from pydantic import BaseModel
from fastapi_users import schemas
import uuid
from typing import Optional
from datetime import datetime


class PostCreate(BaseModel):
    caption: Optional[str] = ""


class PostResponse(BaseModel):
    id: str
    caption: Optional[str] = ""
    url: str
    file_type: str
    file_name: str
    created_at: str
    is_owner: bool
    email: str

    class Config:
        from_attributes = True


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass
