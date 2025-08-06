"""
API endpoints для мониторинга и управления системой синхронизации складских остатков.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_session
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


def get_sync_service(session: Session = Depends(get_session)) -> StockSynchronizationService:
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


def get_validation_service(session: Session = Depends(get_session)) -> StockValidationService:
    """Создание сервиса валидации с зависимостями."""
    inventory_manager = get_manager()
    return StockValidationService(
        session=session,
        inventory_manager=inventory_manager
    )


@router.get("/health", summary="Состояние системы синхронизации")
async def get_system_health(
    sync_service: StockSynchronizationService = Depends(get_sync_service),
    current_user: User = Depends(get_current_user)
):
    """
    Получить общее состояние системы синхронизации складских остатков.
    
    Returns:
        Dict: Детальная информация о состоянии системы
    """
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


@router.get("/operations/pending", summary="Список ожидающих операций")
async def get_pending_operations(
    limit: int = Query(50, ge=1, le=500, description="Количество операций для получения"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    token_id: Optional[str] = Query(None, description="Фильтр по ID токена"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
            operations_data.append({
                "id": str(op.id),
                "order_id": op.order_id,
                "operation_type": op.operation_type,
                "sku": op.sku,
                "quantity": op.quantity,
                "warehouse": op.warehouse,
                "token_id": op.token_id,
                "status": op.status,
                "retry_count": op.retry_count,
                "max_retries": op.max_retries,
                "next_retry_at": op.next_retry_at.isoformat() if op.next_retry_at else None,
                "error_message": op.error_message,
                "created_at": op.created_at.isoformat(),
                "updated_at": op.updated_at.isoformat() if op.updated_at else None
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Получить логи синхронизации с возможностью фильтрации.
    
    Returns:
        Dict: Список логов с фильтрами и пагинацией
    """
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
    current_user: User = Depends(get_current_user)
):
    """
    Ручной запуск обработки операций из очереди.
    
    Returns:
        ProcessingResult: Результат обработки операций
    """
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
    current_user: User = Depends(get_current_user)
):
    """
    Ручной запуск сверки состояний между локальной системой и микросервисом.
    
    Returns:
        ReconciliationResult: Результат сверки
    """
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
    current_user: User = Depends(get_current_user)
):
    """
    Откат конкретной операции синхронизации.
    
    Args:
        operation_id: ID операции для отката
        
    Returns:
        SyncResult: Результат отката
    """
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
    current_user: User = Depends(get_current_user)
):
    """
    Валидация доступности товара на складе.
    
    Returns:
        StockValidationResult: Результат валидации
    """
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Получить детальную статистику работы системы за указанный период.
    
    Returns:
        Dict: Подробная статистика операций
    """
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
    current_user: User = Depends(get_current_user)
):
    """
    Ручное создание и синхронизация операции списания.
    
    Returns:
        SyncResult: Результат синхронизации
    """
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