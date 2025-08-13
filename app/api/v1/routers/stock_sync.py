"""
API endpoints для мониторинга и управления системой синхронизации складских остатков.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_current_user_optional, get_async_session
from app.database import get_db
from app.models.user import User
from app.models.stock_synchronization import (
    PendingStockOperation,
    StockSynchronizationLog,
    OperationStatus
)
from app.services.stock_synchronization_service import StockSynchronizationService
from app.services.stock_validation_service import StockValidationService
from app.services.warehouse.manager import get_manager
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings
from app.schemas.stock_synchronization import (
    SyncResult,
    ProcessingResult,
    ReconciliationResult,
    StockValidationResult
)

logger = logging.getLogger(__name__)

router = APIRouter()
web_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Регистрируем фильтры локализации
from app.utils.localization import localize_action, localize_status, localize_log_message, format_log_details
templates.env.filters["localize_action"] = localize_action
templates.env.filters["localize_status"] = localize_status  
templates.env.filters["localize_log_message"] = localize_log_message

# Регистрируем глобальные функции для шаблонов
templates.env.globals["localize_action"] = localize_action
templates.env.globals["localize_status"] = localize_status
templates.env.globals["localize_log_message"] = localize_log_message
templates.env.globals["format_log_details"] = format_log_details


def get_sync_service(session: Session = Depends(get_db)) -> StockSynchronizationService:
    """Создание сервиса синхронизации с зависимостями."""
    # Создаем JWT токен для работы с микросервисом
    jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
    
    # Инициализируем клиенты
    orders_client = OrdersClient(
        jwt_token=jwt_token,
        base_url=settings.MICRO_SERVICE_URL
    )
    tokens_client = AllegroTokenMicroserviceClient(
        jwt_token=jwt_token,
        base_url=settings.MICRO_SERVICE_URL
    )
    inventory_manager = get_manager()
    
    return StockSynchronizationService(
        session=session,
        orders_client=orders_client,
        tokens_client=tokens_client,
        inventory_manager=inventory_manager
    )


def get_validation_service(session: Session = Depends(get_db)) -> StockValidationService:
    """Создание сервиса валидации с зависимостями."""
    inventory_manager = get_manager()
    return StockValidationService(
        session=session,
        inventory_manager=inventory_manager
    )


@router.get("/health", summary="Состояние системы синхронизации")
async def get_system_health(
    sync_service: StockSynchronizationService = Depends(get_sync_service),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Получить общее состояние системы синхронизации складских остатков.
    
    Returns:
        Dict: Детальная информация о состоянии системы
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    try:
        health_stats = sync_service.get_sync_statistics()
        return {
            "status": "success",
            "health_data": health_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Ошибка получения статуса системы: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения статуса системы: {str(e)}"
        )


@router.get("/operations", summary="Список всех операций с фильтрацией")
async def get_all_operations(
    limit: int = Query(50, ge=1, le=500, description="Количество операций для получения"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    order_id: Optional[str] = Query(None, description="Фильтр по ID заказа"),
    account_name: Optional[str] = Query(None, description="Фильтр по имени аккаунта"),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Получить список всех операций с возможностью фильтрации.
    
    Args:
        limit: Максимальное количество операций
        offset: Смещение для пагинации
        order_id: Фильтр по ID заказа
        account_name: Фильтр по имени аккаунта
        status: Фильтр по статусу
        
    Returns:
        Dict: Список операций с метаинформацией
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    try:
        # Базовый запрос - получаем все операции
        statement = select(PendingStockOperation)
        
        # Применяем фильтры
        if order_id:
            statement = statement.where(PendingStockOperation.order_id == order_id)
        
        if status:
            statement = statement.where(PendingStockOperation.status == status)
        
        # Фильтр по аккаунту
        if account_name:
            statement = statement.where(PendingStockOperation.account_name.contains(account_name))
        
        # Сортируем по времени создания (новые сначала)
        statement = statement.order_by(PendingStockOperation.created_at.desc())
        
        # Подсчет общего количества
        total_statement = statement
        total_count = len(session.exec(total_statement).all())
        
        # Применяем лимит и смещение
        statement = statement.offset(offset).limit(limit)
        operations = session.exec(statement).all()
        
        # Конвертируем в словари для JSON ответа
        operations_data = []
        for op in operations:
            # Извлекаем информацию о позициях из line_items
            line_items_info = {
                "count": 0,
                "items": []
            }
            
            if op.line_items:
                line_items_info["count"] = len(op.line_items)
                line_items_info["items"] = op.line_items
            else:
                line_items_info["count"] = 0
                line_items_info["items"] = []
            
            operations_data.append({
                "id": str(op.id),
                "order_id": op.order_id,
                "operation_type": op.operation_type,
                "warehouse": op.warehouse,
                "token_id": op.token_id,
                "account_name": op.account_name,
                "status": op.status,
                "retry_count": op.retry_count,
                "error_message": op.error_message,
                "created_at": op.created_at.isoformat(),
                "updated_at": op.updated_at.isoformat() if op.updated_at else None,
                "line_items_count": line_items_info["count"],
                "line_items": line_items_info["items"]
            })
        
        return {
            "status": "success",
            "operations": operations_data,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения операций: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения операций: {str(e)}"
        )


@router.get("/operations/pending", summary="Список ожидающих операций")
async def get_pending_operations(
    limit: int = Query(50, ge=1, le=500, description="Количество операций для получения"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    token_id: Optional[str] = Query(None, description="Фильтр по ID токена"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Получить список операций, ожидающих синхронизации.
    
    Args:
        limit: Максимальное количество операций
        offset: Смещение для пагинации
        token_id: Фильтр по конкретному токену
        
    Returns:
        Dict: Список операций с метаинформацией
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    try:
        # Базовый запрос
        statement = select(PendingStockOperation).where(
            PendingStockOperation.status == OperationStatus.PENDING
        )
        
        # Фильтр по токену
        if token_id:
            statement = statement.where(PendingStockOperation.token_id == token_id)
        
        # Подсчет общего количества
        total_statement = statement
        total_count = len(session.exec(total_statement).all())
        
        # Применяем лимит и смещение
        statement = statement.offset(offset).limit(limit)
        operations = session.exec(statement).all()
        
        # Конвертируем в словари для JSON ответа
        operations_data = []
        for op in operations:
            # Извлекаем информацию о позициях из line_items
            line_items_info = {
                "count": 0,
                "items": []
            }
            
            if op.line_items:
                line_items_info["count"] = len(op.line_items)
                line_items_info["items"] = op.line_items
            else:
                line_items_info["count"] = 0
                line_items_info["items"] = []
            
            operations_data.append({
                "id": str(op.id),
                "order_id": op.order_id,
                "operation_type": op.operation_type,
                "warehouse": op.warehouse,
                "token_id": op.token_id,
                "status": op.status,
                "retry_count": op.retry_count,
                "max_retries": op.max_retries,
                "next_retry_at": op.next_retry_at.isoformat() if op.next_retry_at else None,
                "error_message": op.error_message,
                "created_at": op.created_at.isoformat(),
                "updated_at": op.updated_at.isoformat() if op.updated_at else None,
                "line_items_count": line_items_info["count"],
                "line_items": line_items_info["items"]
            })
        
        return {
            "status": "success",
            "operations": operations_data,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения pending операций: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения операций: {str(e)}"
        )


@router.get("/operations/logs", summary="Логи синхронизации")
async def get_sync_logs(
    limit: int = Query(100, ge=1, le=1000, description="Количество записей"),
    offset: int = Query(0, ge=0, description="Смещение"),
    operation_id: Optional[UUID] = Query(None, description="ID конкретной операции"),
    action: Optional[str] = Query(None, description="Фильтр по типу действия"),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Получить логи синхронизации с возможностью фильтрации.
    
    Returns:
        Dict: Список логов с фильтрами и пагинацией
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        # Базовый запрос
        statement = select(StockSynchronizationLog).order_by(
            StockSynchronizationLog.timestamp.desc()
        )
        
        # Применяем фильтры
        if operation_id:
            statement = statement.where(StockSynchronizationLog.operation_id == operation_id)
        if action:
            statement = statement.where(StockSynchronizationLog.action == action)
        if status:
            statement = statement.where(StockSynchronizationLog.status == status)
        
        # Подсчет общего количества
        total_count = len(session.exec(statement).all())
        
        # Применяем лимит и смещение
        statement = statement.offset(offset).limit(limit)
        logs = session.exec(statement).all()
        
        # Конвертируем в словари
        logs_data = []
        for log in logs:
            logs_data.append({
                "id": log.id,
                "operation_id": str(log.operation_id),
                "action": log.action,
                "status": log.status,
                "details": log.details,
                "execution_time_ms": log.execution_time_ms,
                "timestamp": log.timestamp.isoformat()
            })
        
        return {
            "status": "success",
            "logs": logs_data,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения логов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения логов: {str(e)}"
        )


@router.post("/operations/process", summary="Запуск обработки очереди")
async def process_pending_operations(
    limit: int = Query(50, ge=1, le=200, description="Максимальное количество операций для обработки"),
    sync_service: StockSynchronizationService = Depends(get_sync_service),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Ручной запуск обработки операций из очереди.
    
    Returns:
        ProcessingResult: Результат обработки операций
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        result = sync_service.process_pending_operations(limit=limit)
        
        return {
            "status": "success",
            "result": {
                "processed": result.processed,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "max_retries_reached": result.max_retries_reached,
                "details": result.details
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка обработки операций: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки операций: {str(e)}"
        )


@router.post("/reconciliation", summary="Запуск сверки состояний")
async def run_reconciliation(
    token_id: Optional[UUID] = Query(None, description="ID токена для сверки (все токены если не указан)"),
    limit: int = Query(100, ge=1, le=500, description="Максимальное количество заказов для проверки"),
    sync_service: StockSynchronizationService = Depends(get_sync_service),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Ручной запуск сверки состояний между локальной системой и микросервисом.
    
    Returns:
        ReconciliationResult: Результат сверки
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        result = sync_service.reconcile_stock_status(
            token_id=token_id,
            limit=limit
        )
        
        return {
            "status": "success",
            "result": {
                "total_checked": result.total_checked,
                "discrepancies_found": result.discrepancies_found,
                "auto_fixed": result.auto_fixed,
                "requires_manual_review": result.requires_manual_review,
                "discrepancies": result.discrepancies
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка сверки состояний: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка сверки состояний: {str(e)}"
        )


@router.post("/operations/{operation_id}/rollback", summary="Откат операции")
async def rollback_operation(
    operation_id: UUID,
    sync_service: StockSynchronizationService = Depends(get_sync_service),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Откат конкретной операции синхронизации.
    
    Args:
        operation_id: ID операции для отката
        
    Returns:
        SyncResult: Результат отката
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        result = sync_service.rollback_operation(operation_id)
        
        return {
            "status": "success" if result.success else "error",
            "result": {
                "operation_id": str(result.operation_id) if result.operation_id else None,
                "success": result.success,
                "error": result.error,
                "details": result.details
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка отката операции {operation_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка отката операции: {str(e)}"
        )


@router.post("/validate/stock", summary="Валидация складских остатков")
async def validate_stock_availability(
    sku: str = Query(..., description="SKU товара"),
    warehouse: str = Query("Ирина", description="Склад для проверки"),
    quantity: int = Query(..., ge=1, description="Требуемое количество"),
    validation_service: StockValidationService = Depends(get_validation_service),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Валидация доступности товара на складе.
    
    Returns:
        StockValidationResult: Результат валидации
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        result = validation_service.validate_stock_deduction(
            sku=sku,
            warehouse=warehouse,
            required_quantity=quantity
        )
        
        return {
            "status": "success",
            "validation": {
                "valid": result.valid,
                "sku": result.sku,
                "warehouse": result.warehouse,
                "available_quantity": result.available_quantity,
                "required_quantity": result.required_quantity,
                "shortage_quantity": result.shortage_quantity,
                "shortage_percentage": result.shortage_percentage,
                "error_message": result.error_message
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка валидации товара {sku}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка валидации товара: {str(e)}"
        )


@router.get("/statistics", summary="Детальная статистика")
async def get_detailed_statistics(
    days: int = Query(7, ge=1, le=90, description="Количество дней для статистики"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Получить детальную статистику работы системы за указанный период.
    
    Returns:
        Dict: Подробная статистика операций
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Статистика операций
        total_operations = session.exec(
            select(PendingStockOperation).where(
                PendingStockOperation.created_at >= cutoff_date
            )
        ).all()
        
        completed_ops = [op for op in total_operations if op.status == OperationStatus.COMPLETED]
        pending_ops = [op for op in total_operations if op.status == OperationStatus.PENDING]
        failed_ops = [op for op in total_operations if op.status == OperationStatus.FAILED]
        
        # Статистика по складам
        warehouse_stats = {}
        for op in total_operations:
            if op.warehouse not in warehouse_stats:
                warehouse_stats[op.warehouse] = {"total": 0, "completed": 0, "failed": 0}
            warehouse_stats[op.warehouse]["total"] += 1
            if op.status == OperationStatus.COMPLETED:
                warehouse_stats[op.warehouse]["completed"] += 1
            elif op.status == OperationStatus.FAILED:
                warehouse_stats[op.warehouse]["failed"] += 1
        
        # Статистика логов по дням
        logs_by_day = {}
        logs = session.exec(
            select(StockSynchronizationLog).where(
                StockSynchronizationLog.timestamp >= cutoff_date
            )
        ).all()
        
        for log in logs:
            day_key = log.timestamp.date().isoformat()
            if day_key not in logs_by_day:
                logs_by_day[day_key] = 0
            logs_by_day[day_key] += 1
        
        return {
            "status": "success",
            "period_days": days,
            "statistics": {
                "operations": {
                    "total": len(total_operations),
                    "completed": len(completed_ops),
                    "pending": len(pending_ops),
                    "failed": len(failed_ops),
                    "success_rate": (len(completed_ops) / len(total_operations) * 100) if total_operations else 0
                },
                "warehouses": warehouse_stats,
                "daily_activity": logs_by_day,
                "average_operations_per_day": len(total_operations) / days if days > 0 else 0
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения статистики: {str(e)}"
        )


@router.post("/sync/manual", summary="Ручная синхронизация операции")
async def manual_sync_operation(
    token_id: str = Query(..., description="ID токена Allegro"),
    order_id: str = Query(..., description="ID заказа"),
    sku: str = Query(..., description="SKU товара"),
    quantity: int = Query(..., ge=1, description="Количество для списания"),
    warehouse: str = Query("Ирина", description="Склад"),
    sync_service: StockSynchronizationService = Depends(get_sync_service),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Ручное создание и синхронизация операции списания.
    
    Returns:
        SyncResult: Результат синхронизации
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        result = sync_service.sync_stock_deduction(
            token_id=token_id,
            order_id=order_id,
            sku=sku,
            quantity=quantity,
            warehouse=warehouse
        )
        
        return {
            "status": "success" if result.success else "error",
            "result": {
                "operation_id": str(result.operation_id) if result.operation_id else None,
                "success": result.success,
                "error": result.error,
                "details": result.details
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка ручной синхронизации: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка ручной синхронизации: {str(e)}"
        )


@router.get("/operations/{operation_id}/details", summary="Детальная информация об операции")
async def get_operation_details(
    operation_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    Получить детальную информацию об операции включая все попытки и ошибки.
    
    Args:
        operation_id: ID операции
        
    Returns:
        Dict: Детальная информация об операции со всеми попытками
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    try:
        # Получаем операцию
        operation = session.get(PendingStockOperation, operation_id)
        if not operation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Операция не найдена"
            )
        
        # Получаем все логи для этой операции
        logs_statement = select(StockSynchronizationLog).where(
            StockSynchronizationLog.operation_id == operation_id
        ).order_by(StockSynchronizationLog.timestamp.asc())
        
        logs = session.exec(logs_statement).all()
        
        # Форматируем данные операции
        operation_data = {
            "id": str(operation.id),
            "order_id": operation.order_id,
            "operation_type": operation.operation_type,
            "status": operation.status,
            "warehouse": operation.warehouse,
            "token_id": operation.token_id,
            "account_name": operation.account_name,
            "retry_count": operation.retry_count,
            "next_retry_at": operation.next_retry_at.isoformat() if operation.next_retry_at else None,
            "error_message": operation.error_message,
            "created_at": operation.created_at.isoformat(),
            "updated_at": operation.updated_at.isoformat() if operation.updated_at else None,
            "completed_at": operation.completed_at.isoformat() if operation.completed_at else None,
            "line_items": operation.line_items,
            "allegro_order_id": operation.allegro_order_id
        }
        
        # Форматируем логи
        logs_data = []
        validation_details = None
        
        for log in logs:
            try:
                log_data = {
                    "id": log.id,
                    "action": log.action,
                    "status": log.status,
                    "details": log.details,
                    "execution_time_ms": log.execution_time_ms,
                    "timestamp": log.timestamp.isoformat()
                }
                logs_data.append(log_data)
                
                # Извлекаем детали валидации если есть
                if log.action == "stock_validation_failed" and "items_details" in log.details:
                    validation_details = {
                        "total_items": log.details.get("total_items", 0),
                        "valid_items": log.details.get("valid_items", 0),
                        "invalid_items": log.details.get("invalid_items", 0),
                        "validation_errors": log.details.get("validation_errors", []),
                        "items_details": log.details.get("items_details", [])
                    }
            except Exception as log_error:
                logger.error(f"Ошибка обработки лога {log.id}: {log_error}")
                # Пропускаем проблемный лог
                continue
        
        return {
            "status": "success",
            "operation": operation_data,
            "logs": logs_data,
            "validation_details": validation_details,
            "logs_count": len(logs_data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения деталей операции {operation_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения деталей операции: {str(e)}"
        )


@router.get("/operations/pending", summary="Список провальных операций")
async def get_failed_operations(
    limit: int = Query(50, ge=1, le=500, description="Количество операций"),
    offset: int = Query(0, ge=0, description="Смещение"),
    token_id: Optional[str] = Query(None, description="Фильтр по токену"),
    days: int = Query(7, ge=1, le=90, description="За сколько дней"),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):

    """
    Получить список провальных операций с краткой информацией об ошибках.
    """

    if not current_user:
        return RedirectResponse(url=f"/login?next=/operations/pending", status_code=302)

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Базовый запрос для провальных операций
        statement = select(PendingStockOperation).where(
            PendingStockOperation.status == OperationStatus.PENDING,
            PendingStockOperation.created_at >= cutoff_date
        ).order_by(PendingStockOperation.updated_at.desc())
        
        # Фильтр по токену
        if token_id:
            statement = statement.where(PendingStockOperation.token_id == token_id)
        
        # Подсчет общего количества
        total_count = len(session.exec(statement).all())
        
        # Применяем лимит и смещение
        statement = statement.offset(offset).limit(limit)
        operations = session.exec(statement).all()
        
        # Получаем детали для каждой операции
        operations_data = []
        for op in operations:
            # Получаем последний лог с ошибкой валидации
            last_validation_log = session.exec(
                select(StockSynchronizationLog).where(
                    StockSynchronizationLog.operation_id == op.id,
                    StockSynchronizationLog.action == "stock_validation_failed"
                ).order_by(StockSynchronizationLog.timestamp.desc()).limit(1)
            ).first()
            
            validation_summary = None
            if last_validation_log and "items_details" in last_validation_log.details:
                items_details = last_validation_log.details["items_details"]
                validation_summary = {
                    "total_items": len(items_details),
                    "invalid_items": len([item for item in items_details if not item.get("valid", True)]),
                    "main_issues": []
                }
                
                # Собираем основные проблемы
                for item in items_details:
                    if not item.get("valid", True):
                        validation_summary["main_issues"].append({
                            "sku": item.get("sku"),
                            "shortage": item.get("shortage_quantity", 0),
                            "available": item.get("available_quantity", 0),
                            "required": item.get("required_quantity", 0)
                        })
            
            operation_data = {
                "id": str(op.id),
                "order_id": op.order_id,
                "token_id": op.token_id,
                "warehouse": op.warehouse,
                "retry_count": op.retry_count,
                "error_message": op.error_message,
                "created_at": op.created_at.isoformat(),
                "updated_at": op.updated_at.isoformat() if op.updated_at else None,
                "line_items_count": len(op.line_items) if op.line_items else 0,
                "validation_summary": validation_summary
            }
            operations_data.append(operation_data)
        
        return {
            "status": "success",
            "failed_operations": operations_data,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            },
            "period_days": days
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения провальных операций: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения провальных операций: {str(e)}"
        )


@web_router.get("/stock-sync/monitor", response_class=HTMLResponse, summary="Страница мониторинга операций")
async def monitoring_page(
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """
    HTML страница для мониторинга провальных операций синхронизации.
    Не требует аутентификации для доступа из Telegram уведомлений.
    """

    if not current_user:
        return RedirectResponse(url=f"/login?next=/stock-sync/monitor", status_code=302)

    try:
        # Получаем базовую статистику для отображения
        now = datetime.utcnow()
        last_24h = now - timedelta(hours=24)
        
        # Статистика за 24 часа
        total_ops = len(session.exec(
            select(PendingStockOperation).where(
                PendingStockOperation.created_at >= last_24h
            )
        ).all())
        
        failed_ops = session.exec(
            select(PendingStockOperation).where(
                PendingStockOperation.status == OperationStatus.FAILED,
                PendingStockOperation.created_at >= last_24h
            )
        ).all()
        
        pending_ops = len(session.exec(
            select(PendingStockOperation).where(
                PendingStockOperation.status == OperationStatus.PENDING
            )
        ).all())
        
        return templates.TemplateResponse("stock_monitoring.html", {
            "request": request,
            "user": current_user,
            "current_user": current_user,
            "total_operations_24h": total_ops,
            "failed_operations_24h": len(failed_ops),
            "pending_operations": pending_ops,
            "timestamp": now.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Ошибка загрузки страницы мониторинга: {e}")
        # Возвращаем простую HTML страницу с ошибкой
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Мониторинг операций - Ошибка</title>
            <meta charset="utf-8">
        </head>
        <body>
            <h1>Ошибка загрузки страницы мониторинга</h1>
            <p>Произошла ошибка при загрузке данных: {str(e)}</p>
            <p>Время: {datetime.utcnow().isoformat()}</p>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=500)


@web_router.get("/stock-sync/monitor/operation/{operation_id}", response_class=HTMLResponse, summary="Страница деталей операции")
async def operation_details_page(
    operation_id: UUID,
    request: Request,
    session: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user_optional)
):

    """
    HTML страница с детальной информацией об операции.
    Используется для ссылок из Telegram уведомлений.
    """

    if not current_user:
        return RedirectResponse(url=f"/login?next=/stock-sync/monitor/operation/{operation_id}", status_code=302)

    try:
        # Получаем детали операции (аналогично API endpoint)
        operation = session.get(PendingStockOperation, operation_id)
        if not operation:
            return HTMLResponse(
                content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Операция не найдена</title>
                    <meta charset="utf-8">
                </head>
                <body>
                    <h1>Операция не найдена</h1>
                    <p>Операция с ID {operation_id} не существует.</p>
                </body>
                </html>
                """,
                status_code=404
            )
        
        # Получаем логи операции
        logs = session.exec(
            select(StockSynchronizationLog).where(
                StockSynchronizationLog.operation_id == operation_id
            ).order_by(StockSynchronizationLog.timestamp.desc())
        ).all()
        
        # Получаем детали валидации
        validation_details = None
        for log in logs:
            try:
                if log.action == "stock_validation_failed" and "items_details" in log.details:
                    validation_details = log.details
                    break
            except Exception as log_error:
                logger.error(f"Ошибка обработки лога валидации {log.id}: {log_error}")
                continue
        
        return templates.TemplateResponse("operation_details.html", {
            "request": request,
            "user": current_user,
            "current_user": current_user,
            "operation": operation,
            "logs": logs,
            "validation_details": validation_details,
            "logs_count": len(logs)
        })
        
    except Exception as e:
        logger.error(f"Ошибка загрузки деталей операции {operation_id}: {e}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Ошибка загрузки операции</title>
                <meta charset="utf-8">
            </head>
            <body>
                <h1>Ошибка загрузки деталей операции</h1>
                <p>Произошла ошибка: {str(e)}</p>
                <p>ID операции: {operation_id}</p>
            </body>
            </html>
            """,
            status_code=500
        )