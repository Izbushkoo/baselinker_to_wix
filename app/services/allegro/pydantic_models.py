from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class InitializeAuth(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )
    user_id: str
    client_id: str
    client_secret: str
    account_name: str
    account_description: Optional[str | None] = Field(default=None)
    callback_url: Optional[str | None] = Field(default=None)


class TokenOfAllegro(BaseModel):
    id_: Optional[str]
    account_name: Optional[str]
    redirect_url: Optional[str]
    client_id: Optional[str]
