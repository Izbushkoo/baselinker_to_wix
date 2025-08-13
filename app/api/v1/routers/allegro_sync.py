from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Header, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Session, select, func, text
from datetime import timedelta, datetime
from uuid import UUID
import os
import logging
import redis
import json
from app.api.deps import get_db, get_session 
from app.models.user import User

from app.celery_app import celery, launch_wix_sync
from app.utils.date_utils import parse_date
from app.api import deps
from app.utils.logging_config import logger
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.Allegro_Microservice.sync_endpoint import SyncClient
from app.core.security import create_access_token
from app.core.config import settings

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

    try:
        # Парсим дату
        parsed_date = parse_date(from_date)
        sync_client = SyncClient(
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME,
            ),
            base_url=settings.MICRO_SERVICE_URL
        )
        sync_response = sync_client.start_sync(
            token_id=token_id,
            sync_from_date=parsed_date
        )
        
        # Получаем данные из GenericResponse.data
        task_data = sync_response.data
        
        return {
            "status": "success",
            "message": "Задача немедленной синхронизации запущена",
            "task_id": task_data.get("task_id"),
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
        orders_client = OrdersClient(
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            ),
            base_url=settings.MICRO_SERVICE_URL
        )
        orders_response = orders_client.get_orders(
            token_id=UUID(token_id),
            limit=limit,
            offset=offset,
            status=status,
            from_date=from_date,
            to_date=to_date
        )

        # Получаем данные из OrdersListResponse
        orders = orders_response.orders
        pagination = orders_response.pagination

        orders_data = []
        for order in orders:
            technical_flags = order.get("technical_flags", {})
            
            # Загружаем позиции заказа
            line_items = order.get("lineItems", [])
            
            
            order_dict = {
                "id": order.get("id"),
                "status": order.get("status"),
                "is_stock_updated": technical_flags.get("is_stock_updated"),
                "has_invoice_created": technical_flags.get("has_invoice_created"),
                "updated_at": order.get("updatedAt") if order.get("updatedAt") else None,
                "token_id": order.get("token_id") or None,
                "buyer": order.get("buyer", {}),
                "payment": order.get("payment", {}),
                "fulfillment": order.get("fulfillment", {}),
                "delivery": order.get("delivery", {}),
                "line_items": line_items,
                "summary": order.get("summary", {})
            }
            
            orders_data.append(order_dict)
        
        return {
            "total": pagination.total,
            "offset": pagination.offset,
            "limit": pagination.limit,
            "orders": orders_data
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении заказов: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/search/{token_id}/{query}")
async def search_orders(
    token_id: str,
    query: str,
    limit: int = Query(100, ge=1, le=1000, description="Количество заказов на странице"),
):
    """
    Получает все заказы для указанного токена из базы данных.
    
    Args:
        token_id: ID токена Allegro
        query: Поисковой запрос
        limit: Количество заказов в ответе
    """
    try:
        orders_client = OrdersClient(
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            ),
            base_url=settings.MICRO_SERVICE_URL
        )
        search_response = orders_client.search_orders(
            token_id=UUID(token_id),
            query=query,
            limit=limit,
        )

        # Получаем данные из OrdersListResponse
        orders = search_response.orders
        logging.info(f"orders result {orders}")
        pagination = search_response.pagination

        orders_data = []
        for order in orders:
            technical_flags = order.get("technical_flags", {})
            logging.info(f"{technical_flags}")
            # Загружаем позиции заказа
            line_items = order.get("lineItems", [])
            
            
            order_dict = {
                "id": order.get("id"),
                "status": order.get("status"),
                "is_stock_updated": technical_flags.get("is_stock_updated"),
                "has_invoice_created": technical_flags.get("has_invoice_created"),
                "updated_at": order.get("updatedAt") if order.get("updatedAt") else None,
                "token_id": order.get("token_id") or None,
                "buyer": order.get("buyer", {}),
                "payment": order.get("payment", {}),
                "fulfillment": order.get("fulfillment", {}),
                "delivery": order.get("delivery", {}),
                "line_items": line_items,
                "summary": order.get("summary", {})
            }
            
            orders_data.append(order_dict)
        
        return {
            "total": pagination.total,
            "offset": pagination.offset,
            "limit": pagination.limit,
            "orders": orders_data
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении заказов: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/backup")
async def backup():
    celery.send_task("app.backup_base")

@router.post("/check-stock")
def check_stock(
) -> Dict[str, Any]:
    """
    Запускает немедленную проверку и обновление стоков для заказов из микросервиса.
    """
    try:
        # Запускаем задачу проверки стоков с параметрами
        task = celery.send_task(
            'app.celery_app.check_and_update_stock',
        )
        
        return {
            "status": "success",
            "message": "Задача проверки стоков запущена",
            "task_id": task.id,
        }
    except Exception as e:
        logger.error(f"Ошибка при запуске проверки стоков: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске проверки стоков: {str(e)}"
        )

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

    # tokens = get_tokens_list_sync(db)
    micro_service_client = AllegroTokenMicroserviceClient(
        jwt_token=create_access_token(
            user_id=settings.PROJECT_NAME
        )
    )

    tokens_response = micro_service_client.get_tokens(per_page=20)
    # Получаем данные из GenericListResponse.items
    tokens = tokens_response.items
    logging.info(f"{tokens}")

    return templates.TemplateResponse(
        "synchronization.html",
        {"request": request, "tokens": tokens, "user": user}
    )

@router.post("/start-events/{token_id}")
def start_events_task(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Запускает периодическую задачу обработки событий заказов для указанного токена.
    """
    try:
        sync_client = SyncClient(
            base_url=settings.MICRO_SERVICE_URL,
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            )
        )

        activation_response = sync_client.activate_sync(token_id=token_id, interval_minutes=2)
        logger.info(f"Запущена задача обработки событий для токена {token_id}")
        
        return {
            "status": "success",
            "message": "Задача обработки событий успешно запущена"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации: {str(e)}"
        )

@router.post("/stop-events/{token_id}")
def stop_events_task(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Останавливает периодическую задачу обработки событий заказов для указанного токена.
    """
    try:
        sync_client = SyncClient(
            base_url=settings.MICRO_SERVICE_URL,
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            )
        )

        deactivation_response = sync_client.deactivate_sync(token_id=token_id)

        return {
            "status": "success",
            "message": "Задача обработки событий успешно остановлена"
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при остановке синхронизации: {str(e)}"
        )

@router.get("/status-events/{token_id}")
def get_events_status(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Получает статус задачи обработки событий для указанного токена.
    """
    try:
        sync_client = SyncClient(
            base_url=settings.MICRO_SERVICE_URL,
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            )
        )

        status_response = sync_client.get_token_sync_status(token_id=UUID(token_id))
        logging.info(f"task response {status_response}")
        return {
            "status": "active" if status_response.is_active else "inactive",
            "task": {
                "token_id": status_response.token_id,
                "is_active": status_response.is_active,
                "interval_minutes": status_response.interval_minutes,
                "status": status_response.status,
                "task_name": status_response.task_name,
                "last_run_at": status_response.last_run_at,
                "last_success_at": status_response.last_success_at,
                "created_at": status_response.created_at,
                "updated_at": status_response.updated_at
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при остановке синхронизации: {str(e)}"
        )


@router.patch("/orders/{token_id}/{order_id}/mark_stock_updated")
async def mark_order_stock_updated(
    token_id: str,
    order_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):


    """
    Пометить заказ как списанный (is_stock_updated=True) по token_id и order_id.
    """
    try:
        orders_client = OrdersClient(
            jwt_token=create_access_token(
                user_id=settings.PROJECT_NAME
            ),
            base_url=settings.MICRO_SERVICE_URL
        )

        update_response = orders_client.update_stock_status(
            token_id=token_id,
            order_id=order_id,
            is_stock_updated=True
        )
        
        # Возвращаем данные из OrderStatusUpdate
        return {
            "success": update_response.success,
            "order_id": update_response.order_id,
            "is_stock_updated": update_response.is_stock_updated,
            "updated_at": update_response.updated_at,
            "message": update_response.message
        }
    except Exception as e:
        logger.error(f"Ошибка при пометке заказа как списанного: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/start-check-stock")
def start_check_stock_task(interval_seconds: int) -> Dict[str, Any]:
    """
    Запускает периодическую задачу проверки и обновления стоков.
    
    Args:
        interval_seconds: Интервал запуска в секундах
    """
    try:
        client = get_redis_client()
        schedule_raw = client.get("celery_beat_schedule")
        if schedule_raw:
            schedule = json.loads(schedule_raw.decode("utf-8"))
        else:
            schedule = {}

        check_stock_entry = {
            "task": "app.celery_app.check_and_update_stock",
            "schedule": interval_seconds,
            "args": []
        }
        schedule["check-and-update-stock"] = check_stock_entry
        client.set("celery_beat_schedule", json.dumps(schedule))
        return {"status": "success", "message": f"Периодическая задача проверки стоков запущена с интервалом {interval_seconds} сек."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при запуске задачи: {str(e)}")

@router.post("/stop-check-stock")
def stop_check_stock_task() -> Dict[str, Any]:
    """
    Останавливает периодическую задачу проверки и обновления стоков.
    """
    try:
        client = get_redis_client()
        schedule_raw = client.get("celery_beat_schedule")
        if schedule_raw:
            schedule = json.loads(schedule_raw.decode("utf-8"))
        else:
            schedule = {}
        if "check-and-update-stock" in schedule:
            del schedule["check-and-update-stock"]
            client.set("celery_beat_schedule", json.dumps(schedule))
        return {"status": "success", "message": "Периодическая задача проверки стоков остановлена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при остановке задачи: {str(e)}")


@router.post("/wix-sync")
def run_wix_sync() -> Dict[str, Any]:
    """
    Запускает единоразовую синхронизацию количества товаров с Wix.
    
    Returns:
        Dict[str, Any]: Результат запуска задачи
    """
    try:
        result = launch_wix_sync()
        
        return {
            "status": "success",
            "message": "Синхронизация Wix запущена",
            "task_id": result.id,
            "task_status": "PENDING"
        }
    except Exception as e:
        logger.error(f"Ошибка при запуске синхронизации Wix: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации Wix: {str(e)}"
        )


@router.get("/wix-test-connection")
def test_wix_connection() -> Dict[str, Any]:
    """
    Тестирует подключение к Wix API и валидность креденшиалов.
    
    Returns:
        Dict[str, Any]: Результат тестирования подключения
    """
    try:
        from app.services.wix_api_service.base import WixApiService
        
        wix_service = WixApiService()
        result = wix_service.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"Ошибка при тестировании подключения к Wix: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при тестировании подключения к Wix: {str(e)}"
        )

