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

@router.get("/orders/{token_id}")
async def get_all_orders(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session),
    limit: int = Query(100, ge=1, le=1000, description="Количество заказов на странице"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"), 
    status: Optional[str] = Query(None, description="Фильтр по статусу заказа"),
    from_date: Optional[str] = Query(None, description="Фильтр по дате (DD-MM-YYYY)"),
    to_date: Optional[str] = Query(None, description="Фильтр по дате (DD-MM-YYYY)")
):
    """
    Получает все заказы для указанного токена из базы данных.
    
    Args:
        token_id: ID токена Allegro
        database: Сессия базы данных
        limit: Количество заказов на странице
        offset: Смещение для пагинации
        status: Фильтр по статусу заказа
        from_date: Фильтр по дате начала
        to_date: Фильтр по дате окончания
    """
    try:
        # Формируем базовый запрос
        query = select(AllegroOrder).where(AllegroOrder.token_id == token_id)
        
        # Применяем фильтры
        if status:
            query = query.where(AllegroOrder.status == status)
            
        if from_date:
            parsed_from_date = parse_date(from_date)
            query = query.where(AllegroOrder.updated_at >= parsed_from_date)
            
        if to_date:
            parsed_to_date = parse_date(to_date)
            query = query.where(AllegroOrder.updated_at <= parsed_to_date)
            
        # Получаем общее количество заказов
        count_query = select(func.count()).select_from(query.subquery())
        total_count = await database.scalar(count_query)
        
        # Применяем пагинацию
        query = query.offset(offset).limit(limit)
        
        # Получаем заказы
        result = await database.exec(query)
        orders = result.all()
        
        # Формируем ответ
        orders_data = []
        for order in orders:
            # Загружаем связанные данные
            buyer = await database.get(AllegroBuyer, order.buyer_id) if order.buyer_id else None
            
            # Загружаем позиции заказа
            order_items_query = select(OrderLineItem).where(OrderLineItem.order_id == order.id)
            order_items_result = await database.exec(order_items_query)
            order_items = order_items_result.all()
            
            # Загружаем детали позиций
            line_items = []
            for item in order_items:
                line_item = await database.get(AllegroLineItem, item.line_item_id)
                if line_item:
                    line_items.append({
                        "id": line_item.id,
                        "offer_id": line_item.offer_id,
                        "offer_name": line_item.offer_name,
                        "external_id": line_item.external_id,
                        "original_price": line_item.original_price,
                        "price": line_item.price
                    })
            
            order_dict = {
                "id": order.id,
                "status": order.status,
                "is_stock_updated": order.is_stock_updated,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
                "belongs_to": order.belongs_to,
                "token_id": order.token_id,
                "buyer": None,
                "payment": order.payment,
                "fulfillment": order.fulfillment,
                "delivery": order.delivery,
                "line_items": line_items
            }
            
            # Добавляем данные покупателя
            if buyer:
                order_dict["buyer"] = {
                    "id": buyer.id,
                    "email": buyer.email,
                    "login": buyer.login,
                    "first_name": buyer.first_name,
                    "last_name": buyer.last_name,
                    "company_name": buyer.company_name,
                    "phone_number": buyer.phone_number,
                    "address": buyer.address
                }
            
            orders_data.append(order_dict)
        
        return {
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "orders": orders_data
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении заказов: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))