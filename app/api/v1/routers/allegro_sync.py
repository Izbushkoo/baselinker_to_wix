from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Header
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Session, select, func
from datetime import timedelta, datetime
import os
import logging

from app.api.deps import get_db, get_session
from app.models.allegro_token import AllegroToken
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
        # Добавляем задачи в Celery Beat
        celery.conf.beat_schedule.update({
            f'sync-allegro-orders-{token_id}': {
                'task': 'tasks.sync_allegro_orders',
                'schedule': timedelta(hours=12),
                'args': (token_id,)
            },
            f'check-recent-orders-{token_id}': {
                'task': 'tasks.check_recent_orders',
                'schedule': timedelta(hours=1),
                'args': (token_id,)
            }
        })

        # Запускаем первую синхронизацию немедленно
        celery.send_task('tasks.sync_allegro_orders', args=[token_id])
        
        return {
            "status": "success",
            "message": "Задачи синхронизации успешно запущены",
            "tasks": [
                {
                    "name": "sync_allegro_orders",
                    "schedule": "каждые 12 часов"
                },
                {
                    "name": "check_recent_orders",
                    "schedule": "каждый час"
                }
            ]
        }
    except Exception as e:
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
        # Удаляем задачи из Celery Beat
        if f'sync-allegro-orders-{token_id}' in celery.conf.beat_schedule:
            del celery.conf.beat_schedule[f'sync-allegro-orders-{token_id}']
        
        if f'check-recent-orders-{token_id}' in celery.conf.beat_schedule:
            del celery.conf.beat_schedule[f'check-recent-orders-{token_id}']

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

    # Проверяем наличие задач в расписании
    sync_task = f'sync-allegro-orders-{token_id}' in celery.conf.beat_schedule
    check_task = f'check-recent-orders-{token_id}' in celery.conf.beat_schedule

    return {
        "status": "active" if sync_task or check_task else "inactive",
        "tasks": {
            "sync_allegro_orders": {
                "active": sync_task,
                "schedule": "каждые 12 часов" if sync_task else None
            },
            "check_recent_orders": {
                "active": check_task,
                "schedule": "каждый час" if check_task else None
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
        task = celery.send_task('tasks.sync_allegro_orders', args=[token_id, parsed_date])
        
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
    
    # Получаем все токены
    tokens = get_tokens_list_sync(db)
    
    for token in tokens:
        token_tasks = {}
        sync_task_name = f'sync-allegro-orders-{token.id_}'
        check_task_name = f'check-recent-orders-{token.id_}'
        
        if sync_task_name in celery.conf.beat_schedule:
            token_tasks['sync_allegro_orders'] = {
                'schedule': 'каждые 12 часов',
                'last_run': None
            }
            
        if check_task_name in celery.conf.beat_schedule:
            token_tasks['check_recent_orders'] = {
                'schedule': 'каждый час',
                'last_run': None
            }
            
        if token_tasks:
            active_tasks[token.id_] = {
                'account_name': token.account_name,
                'tasks': token_tasks
            }
    
    return {
        "active_tasks_count": len(active_tasks),
        "tasks": active_tasks
    }

@router.get("/tasks/{token_id}/active")
def list_token_active_tasks(token_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Получает список активных задач для конкретного токена.
    """
    # Проверяем существование токена
    token = get_token_by_id_sync(db, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Токен не найден")

    active_tasks = []
    
    # Проверяем каждую возможную задачу для токена
    task_configs = {
        f'sync-allegro-orders-{token_id}': {
            'name': 'sync_allegro_orders',
            'description': 'Полная синхронизация заказов',
            'schedule': 'каждые 12 часов'
        },
        f'check-recent-orders-{token_id}': {
            'name': 'check_recent_orders',
            'description': 'Проверка новых заказов',
            'schedule': 'каждый час'
        }
    }
    
    for task_name, config in task_configs.items():
        if task_name in celery.conf.beat_schedule:
            task_info = celery.conf.beat_schedule[task_name]
            active_tasks.append({
                'name': config['name'],
                'description': config['description'],
                'schedule': config['schedule'],
                'task': task_info['task'],
                'args': task_info['args']
            })

    return {
        "token_id": token_id,
        "account_name": token.account_name,
        "active_tasks_count": len(active_tasks),
        "tasks": active_tasks
    }

@router.delete("/orders/all")
async def delete_all_orders(
    db: Session = Depends(get_db),
    _: str = Depends(verify_admin_password)
) -> Dict[str, Any]:
    """
    Удаляет все заказы и связанные данные из базы данных.
    Требует пароль администратора в заголовке X-Admin-Password.
    """
    try:
        # Удаляем в правильном порядке с учетом зависимостей
        # 1. Сначала удаляем связи в таблице order_line_items
        results = db.exec(select(OrderLineItem).where(True)).all()
        for result in results:
            db.delete(result)
        
        # 2. Затем удаляем заказы
        results = db.exec(select(AllegroOrder).where(True)).all()
        for result in results:
            db.delete(result)
        
        # 3. Удаляем товарные позиции
        results = db.exec(select(AllegroLineItem).where(True)).all()
        for result in results:
            db.delete(result)
        
        # 4. В последнюю очередь удаляем покупателей
        results = db.exec(select(AllegroBuyer).where(True)).all()
        for result in results:
            db.delete(result)
        
        db.commit()
        
        return {
            "status": "success",
            "message": "Все заказы и связанные данные успешно удалены"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при удалении данных: {str(e)}"
        )

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
        task = celery.send_task('tasks.sync_allegro_orders_immediate', args=[token_id, parsed_date])
        
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

@router.get("/orders")
def get_all_orders(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000, description="Количество заказов на странице"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    status: Optional[str] = Query(None, description="Фильтр по статусу заказа"),
    from_date: Optional[str] = Query(None, description="Фильтр по дате (DD-MM-YYYY)"),
    to_date: Optional[str] = Query(None, description="Фильтр по дате (DD-MM-YYYY)")
) -> Dict[str, Any]:
    """
    Получает список всех заказов со всеми связанными данными.
    """
    try:
        # Формируем базовый запрос
        query = select(AllegroOrder)
        
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
        total_count = db.exec(select(func.count()).select_from(query.subquery())).first()
        
        # Применяем пагинацию
        query = query.offset(offset).limit(limit)
        
        # Получаем заказы
        orders = db.exec(query).all()
        
        # Формируем ответ
        orders_data = []
        for order in orders:
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
                "line_items": []
            }
            
            # Добавляем данные покупателя
            if order.buyer:
                order_dict["buyer"] = {
                    "id": order.buyer.id,
                    "email": order.buyer.email,
                    "login": order.buyer.login,
                    "first_name": order.buyer.first_name,
                    "last_name": order.buyer.last_name,
                    "company_name": order.buyer.company_name,
                    "phone_number": order.buyer.phone_number,
                    "address": order.buyer.address
                }
            
            # Добавляем позиции заказа
            if order.order_items:
                order_dict["line_items"] = [
                    {
                        "id": item.line_item.id,
                        "offer_id": item.line_item.offer_id,
                        "offer_name": item.line_item.offer_name,
                        "external_id": item.line_item.external_id,
                        "original_price": item.line_item.original_price,
                        "price": item.line_item.price
                    }
                    for item in order.order_items
                ]
            
            orders_data.append(order_dict)
        
        return {
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "orders": orders_data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении списка заказов: {str(e)}"
        )

@router.get("/orders/{token_id}")
async def get_all_orders(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """
    Получает все заказы для указанного токена.
    
    Args:
        token_id: ID токена Allegro
        database: Сессия базы данных
    """
    try:
        # Проверяем токен
        token = await get_token_by_id(database, token_id)
        if not token:
            raise HTTPException(status_code=404, detail="Токен не найден")
            
        token = await check_token(database, token)
        if not token:
            raise HTTPException(status_code=401, detail="Токен недействителен")
        
        # Создаем сервис API
        api_service = AsyncAllegroApiService()
        
        # Получаем заказы через API
        orders = await api_service.get_orders(token.access_token)
        
        # Сохраняем заказы в базу данных
        repository = AllegroOrderRepository(database)
        saved_orders = []
        
        for order_data in orders:
            try:
                # Проверяем, существует ли уже заказ
                existing_order = await repository.get_order_by_id(order_data["id"])
                
                if existing_order:
                    # Если заказ существует, обновляем его
                    order = await repository.update_order(token_id, order_data["id"], order_data)
                else:
                    # Если заказ не существует, создаем новый
                    order = await repository.add_order(token_id, order_data)
                    
                saved_orders.append(order)
            except Exception as e:
                logging.error(f"Ошибка при сохранении заказа {order_data.get('id')}: {str(e)}")
                continue
        
        return saved_orders
        
    except Exception as e:
        logging.error(f"Ошибка при синхронизации заказов: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/{token_id}/{order_id}")
async def get_order_by_id(
    token_id: str,
    order_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """
    Получает заказ по ID для указанного токена.
    
    Args:
        token_id: ID токена Allegro
        order_id: ID заказа
        database: Сессия базы данных
    """
    try:
        # Проверяем токен
        token = await get_token_by_id(database, token_id)
        if not token:
            raise HTTPException(status_code=404, detail="Токен не найден")
            
        token = await check_token(database, token)
        if not token:
            raise HTTPException(status_code=401, detail="Токен недействителен")
        
        # Создаем сервис API
        api_service = AsyncAllegroApiService()
        
        # Получаем заказ через API
        order_data = await api_service.get_order_by_id(token.access_token, order_id)
        if not order_data:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        
        # Сохраняем заказ в базу данных
        repository = AllegroOrderRepository(database)
        
        # Проверяем, существует ли уже заказ
        existing_order = await repository.get_order_by_id(order_id)
        
        if existing_order:
            # Если заказ существует, обновляем его
            order = await repository.update_order(token_id, order_id, order_data)
        else:
            # Если заказ не существует, создаем новый
            order = await repository.add_order(token_id, order_data)
            
        return order
        
    except Exception as e:
        logging.error(f"Ошибка при получении заказа: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/orders/{token_id}")
async def delete_all_orders(
    token_id: str,
    database: AsyncSession = Depends(deps.get_async_session)
):
    """
    Удаляет все заказы для указанного токена.
    
    Args:
        token_id: ID токена Allegro
        database: Сессия базы данных
    """
    try:
        # Проверяем токен
        token = await get_token_by_id(database, token_id)
        if not token:
            raise HTTPException(status_code=404, detail="Токен не найден")
        
        # Удаляем все заказы для этого токена
        statement = select(AllegroOrder).where(AllegroOrder.token_id == token_id)
        orders = await database.exec(statement)
        
        for order in orders:
            await database.delete(order)
        
        await database.commit()
        return {"message": "Все заказы успешно удалены"}
        
    except Exception as e:
        logging.error(f"Ошибка при удалении заказов: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/orders/filter")
def get_orders_by_min_line_items(
    min_line_items: int,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Получает заказы, у которых количество товарных позиций больше или равно указанному.
    """
    try:
        # Формируем запрос с фильтром по количеству товарных позиций
        query = (
            select(AllegroOrder)
            .join(OrderLineItem)
            .group_by(AllegroOrder.id)
            .having(func.count(OrderLineItem.id) >= min_line_items)
        )
        
        # Получаем заказы
        orders = db.exec(query).all()
        
        if not orders:
            raise HTTPException(status_code=404, detail="Заказы не найдены")
        
        # Формируем ответ
        orders_list = []
        for order in orders:
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
                "line_items": []
            }
            
            # Добавляем данные покупателя
            if order.buyer:
                order_dict["buyer"] = {
                    "id": order.buyer.id,
                    "email": order.buyer.email,
                    "login": order.buyer.login,
                    "first_name": order.buyer.first_name,
                    "last_name": order.buyer.last_name,
                    "company_name": order.buyer.company_name,
                    "phone_number": order.buyer.phone_number,
                    "address": order.buyer.address
                }
            
            # Добавляем позиции заказа
            if order.order_items:
                order_dict["line_items"] = [
                    {
                        "id": item.line_item.id,
                        "offer_id": item.line_item.offer_id,
                        "offer_name": item.line_item.offer_name,
                        "external_id": item.line_item.external_id,
                        "original_price": item.line_item.original_price,
                        "price": item.line_item.price
                    }
                    for item in order.order_items
                ]
            
            orders_list.append(order_dict)
        
        return orders_list
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении заказов: {str(e)}"
        ) 