from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.requests import Request
from app.models.user import User
from fastapi.templating import Jinja2Templates
import logging

from app.api import deps
from app.models.allegro_order import AllegroOrder, AllegroBuyer, AllegroLineItem, OrderLineItem
from app.models.allegro_token import AllegroToken
from app.utils.date_utils import parse_date
from app.utils.logging_config import logger

router = APIRouter()
web_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@web_router.get("/allegro/orders/{token_id}", response_class=HTMLResponse)
async def get_orders_page(
    token_id: str,
    request: Request,
    database: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """Страница с заказами для конкретного аккаунта Allegro."""
    if not current_user:
        return RedirectResponse(url=f"/login?next=/allegro/orders/{token_id}", status_code=302)

    # Получаем информацию о токене
    result = await database.exec(
        select(AllegroToken).where(AllegroToken.id_ == token_id)
    )
    token = result.first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    return templates.TemplateResponse(
        "allegro_orders.html",
        {
            "request": request,
            "user": current_user,
            "account_name": token.account_name,
            "token_id": token_id
        }
    )


