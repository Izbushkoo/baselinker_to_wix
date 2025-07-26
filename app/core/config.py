import os
import logging
import secrets
from typing import Any, Dict, List, Optional, Union

from pydantic import AnyHttpUrl, HttpUrl, PostgresDsn, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv

load_dotenv()

# Затем проверяем, запущено ли приложение в Docker
is_docker = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")

# Если запущено в Docker, перезагружаем переменные из .env.docker
if is_docker:
    load_dotenv(".env.docker", override=True)


class Settings(BaseSettings):
    API_V1_STR: str = "/api"

    # Используем значение из .env или генерируем новое, если его нет
    SECRET_KEY: str = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))

    # Telegram Bot settings
    NOTIFICATOR_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_URL: Optional[str] = None
    TELEGRAM_WEBAPP_URL: Optional[str] = None

    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    # BACKEND_CORS_ORIGINS is a JSON-formatted list of origins
    # e.g: '["http://localhost", "http://localhost:4200", "http://localhost:3000"]'
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode='before')
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    PROJECT_NAME: str = "baselinker_to_wix"

    SENTRY_DSN: Optional[HttpUrl] = None

    POSTGRES_SERVER: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None
    SQLALCHEMY_DATABASE_URI_ASYNC: Optional[PostgresDsn] = None
    
    # Удаленная БД для цен
    PRICES_DB_URI: Optional[str] = None
    PRICES_DB_URI_ASYNC: Optional[str] = None
    
    ALLEGRO_CLIENT_ID: str
    ALLEGRO_CLIENT_SECRET: str
    MICRO_SERVICE_URL: str

    @field_validator("SQLALCHEMY_DATABASE_URI", mode='before')
    def assemble_db_connection(cls, v: Optional[str], values: ValidationInfo) -> Any:
        if isinstance(v, str) and v is not None:
            return v
        return PostgresDsn.build(
            scheme="postgresql",
            username=values.data.get("POSTGRES_USER"),
            password=values.data.get("POSTGRES_PASSWORD"),
            host=values.data.get("POSTGRES_SERVER"),
            path=f"{values.data.get('POSTGRES_DB') or ''}",
        )

    @field_validator("SQLALCHEMY_DATABASE_URI_ASYNC", mode='before')
    def assemble_db_connection_async(cls, v: Optional[str], values: ValidationInfo) -> Any:
        if isinstance(v, str) and v is not None:
            return v
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=values.data.get("POSTGRES_USER"),
            password=values.data.get("POSTGRES_PASSWORD"),
            host=values.data.get("POSTGRES_SERVER"),
            path=f"{values.data.get('POSTGRES_DB') or ''}",
        )

    model_config = SettingsConfigDict(case_sensitive=True)


settings = Settings()
logging.info(f"settings {settings}")