from collections.abc import AsyncGenerator
import uuid
import os
from urllib.parse import quote_plus
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
import datetime
from fastapi_users.db import SQLAlchemyUserDatabase, SQLAlchemyBaseUserTableUUID
from fastapi import Depends
from dotenv import load_dotenv


load_dotenv()


def _normalize_database_url(raw_url: str) -> str:
    if raw_url.startswith("postgres://"):
        raw_url = f"postgresql://{raw_url[len('postgres://'):]}"
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if raw_url.startswith("postgresql+asyncpg://"):
        return raw_url
    raise RuntimeError(
        "DATABASE_URL must start with postgres://, postgresql://, or postgresql+asyncpg://"
    )


def _build_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return _normalize_database_url(database_url)

    host = os.getenv("PGHOST") or os.getenv("POSTGRES_HOST")
    port = os.getenv("PGPORT") or os.getenv("POSTGRES_PORT") or "5432"
    database = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")
    user = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
    password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD") or ""
    sslmode = os.getenv("PGSSLMODE") or os.getenv("POSTGRES_SSLMODE")

    if not host or not database or not user:
        raise RuntimeError(
            "Set DATABASE_URL, or set PGHOST/PGDATABASE/PGUSER (optionally PGPORT, PGPASSWORD, PGSSLMODE)."
        )

    user_part = quote_plus(user)
    if password:
        user_part = f"{user_part}:{quote_plus(password)}"

    url = f"postgresql+asyncpg://{user_part}@{host}:{port}/{database}"
    if sslmode:
        url = f"{url}?sslmode={sslmode}"
    return url


DATABASE_URL = _build_database_url()


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    posts    = relationship(argument="Post",    back_populates="user",      cascade="all, delete-orphan")
    likes    = relationship(argument="Like",    back_populates="user",      cascade="all, delete-orphan")
    comments = relationship(argument="Comment", back_populates="user",      cascade="all, delete-orphan")
    followers = relationship(
        argument="Follow",
        foreign_keys="Follow.following_id",
        back_populates="following",
        cascade="all, delete-orphan"
    )
    following = relationship(
        argument="Follow",
        foreign_keys="Follow.follower_id",
        back_populates="follower",
        cascade="all, delete-orphan"
    )


class Post(Base):
    __tablename__ = "posts"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    caption    = Column(Text, nullable=True)
    url        = Column(String, nullable=False)
    file_type  = Column(String, nullable=False)
    file_name  = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user     = relationship(argument="User",    back_populates="posts")
    likes    = relationship(argument="Like",    back_populates="post", cascade="all, delete-orphan")
    comments = relationship(argument="Comment", back_populates="post", cascade="all, delete-orphan")


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="unique_like"),)

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("user.id"),  nullable=False)
    post_id    = Column(UUID(as_uuid=True), ForeignKey("posts.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship(argument="User", back_populates="likes")
    post = relationship(argument="Post", back_populates="likes")


class Comment(Base):
    __tablename__ = "comments"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("user.id"),  nullable=False)
    post_id    = Column(UUID(as_uuid=True), ForeignKey("posts.id"), nullable=False)
    text       = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship(argument="User", back_populates="comments")
    post = relationship(argument="Post", back_populates="comments")


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("follower_id", "following_id", name="unique_follow"),)

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    follower_id  = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    following_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    created_at   = Column(DateTime, default=datetime.datetime.utcnow)

    follower  = relationship(argument="User", foreign_keys=[follower_id],  back_populates="following")
    following = relationship(argument="User", foreign_keys=[following_id], back_populates="followers")


engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)
