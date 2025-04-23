import logging
from typing import List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.services.allegro import tokens as allegro_tokens
from app.services.allegro.data_access import get_tokens_list, insert_token, delete_token, get_token_by_id
from app.services.allegro.pydantic_models import TokenOfAllegro
from app.services.allegro.pydantic_models import InitializeAuth
from app.models.user import User as UserModel
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from app.core.config import settings

router = APIRouter()
web_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

class InitializeRequest(BaseModel):
    account_name: str

@web_router.get("/connect_allegro")
async def get_allegro_connect(
    request: Request,
    database: AsyncSession = Depends(deps.get_async_session),
    current_user: UserModel = Depends(deps.get_current_user_optional)
):
    if not current_user:
        return RedirectResponse(url=f"/login?next=/connect_allegro", status_code=302)

    return templates.TemplateResponse("connect_allegro.html", {"request": request, "user": current_user})


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
async def initialize_token(request: InitializeRequest):
    """Инициализирует новый токен используя Device Flow."""
    try:
        auth_data = allegro_tokens.initialize_device_flow(request.account_name)
        return auth_data
    except Exception as e:
        logging.error(f"Error initializing auth: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/check/{device_code}")
async def check_auth_status(device_code: str, account_name: str):
    """Проверяет статус авторизации по device_code."""
    try:
        status = allegro_tokens.check_auth_status(device_code, account_name)
        return {"status": status}
    except Exception as e:
        logging.error(f"Error checking auth status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))