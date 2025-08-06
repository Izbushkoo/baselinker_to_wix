
from requests.exceptions import HTTPError
import logging
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Cookie
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
from app.core.security import create_access_token
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient


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
    micro_token_client = AllegroTokenMicroserviceClient(
        base_url=settings.MICRO_SERVICE_URL,
        jwt_token=create_access_token(user_id=settings.PROJECT_NAME),
        timeout=10
    )
    logging.info(f"Access to allegro tokens list")

    tokens_response = micro_token_client.get_user_tokens(user_id, active_only=True)
    # Получаем данные из GenericListResponse.items
    return [TokenOfAllegro(**token) for token in tokens_response.items]


@router.post("/initialize")
async def initialize_token(request: InitializeRequest):

    micro_token_client = AllegroTokenMicroserviceClient(
        base_url=settings.MICRO_SERVICE_URL,
        jwt_token=create_access_token(user_id=settings.PROJECT_NAME),
        timeout=10
    )

    """Инициализирует новый токен используя Device Flow."""
    try: 
        auth_response = micro_token_client.initialize_auth(request.account_name)
        # Возвращаем данные из AuthInitializeResponse
        return {
            "device_code": auth_response.device_code,
            "user_code": auth_response.user_code,
            "verification_uri": auth_response.verification_uri,
            "verification_uri_complete": auth_response.verification_uri_complete,
            "expires_in": auth_response.expires_in,
            "interval": auth_response.interval,
            "task_id": auth_response.task_id
        }

    except HTTPError as http_err:
        # HTTPError.response — это объект requests.Response
        resp = http_err.response
        body = resp.json()
        raw = body.get("detail", body)
        # пробуем вычитать JSON, иначе — текст
        detail = raw if isinstance(raw, str) else json.dumps(raw)
        # пробрасываем код и тело из микросервиса
        raise HTTPException(status_code=resp.status_code, detail=detail)

    except Exception as e:
        logging.error(f"Error initializing auth: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{token_id}")
async def delete_token_route(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """Удаляет токен по ID и все связанные заказы и связанные сущности."""
    logging.info(f"Access to allegro tokens delete")
    try:
  
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            ),
            base_url=settings.MICRO_SERVICE_URL
        )

        delete_response = token_client.delete_token(token_id=token_id)
        # Возвращаем данные из GenericResponse.data
        return delete_response.data
    except Exception as e:
        logging.error(f"Ошибка при удалении токена и заказов: {e}")
        await database.rollback()
        raise HTTPException(500, "Ошибка при удалении токена и связанных заказов")


@router.get("/check/{task_id}")
async def check_auth_status(task_id: str, account_name: str):

    """Проверяет статус авторизации по device_code и account_name"""

    micro_token_client = AllegroTokenMicroserviceClient(
        base_url=settings.MICRO_SERVICE_URL,
        jwt_token=create_access_token(user_id=settings.PROJECT_NAME),
        timeout=10
    )

    try:
        status_response = micro_token_client.get_auth_task_status(task_id)
        # Возвращаем данные из TaskStatusResponse
        return {
            "task_id": status_response.task_id,
            "status": status_response.status,
            "result": status_response.result,
            "progress": status_response.progress
        }
    except Exception as e:
        logging.error(f"Error checking auth status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



