from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.schemas import PostCreate, PostResponse, UserRead, UserCreate, UserUpdate
from app.db import Post, Like, Comment, Follow, create_db_and_tables, get_async_session, User
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
from sqlalchemy import select, func
from app.users import auth_backend, current_active_user, fastapi_users
from dotenv import load_dotenv
from imagekitio import ImageKit
import os, uuid
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

# Allow the local Streamlit frontend to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fastapi_users.get_auth_router(auth_backend),         prefix="/auth/jwt", tags=["auth"])
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth",     tags=["auth"])
app.include_router(fastapi_users.get_reset_password_router(),            prefix="/auth",     tags=["auth"])
app.include_router(fastapi_users.get_verify_router(UserRead),            prefix="/auth",     tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/auth",     tags=["auth"])

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

    result = await session.execute(select(User))
    users = [row[0] for row in result.all()]
    user_dict = {
        u.id: {
            "email": u.email,
            "display_name": _display_name_from_email(u.email),
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

    posts_data = []
    for post in posts:
        posts_data.append({
            "id":          str(post.id),
            "caption":     post.caption,
            "url":         post.url,
            "file_type":   post.file_type,
            "file_name":   post.file_name,
            "created_at":  post.created_at.isoformat(),
            "is_owner":    post.user_id == user.id,
            "email":       user_dict.get(post.user_id, {}).get("email", "Unknown"),
            "display_name": user_dict.get(post.user_id, {}).get("display_name", "User"),
            "like_count":  like_counts.get(post.id, 0),
            "is_liked":    post.id in liked_post_ids,
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
    user_dict = {
        u.id: {
            "email": u.email,
            "display_name": _display_name_from_email(u.email),
        }
        for u in user_result.scalars().all()
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
        "followers":      followers_count.scalar(),
        "following":      following_count.scalar(),
        "post_count":     post_count.scalar(),
        "is_following":   is_following_result.scalars().first() is not None,
    }
