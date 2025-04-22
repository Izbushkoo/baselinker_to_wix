import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.services.allegro import tokens as allegro_tokens
from app.services.allegro.data_access import get_tokens_list, insert_token, delete_token, get_token_by_id
from app.services.allegro.pydantic_models import TokenOfAllegro
from app.services.allegro.pydantic_models import InitializeAuth
from app.models.user import User as UserModel


router = APIRouter()


@router.get("/")
async def get_tokens(
    user_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """Получает список всех токенов для пользователя."""
    logging.info(f"Access to allegro tokens list")
    tokens = await get_tokens_list(database, user_id)
    return [TokenOfAllegro(**token.model_dump(exclude_none=True)) for token in tokens]


@router.post("/add")
async def add_account(account_data: TokenOfAllegro, database: AsyncSession = Depends(deps.get_async_session)):

    logging.info(f"Access to allegro tokens add")
    written_token = await insert_token(database, account_data)

    return TokenOfAllegro(**written_token.model_dump(exclude_none=True))


@router.post("/initialize")
async def initialize_token(
    init_auth: InitializeAuth,
):
    """Инициализирует новый токен."""
    logging.info(f"Access to initialize auth with config {init_auth}")
    return allegro_tokens.initialize_auth(init_auth)


@router.get("/{token_id}")
async def get_token(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """Получает токен по ID."""
    logging.info(f"Access to allegro token get by ID")
    token = await get_token_by_id(database, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")
    return token


@router.delete("/{token_id}")
async def delete_token_route(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """Удаляет токен по ID."""
    logging.info(f"Access to allegro tokens add")
    try:
        token = await delete_token(database, token_id)
    except Exception :
        return HTTPException(404, "Smth went wrong. Not deleted or not exists")
    else:
        return TokenOfAllegro(**token.model_dump(exclude_none=True))