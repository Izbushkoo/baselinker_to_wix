"""
DEPRECATED: Модель перенесена в микросервис.
Оставлена минимальная заглушка для совместимости.
"""
import uuid
from typing import Optional, List
from sqlmodel import SQLModel, Field

def uuid_as_string():
    return str(uuid.uuid4())

class AllegroToken(SQLModel, table=False):
    """
    DEPRECATED: Используйте микросервис для работы с токенами Allegro.
    Эта модель оставлена только для совместимости существующего кода.
    """
    id_: Optional[str] = Field(primary_key=True, default_factory=uuid_as_string)
    belongs_to: str = Field(nullable=False, default="1")
    account_name: Optional[str] = Field(default=None, nullable=True)
    description: Optional[str] = Field(default=None, nullable=True)
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_url: str = ""
    
    def __init__(self, **data):
        super().__init__(**data)
        raise NotImplementedError("AllegroToken перенесен в микросервис. Используйте AllegroTokenMicroserviceClient")
