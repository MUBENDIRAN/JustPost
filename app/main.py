from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from app.schemas import PostCreate, PostResponse, UserRead, UserCreate, UserUpdate
from app.db import (
    Post,
    Like,
    Comment,
    Follow,
    UserProfile,
    create_db_and_tables,
    get_async_session,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
from sqlalchemy import select, func
from app.users import auth_backend, current_active_user, fastapi_users
from dotenv import load_dotenv
from imagekitio import ImageKit
import os, uuid
from datetime import date
from pydantic import BaseModel

load_dotenv()

imagekit = ImageKit(
    private_key=os.getenv("IMAGEKIT_PRIVATE_KEY"),
)


def _display_name_from_email(email: str | None) -> str:
    if not email:
        return "User"
    local_part = email.split("@", 1)[0]
    cleaned = local_part.replace(".", " ").replace("_", " ").strip()
    return cleaned.title() if cleaned else "User"


def _normalize_custom_username(custom_username: str | None) -> str | None:
    if custom_username is None:
        return None
    normalized = custom_username.strip().lower()
    if not normalized:
        return None
    if len(normalized) < 3 or len(normalized) > 30:
        raise HTTPException(
            status_code=400,
            detail="Username must be between 3 and 30 characters",
        )
    if not all(ch.isalnum() or ch in {"_", "."} for ch in normalized):
        raise HTTPException(
            status_code=400,
            detail="Username can only contain letters, numbers, underscores, and dots",
        )
    return normalized


def _display_name_for_user(email: str | None, profile: UserProfile | None) -> str:
    if profile and profile.custom_username:
        return profile.custom_username
    return _display_name_from_email(email)


async def _get_user_profile_map(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, UserProfile]:
    if not user_ids:
        return {}
    profiles_result = await session.execute(
        select(UserProfile).where(UserProfile.user_id.in_(user_ids))
    )
    profiles = profiles_result.scalars().all()
    return {profile.user_id: profile for profile in profiles}


def _profile_payload(user: User, profile: UserProfile | None) -> dict:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "display_name": _display_name_for_user(user.email, profile),
        "custom_username": profile.custom_username if profile else None,
        "birthday": (
            profile.birthday.isoformat()
            if profile and profile.birthday
            else None
        ),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

# Allow both local and deployed Streamlit frontend to call the API.
# Get frontend URL from environment variable
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8501")
allowed_origins = ["http://localhost:8501"]
if FRONTEND_URL and FRONTEND_URL not in allowed_origins:
    allowed_origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fastapi_users.get_auth_router(auth_backend),         prefix="/auth/jwt", tags=["auth"])
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth",     tags=["auth"])
app.include_router(fastapi_users.get_reset_password_router(),            prefix="/auth",     tags=["auth"])
app.include_router(fastapi_users.get_verify_router(UserRead),            prefix="/auth",     tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/auth",     tags=["auth"])

@app.get("/health", tags=["health"])
async def health_check(response: Response):
    # Allow CORS from any origin for health checks so index.html can verify backend is up
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return {"status": "ok"}

@app.options("/health", tags=["health"])
async def health_check_options(response: Response):
    # Handle CORS preflight requests for health endpoint
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return {}

@app.post("/upload", tags=["posts"])
async def upload_file(
    file: UploadFile = File(...),
    caption: str = Form(""),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        upload_name = file.filename or f"upload_{uuid.uuid4().hex}"

        upload_result = imagekit.files.upload(
            file=file_bytes,
            file_name=upload_name,
        )

        uploaded_url = getattr(upload_result, "url", None)
        uploaded_name = getattr(upload_result, "name", None) or upload_name
        if not uploaded_url:
            raise HTTPException(status_code=500, detail="ImageKit upload failed: missing URL")

        post = Post(
            user_id=user.id,
            caption=caption,
            url=uploaded_url,
            file_type="video" if file.content_type.startswith("video/") else "image",
            file_name=uploaded_name
        )
        session.add(post)
        await session.commit()
        await session.refresh(post)

        return {"success": True, "post_id": str(post.id)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        file.file.close()


@app.get("/feed", tags=["posts"])
async def get_feed(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
    skip: int = 0,
    limit: int = 20
):
    result = await session.execute(
        select(Post).order_by(Post.created_at.desc()).offset(skip).limit(limit)
    )
    posts = [row[0] for row in result.all()]

    user_ids = list({p.user_id for p in posts})
    users: list[User] = []
    if user_ids:
        result = await session.execute(select(User).where(User.id.in_(user_ids)))
        users = list(result.scalars().all())
    profile_map = await _get_user_profile_map(session, user_ids)

    user_dict = {
        u.id: {
            "email": u.email,
            "display_name": _display_name_for_user(u.email, profile_map.get(u.id)),
        }
        for u in users
    }

    # Fetch like counts in one query to avoid per-post queries.
    post_ids = [p.id for p in posts]
    like_counts = {}
    if post_ids:
        like_result = await session.execute(
            select(Like.post_id, func.count(Like.id))
            .where(Like.post_id.in_(post_ids))
            .group_by(Like.post_id)
        )
        like_counts = {row[0]: row[1] for row in like_result.all()}

    # Fetch the current user's liked posts once for quick membership checks.
    liked_result = await session.execute(
        select(Like.post_id).where(Like.user_id == user.id)
    )
    liked_post_ids = {row[0] for row in liked_result.all()}

    author_ids = {post.user_id for post in posts if post.user_id != user.id}
    followed_author_ids = set()
    if author_ids:
        followed_result = await session.execute(
            select(Follow.following_id).where(
                Follow.follower_id == user.id,
                Follow.following_id.in_(author_ids),
            )
        )
        followed_author_ids = {row[0] for row in followed_result.all()}

    posts_data = []
    for post in posts:
        posts_data.append({
            "id":          str(post.id),
            "caption":     post.caption,
            "url":         post.url,
            "file_type":   post.file_type,
            "file_name":   post.file_name,
            "created_at":  post.created_at.isoformat(),
            "author_id":   str(post.user_id),
            "is_owner":    post.user_id == user.id,
            "email":       user_dict.get(post.user_id, {}).get("email", "Unknown"),
            "display_name": user_dict.get(post.user_id, {}).get("display_name", "User"),
            "like_count":  like_counts.get(post.id, 0),
            "is_liked":    post.id in liked_post_ids,
            "is_following_author": post.user_id in followed_author_ids,
        })

    return {"posts": posts_data}


@app.delete("/posts/{post_id}", tags=["posts"])
async def delete_post(
    post_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    try:
        post_uuid = uuid.UUID(post_id)
        result = await session.execute(select(Post).where(Post.id == post_uuid))
        post = result.scalars().first()

        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.user_id != user.id:
            raise HTTPException(status_code=403, detail="You don't have permission to delete this post")

        await session.delete(post)
        await session.commit()
        return {"success": True, "message": "Post deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/posts/{post_id}/like", tags=["likes"])
async def like_post(
    post_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    post_uuid = uuid.UUID(post_id)

    result = await session.execute(select(Post).where(Post.id == post_uuid))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Post not found")

    result = await session.execute(
        select(Like).where(Like.user_id == user.id, Like.post_id == post_uuid)
    )
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Already liked")

    like = Like(user_id=user.id, post_id=post_uuid)
    session.add(like)
    await session.commit()
    return {"success": True, "message": "Post liked"}


@app.delete("/posts/{post_id}/like", tags=["likes"])
async def unlike_post(
    post_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    post_uuid = uuid.UUID(post_id)
    result = await session.execute(
        select(Like).where(Like.user_id == user.id, Like.post_id == post_uuid)
    )
    like = result.scalars().first()
    if not like:
        raise HTTPException(status_code=404, detail="Like not found")

    await session.delete(like)
    await session.commit()
    return {"success": True, "message": "Post unliked"}

class CommentCreate(BaseModel):
    text: str


class ProfileUpdate(BaseModel):
    custom_username: str | None = None
    birthday: date | None = None


@app.post("/posts/{post_id}/comments", tags=["comments"])
async def add_comment(
    post_id: str,
    body: CommentCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    post_uuid = uuid.UUID(post_id)
    result = await session.execute(select(Post).where(Post.id == post_uuid))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Post not found")

    comment = Comment(user_id=user.id, post_id=post_uuid, text=body.text)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return {"success": True, "comment_id": str(comment.id)}


@app.get("/posts/{post_id}/comments", tags=["comments"])
async def get_comments(
    post_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    post_uuid = uuid.UUID(post_id)
    result = await session.execute(
        select(Comment).where(Comment.post_id == post_uuid).order_by(Comment.created_at.asc())
    )
    comments = result.scalars().all()

    user_ids = list({c.user_id for c in comments})
    user_result = await session.execute(select(User).where(User.id.in_(user_ids)))
    users = user_result.scalars().all()
    profile_map = await _get_user_profile_map(session, user_ids)

    user_dict = {
        u.id: {
            "email": u.email,
            "display_name": _display_name_for_user(u.email, profile_map.get(u.id)),
        }
        for u in users
    }

    return {
        "comments": [
            {
                "id":         str(c.id),
                "text":       c.text,
                "email":      user_dict.get(c.user_id, {}).get("email", "Unknown"),
                "display_name": user_dict.get(c.user_id, {}).get("display_name", "User"),
                "created_at": c.created_at.isoformat(),
                "is_owner":   c.user_id == user.id,
            }
            for c in comments
        ]
    }


@app.delete("/comments/{comment_id}", tags=["comments"])
async def delete_comment(
    comment_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    comment_uuid = uuid.UUID(comment_id)
    result = await session.execute(select(Comment).where(Comment.id == comment_uuid))
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your comment")

    await session.delete(comment)
    await session.commit()
    return {"success": True, "message": "Comment deleted"}

@app.post("/users/{user_id}/follow", tags=["follow"])
async def follow_user(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    target_uuid = uuid.UUID(user_id)
    if target_uuid == user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    result = await session.execute(
        select(Follow).where(Follow.follower_id == user.id, Follow.following_id == target_uuid)
    )
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Already following")

    follow = Follow(follower_id=user.id, following_id=target_uuid)
    session.add(follow)
    await session.commit()
    return {"success": True, "message": "Followed"}


@app.delete("/users/{user_id}/follow", tags=["follow"])
async def unfollow_user(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    target_uuid = uuid.UUID(user_id)
    result = await session.execute(
        select(Follow).where(Follow.follower_id == user.id, Follow.following_id == target_uuid)
    )
    follow = result.scalars().first()
    if not follow:
        raise HTTPException(status_code=404, detail="Not following")

    await session.delete(follow)
    await session.commit()
    return {"success": True, "message": "Unfollowed"}


@app.get("/users/{user_id}/profile", tags=["follow"])
async def get_profile(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
):
    target_uuid = uuid.UUID(user_id)
    user_result = await session.execute(select(User).where(User.id == target_uuid))
    target_user = user_result.scalars().first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_profile_result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == target_uuid)
    )
    target_profile = target_profile_result.scalars().first()

    followers_count = await session.execute(
        select(func.count(Follow.id)).where(Follow.following_id == target_uuid)
    )
    following_count = await session.execute(
        select(func.count(Follow.id)).where(Follow.follower_id == target_uuid)
    )
    post_count = await session.execute(
        select(func.count(Post.id)).where(Post.user_id == target_uuid)
    )
    is_following_result = await session.execute(
        select(Follow).where(Follow.follower_id == user.id, Follow.following_id == target_uuid)
    )

    return {
        "user_id":        user_id,
        "display_name":   _display_name_for_user(target_user.email, target_profile),
        "custom_username": target_profile.custom_username if target_profile else None,
        "birthday": (
            target_profile.birthday.isoformat()
            if target_profile and target_profile.birthday
            else None
        ),
        "followers":      followers_count.scalar(),
        "following":      following_count.scalar(),
        "post_count":     post_count.scalar(),
        "is_following":   is_following_result.scalars().first() is not None,
    }


@app.get("/users/profile/me", tags=["profile"])
async def get_my_profile(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    profile_result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = profile_result.scalars().first()
    payload = _profile_payload(user, profile)
    return payload


@app.put("/users/profile/me", tags=["profile"])
async def update_my_profile(
    body: ProfileUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    normalized_username = _normalize_custom_username(body.custom_username)

    if normalized_username is not None:
        existing = await session.execute(
            select(UserProfile).where(
                UserProfile.custom_username == normalized_username,
                UserProfile.user_id != user.id,
            )
        )
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="Username already taken")

    profile_result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = profile_result.scalars().first()
    if not profile:
        profile = UserProfile(user_id=user.id)
        session.add(profile)

    profile.custom_username = normalized_username
    profile.birthday = body.birthday
    await session.commit()
    await session.refresh(profile)
    return _profile_payload(user, profile)


@app.get("/users/{user_id}/followers", tags=["follow"])
async def get_user_followers(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    target_uuid = uuid.UUID(user_id)

    target_result = await session.execute(select(User).where(User.id == target_uuid))
    if not target_result.scalars().first():
        raise HTTPException(status_code=404, detail="User not found")

    followers_result = await session.execute(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.following_id == target_uuid)
        .order_by(User.email.asc())
    )
    followers = list(followers_result.scalars().all())
    follower_ids = [u.id for u in followers]
    profile_map = await _get_user_profile_map(session, follower_ids)

    my_following_result = await session.execute(
        select(Follow.following_id).where(
            Follow.follower_id == user.id,
            Follow.following_id.in_(follower_ids),
        )
    )
    my_following_ids = {row[0] for row in my_following_result.all()}

    return {
        "followers": [
            {
                "user_id": str(f.id),
                "display_name": _display_name_for_user(f.email, profile_map.get(f.id)),
                "custom_username": (
                    profile_map.get(f.id).custom_username
                    if profile_map.get(f.id)
                    else None
                ),
                "is_me": f.id == user.id,
                "is_following": f.id in my_following_ids,
            }
            for f in followers
        ]
    }


@app.get("/users/{user_id}/following", tags=["follow"])
async def get_user_following(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    target_uuid = uuid.UUID(user_id)

    target_result = await session.execute(select(User).where(User.id == target_uuid))
    if not target_result.scalars().first():
        raise HTTPException(status_code=404, detail="User not found")

    following_result = await session.execute(
        select(User)
        .join(Follow, Follow.following_id == User.id)
        .where(Follow.follower_id == target_uuid)
        .order_by(User.email.asc())
    )
    following_users = list(following_result.scalars().all())
    following_ids = [u.id for u in following_users]
    profile_map = await _get_user_profile_map(session, following_ids)

    my_following_result = await session.execute(
        select(Follow.following_id).where(
            Follow.follower_id == user.id,
            Follow.following_id.in_(following_ids),
        )
    )
    my_following_ids = {row[0] for row in my_following_result.all()}

    return {
        "following": [
            {
                "user_id": str(f.id),
                "display_name": _display_name_for_user(f.email, profile_map.get(f.id)),
                "custom_username": (
                    profile_map.get(f.id).custom_username
                    if profile_map.get(f.id)
                    else None
                ),
                "is_me": f.id == user.id,
                "is_following": f.id in my_following_ids,
            }
            for f in following_users
        ]
    }
