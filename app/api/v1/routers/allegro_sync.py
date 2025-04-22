from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Header, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Session, select, func, text
from datetime import timedelta, datetime
import os
import logging
import redis
import json
from app.api.deps import get_db, get_session, get_current_user_from_cookie
from app.models.allegro_token import AllegroToken
from app.models.user import User
from app.models.allegro_order import (
    AllegroOrder, AllegroBuyer, AllegroLineItem, OrderLineItem
)
from app.services.allegro.data_access import get_token_by_id_sync, get_tokens_list_sync, get_token_by_id
from app.celery_app import celery
from app.utils.date_utils import parse_date
from app.api import deps
from app.services.allegro.allegro_api_service import AsyncAllegroApiService
from app.data_access.allegro_order_repository import AllegroOrderRepository
from app.services.allegro.tokens import check_token
from app.utils.logging_config import logger

router = APIRouter()
web_router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

def get_redis_client():
    redis_url = os.getenv("CELERY_REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(redis_url)

async def verify_admin_password(x_admin_password: str = Header(...)):
    if x_admin_password != os.getenv("ADMIN_PASSWORD"):
        raise HTTPException(
            status_code=401,
            detail="Неверный пароль администратора"
        )
    return x_admin_password

@router.post("/start/{token_id}")
def start_sync_tasks(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Запускает периодические задачи синхронизации заказов для указанного токена.
    """
    # Проверяем существование токена
    token = get_token_by_id_sync(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")

    try:
        # Формируем новые расписания для задач
        sync_entry = {
            "task": "app.celery_app.sync_allegro_orders",
            "schedule": 1800, # 1800 секунд = 30 минут
            "args": [token_id]
        }

        client = get_redis_client()
        schedule_raw = client.get("celery_beat_schedule")
        if schedule_raw:
            schedule = json.loads(schedule_raw.decode("utf-8"))
        else:
            schedule = {}

        # Обновляем расписание для обеих задач
        schedule[f"sync-allegro-orders-{token_id}"] = sync_entry

        client.set("celery_beat_schedule", json.dumps(schedule))
        
        # Запускаем первую синхронизацию немедленно
        sync_task = celery.send_task(
            'app.celery_app.sync_allegro_orders',
            args=[token_id]
        )
        
        logger.info(f"Запущены задачи синхронизации для токена {token_id}, sync_task_id: {sync_task.id}")
        
        return {
            "status": "success",
            "message": "Задачи синхронизации успешно запущены",
            "tasks": {
                "sync": {
                    "task_id": sync_task.id,
                    "schedule": {
                        "name": "sync_allegro_orders",
                        "interval": "Каждые 30 минут",
                        "next_run": (datetime.now() + timedelta(minutes=30)).isoformat()
                    }
                }
            }
        }
    except Exception as e:
        logger.error(f"Ошибка при запуске задач синхронизации для токена {token_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске задач синхронизации: {str(e)}"
        )

@router.post("/stop/{token_id}")
def stop_sync_tasks(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Останавливает периодические задачи синхронизации заказов для указанного токена.
    """
    # Проверяем существование токена
    token = get_token_by_id_sync(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")

    try:
        client = get_redis_client()
        schedule_raw = client.get("celery_beat_schedule")
        if schedule_raw:
            schedule = json.loads(schedule_raw.decode("utf-8"))
        else:
            schedule = {}

        sync_key = f"sync-allegro-orders-{token_id}"
        if sync_key in schedule:
            del schedule[sync_key]

        client.set("celery_beat_schedule", json.dumps(schedule))
        return {
            "status": "success",
            "message": "Задачи синхронизации успешно остановлены"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при остановке задач синхронизации: {str(e)}"
        )

@router.get("/status/{token_id}")
def get_sync_status(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Получает статус задач синхронизации для указанного токена.
    """
    # Проверяем существование токена
    token = get_token_by_id_sync(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")
    client = get_redis_client()
    schedule_raw = client.get("celery_beat_schedule")
    if schedule_raw:
        schedule = json.loads(schedule_raw.decode("utf-8"))
    else:
        schedule = {}

    sync_task = f"sync-allegro-orders-{token_id}" in schedule

    return {
        "status": "active" if sync_task else "inactive",
        "tasks": {
            "sync_allegro_orders": {
                "active": sync_task,
                "schedule": "Каждые 30 минут" if sync_task else None
            }
        }
    }

@router.post("/run-once/{token_id}")
def run_sync_once(
    token_id: str,
    from_date: Optional[str] = Query(None, description="Дата в формате DD-MM-YYYY"),
    db: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Запускает однократную синхронизацию заказов для указанного токена.
    
    Args:
        token_id: ID токена
        from_date: Дата в формате DD-MM-YYYY, с которой начать синхронизацию (опционально)
    """
    # Проверяем существование токена
    token = get_token_by_id_sync(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")

    try:
        # Парсим дату
        parsed_date = parse_date(from_date) if from_date else None
        
        # Запускаем задачу синхронизации
        task = celery.send_task('app.celery_app.sync_allegro_orders', args=[token_id, parsed_date])
        
        return {
            "status": "success",
            "message": "Задача синхронизации запущена",
            "task_id": task.id,
            "from_date": from_date
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации: {str(e)}"
        )

@router.get("/tasks")
def list_all_active_tasks(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Получает список всех активных задач синхронизации.
    """
    active_tasks = {}
    tokens = get_tokens_list_sync(db)
    client = get_redis_client()
    schedule_raw = client.get("celery_beat_schedule")
    if schedule_raw:
        schedule = json.loads(schedule_raw.decode("utf-8"))
    else:
        schedule = {}

    for token in tokens:
        token_tasks = {}
        sync_key = f"sync-allegro-orders-{token.id_}"

        if sync_key in schedule:
            token_tasks["sync_allegro_orders"] = { "schedule": "каждые 12 часов",
                "last_run": None
            }
        if token_tasks:
            active_tasks[token.id_] = {
                "account_name": token.account_name,
                "tasks": token_tasks
            }
    return {
        "active_tasks_count": len(active_tasks),
        "tasks": active_tasks
    }


@router.post("/sync-immediate/{token_id}")
def sync_immediate(
    token_id: str,
    from_date: Optional[str] = Query(None, description="Дата в формате DD-MM-YYYY"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Запускает немедленную синхронизацию заказов для указанного токена.
    
    Args:
        token_id: ID токена
        from_date: Дата в формате DD-MM-YYYY, с которой начать синхронизацию (опционально)
    """
    # Проверяем существование токена
    token = get_token_by_id_sync(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")

    try:
        # Парсим дату
        parsed_date = parse_date(from_date)
        
        # Запускаем задачу немедленной синхронизации
        task = celery.send_task('app.celery_app.sync_allegro_orders_immediate', args=[token_id, parsed_date])
        
        return {
            "status": "success",
            "message": "Задача немедленной синхронизации запущена",
            "task_id": task.id,
            "from_date": from_date
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации: {str(e)}"
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


@router.delete("/orders/{token_id}")
async def delete_all_orders(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """
    Удаляет все заказы и связанные данные для указанного токена.
    
    Args:
        token_id: ID токена Allegro
        database: Сессия базы данных
    """
    try:
        # Проверяем токен
        token = await get_token_by_id(database, token_id)
        if not token:
            raise HTTPException(status_code=404, detail="Токен не найден")
        
        # Удаляем данные с помощью SQL запросов в правильном порядке
        # 1. Удаляем связи в таблице order_line_items
        delete_items = text("""
            DELETE FROM order_line_items 
            WHERE order_id IN (
                SELECT id FROM allegro_orders WHERE token_id = :token_id
            )
        """).bindparams(token_id=token_id)
        await database.exec(delete_items)
        
        # 2. Удаляем заказы
        delete_orders = text("""
            DELETE FROM allegro_orders 
            WHERE token_id = :token_id
        """).bindparams(token_id=token_id)
        await database.exec(delete_orders)
        
        # 3. Удаляем неиспользуемые товарные позиции
        delete_unused_items = text("""
            DELETE FROM allegro_line_items 
            WHERE id NOT IN (
                SELECT line_item_id FROM order_line_items
            )
        """)
        await database.exec(delete_unused_items)
        
        # 4. Удаляем неиспользуемых покупателей
        delete_unused_buyers = text("""
            DELETE FROM allegro_buyers 
            WHERE id NOT IN (
                SELECT buyer_id FROM allegro_orders
            )
        """)
        await database.exec(delete_unused_buyers)
        
        await database.commit()
        
        # Удаляем время последней синхронизации из Redis для данного токена
        try:
            client = get_redis_client()
            last_sync_key = f"last_sync_time_{token_id}"
            client.delete(last_sync_key)
            logger.info(f"Время последней синхронизации для токена {token_id} удалено из Redis")
        except Exception as redis_error:
            logger.error(f"Ошибка при очистке Redis для токена {token_id}: {str(redis_error)}")
            # Продолжаем выполнение, так как основные данные уже удалены
            
        return {
            "status": "success",
            "message": "Все заказы и связанные данные для токена успешно удалены"
        }
        
    except Exception as e:
        await database.rollback()
        logger.error(f"Ошибка при удалении заказов: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/backup")
async def backup():
    celery.send_task("app.backup_base")

@web_router.get("/synchronization", response_class=HTMLResponse)
async def get_synchronization_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(deps.get_current_user_optional)
):
    """
    Отображает страницу синхронизации с Allegro.
    """
    if not user:
        return RedirectResponse(url=f"/login?next=/synchronization", status_code=302)
    
    if not user.is_admin:
        return templates.TemplateResponse(
            "base.html",
            {"request": request, "user": user}
        )

    tokens = get_tokens_list_sync(db)
    return templates.TemplateResponse(
        "synchronization.html",
        {"request": request, "tokens": tokens, "user": user}
    )

