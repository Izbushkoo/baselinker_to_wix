from typing import Optional
import uuid
from pydantic import BaseModel, EmailStr, Field


# Shared properties
class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = True
    full_name: Optional[str] = None
    is_admin: Optional[bool]


# Properties to receive via API on creation
class UserCreate(UserBase):
    email: EmailStr
    password: str
    is_admin: bool = False
    tg_nickname: Optional[str] = Field(default_factory=lambda x : str(uuid.uuid4()))

# Properties to receive via API on update
class UserUpdate(UserBase):
    password: Optional[str] = None


class UserInDBBase(UserBase):
    id: Optional[int] = None

    class Config:
        from_attributes = True


# Additional properties to return via API
class User(UserInDBBase):
    pass
