"""
Модель токена Allegro для совместимости с существующим кодом.
Постепенно мигрируется в микросервис.
"""
import uuid
from typing import Optional
from sqlmodel import SQLModel, Field

def uuid_as_string():
    return str(uuid.uuid4())

class AllegroToken(SQLModel, table=True):
    """
    Модель токена Allegro для совместимости.
    TODO: Постепенно заменить на использование микросервиса.
    """
    __tablename__ = "allegro_tokens"
    
    id_: Optional[str] = Field(primary_key=True, default_factory=uuid_as_string)
    belongs_to: str = Field(nullable=False, default="1")
    account_name: Optional[str] = Field(default=None, nullable=True, unique=True)
    description: Optional[str] = Field(default=None, nullable=True)
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_url: str = ""
