from typing import Optional
import uuid
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    email: str
    password: str
    is_admin: bool = False
    is_active: bool = True
    tg_nickname: str = Field(default_factory=lambda x : str(uuid.uuid4()), unique=True)
