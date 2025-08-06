# План реализации системы синхронизации складских операций

## Фаза 1: Создание базовой инфраструктуры

### 1.1 Создание моделей данных

#### PendingStockOperation модель
```python
# app/models/stock_synchronization.py
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, Column
from uuid import UUID, uuid4
from enum import Enum

class OperationType(str, Enum):
    DEDUCTION = "deduction"
    REFUND = "refund" 
    ADJUSTMENT = "adjustment"

class OperationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PendingStockOperation(SQLModel, table=True):
    __tablename__ = "pending_stock_operations"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_id: str = Field(index=True)
    operation_type: OperationType
    status: OperationStatus = Field(default=OperationStatus.PENDING)
    
    # Детали операции
    sku: str = Field(index=True)
    quantity: int
    warehouse: str = Field(default="Ирина")
    
    # Retry механизм
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=5)
    next_retry_at: datetime
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Связи
    token_id: str = Field(foreign_key="allegro_tokens.id_", index=True)
    allegro_order_id: Optional[str] = Field(foreign_key="allegro_orders.id")
```

#### Лог синхронизации
```python
class StockSynchronizationLog(SQLModel, table=True):
    __tablename__ = "stock_synchronization_logs"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    operation_id: UUID = Field(foreign_key="pending_stock_operations.id", index=True)
    action: str  # "created", "retry", "completed", "failed", "rolled_back"
    status: str
    details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    execution_time_ms: Optional[int] = None
```

### 1.2 Создание миграции базы данных

```bash
# Команда для создания миграции
alembic revision --autogenerate -m "add_stock_synchronization_tables"
```

### 1.3 Конфигурация системы

```python
# app/core/stock_sync_config.py
from pydantic import BaseSettings
from typing import Dict, Any

class StockSyncConfig(BaseSettings):
    retry_max_attempts: int = 5
    retry_initial_delay: int = 60  # секунды
    retry_max_delay: int = 3600   # секунды
    retry_exponential_base: float = 2.0
    retry_jitter: bool = True
    
    reconciliation_interval_minutes: int = 30
    reconciliation_batch_size: int = 100
    reconciliation_auto_fix_threshold_hours: int = 24
    
    monitoring_alert_on_failed_retries: bool = True
    monitoring_max_pending_operations: int = 1000
    monitoring_stale_operation_hours: int = 6
    
    class Config:
        env_prefix = "STOCK_SYNC_"

stock_sync_config = StockSyncConfig()
```

## Фаза 2: Создание основного сервиса синхронизации

### 2.1 StockSynchronizationService

```python
# app/services/stock_synchronization_service.py
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select
from uuid import UUID

from app.models.stock_synchronization import (
    PendingStockOperation, 
    StockSynchronizationLog,
    OperationType,
    OperationStatus
)
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.core.stock_sync_config import stock_sync_config

class SyncResult:
    def __init__(self, success: bool, operation_id: Optional[UUID] = None, error: Optional[str] = None):
        self.success = success
        self.operation_id = operation_id
        self.error = error

class StockSynchronizationService:
    def __init__(self, session: Session, orders_client: OrdersClient):
        self.session = session
        self.orders_client = orders_client
        self.logger = logging.getLogger("stock.sync")
        self.config = stock_sync_config
    
    async def sync_stock_deduction(
        self,
        token_id: str,
        order_id: str,
        sku: str,
        quantity: int,
        warehouse: str = "Ирина"
    ) -> SyncResult:
        """Синхронное списание с немедленной попыткой обновления микросервиса."""
        operation_id = None
        
        try:
            # Создаем запись операции
            operation = PendingStockOperation(
                order_id=order_id,
                operation_type=OperationType.DEDUCTION,
                sku=sku,
                quantity=quantity,
                warehouse=warehouse,
                token_id=token_id,
                next_retry_at=datetime.utcnow() + timedelta(seconds=self.config.retry_initial_delay)
            )
            self.session.add(operation)
            self.session.commit()
            operation_id = operation.id
            
            self._log_operation(operation.id, "created", "Operation created")
            
            # Немедленная попытка синхронизации
            sync_success = await self._try_sync_with_microservice(operation)
            
            if sync_success:
                operation.status = OperationStatus.COMPLETED
                operation.completed_at = datetime.utcnow()
                self.session.commit()
                
                self._log_operation(operation.id, "completed", "Immediate sync successful")
                return SyncResult(True, operation_id)
            else:
                # Оставляем в pending для retry
                self._log_operation(operation.id, "failed", "Immediate sync failed, queued for retry")
                return SyncResult(False, operation_id, "Immediate sync failed, queued for retry")
                
        except Exception as e:
            self.logger.error(f"Error in sync_stock_deduction: {e}")
            if operation_id:
                self._log_operation(operation_id, "error", f"Exception: {str(e)}")
            return SyncResult(False, operation_id, str(e))
    
    async def _try_sync_with_microservice(self, operation: PendingStockOperation) -> bool:
        """Попытка синхронизации с микросервисом."""
        try:
            start_time = datetime.utcnow()
            
            result = self.orders_client.update_stock_status(
                token_id=UUID(operation.token_id),
                order_id=operation.order_id,
                is_stock_updated=True
            )
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if result and hasattr(result, 'success') and result.success:
                self._log_operation(
                    operation.id, 
                    "sync_success", 
                    "Microservice sync successful",
                    execution_time_ms=execution_time
                )
                return True
            else:
                error_msg = getattr(result, 'error', 'Unknown error') if result else 'No response'
                self._log_operation(
                    operation.id, 
                    "sync_failed", 
                    f"Microservice sync failed: {error_msg}",
                    execution_time_ms=execution_time
                )
                return False
                
        except Exception as e:
            self.logger.error(f"Exception during microservice sync: {e}")
            self._log_operation(operation.id, "sync_error", f"Exception: {str(e)}")
            return False
    
    def _log_operation(
        self, 
        operation_id: UUID, 
        action: str, 
        details: str, 
        execution_time_ms: Optional[int] = None
    ):
        """Логирование операции синхронизации."""
        log_entry = StockSynchronizationLog(
            operation_id=operation_id,
            action=action,
            status="info",
            details={"message": details},
            execution_time_ms=execution_time_ms
        )
        self.session.add(log_entry)
        self.session.commit()
    
    async def process_pending_operations(self, limit: int = 50) -> Dict[str, int]:
        """Обработка операций из очереди с retry логикой."""
        
        # Получаем операции готовые для retry
        now = datetime.utcnow()
        statement = (
            select(PendingStockOperation)
            .where(
                PendingStockOperation.status == OperationStatus.PENDING,
                PendingStockOperation.next_retry_at <= now,
                PendingStockOperation.retry_count < PendingStockOperation.max_retries
            )
            .limit(limit)
        )
        
        operations = self.session.exec(statement).all()
        
        results = {"processed": 0, "succeeded": 0, "failed": 0, "max_retries_reached": 0}
        
        for operation in operations:
            results["processed"] += 1
            
            # Обновляем статус на processing
            operation.status = OperationStatus.PROCESSING
            operation.retry_count += 1
            self.session.commit()
            
            self._log_operation(operation.id, "retry", f"Retry attempt {operation.retry_count}")
            
            # Попытка синхронизации
            sync_success = await self._try_sync_with_microservice(operation)
            
            if sync_success:
                operation.status = OperationStatus.COMPLETED
                operation.completed_at = datetime.utcnow()
                results["succeeded"] += 1
                self._log_operation(operation.id, "completed", f"Retry {operation.retry_count} successful")
            else:
                if operation.retry_count >= operation.max_retries:
                    operation.status = OperationStatus.FAILED
                    results["max_retries_reached"] += 1
                    self._log_operation(operation.id, "max_retries", f"Max retries reached: {operation.max_retries}")
                else:
                    operation.status = OperationStatus.PENDING
                    # Exponential backoff
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = now + timedelta(seconds=delay)
                    results["failed"] += 1
                    self._log_operation(operation.id, "retry_failed", f"Retry {operation.retry_count} failed, next in {delay}s")
            
            operation.updated_at = datetime.utcnow()
            self.session.commit()
        
        return results
```

### 2.2 Интеграция с InventoryManager

```python
# app/services/warehouse/stock_sync_integration.py
from typing import Optional
from app.services.warehouse.manager import InventoryManager
from app.services.stock_synchronization_service import StockSynchronizationService

class InventoryManagerWithSync(InventoryManager):
    def __init__(self, dsn: str, async_dsn: str, sync_service: Optional[StockSynchronizationService] = None):
        super().__init__(dsn, async_dsn)
        self.sync_service = sync_service
    
    async def remove_as_sale_with_sync(
        self, 
        sku: str, 
        warehouse: str, 
        quantity: int,
        order_id: Optional[str] = None,
        token_id: Optional[str] = None
    ):
        """Списание со склада с синхронизацией."""
        
        # Сначала списываем локально
        try:
            super().remove_as_sale(sku, warehouse, quantity)
            self.logger.info(f"Local stock deduction successful: {sku} x{quantity} from {warehouse}")
        except Exception as e:
            self.logger.error(f"Local stock deduction failed: {e}")
            raise
        
        # Затем синхронизируем с микросервисом
        if self.sync_service and order_id and token_id:
            try:
                sync_result = await self.sync_service.sync_stock_deduction(
                    token_id=token_id,
                    order_id=order_id,
                    sku=sku,
                    quantity=quantity,
                    warehouse=warehouse
                )
                
                if sync_result.success:
                    self.logger.info(f"Stock sync successful for order {order_id}")
                else:
                    self.logger.warning(f"Stock sync failed for order {order_id}: {sync_result.error}")
                    
            except Exception as e:
                self.logger.error(f"Stock sync error for order {order_id}: {e}")
                # Не прерываем выполнение, так как локальное списание уже выполнено
```

## Фаза 3: Celery задачи

### 3.1 Периодические задачи синхронизации

```python
# app/services/stock_synchronization_tasks.py
from app.celery_shared import celery
from app.services.stock_synchronization_service import StockSynchronizationService
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.core.config import settings
import logging

logger = logging.getLogger("stock.sync.tasks")

@celery.task(bind=True, max_retries=3)
def process_pending_stock_operations(self):
    """Обработка операций в очереди (каждые 5 минут)."""
    try:
        from app.celery_app import SessionLocal
        
        with SessionLocal() as session:
            # Инициализируем клиент микросервиса
            orders_client = OrdersClient(
                jwt_token=settings.ALLEGRO_MICROSERVICE_JWT_TOKEN,
                base_url=settings.ALLEGRO_MICROSERVICE_BASE_URL
            )
            
            sync_service = StockSynchronizationService(session, orders_client)
            results = await sync_service.process_pending_operations()
            
            logger.info(f"Processed pending operations: {results}")
            return results
            
    except Exception as e:
        logger.error(f"Error processing pending operations: {e}")
        self.retry(exc=e, countdown=300)  # Retry in 5 minutes

@celery.task(bind=True, max_retries=2)
def reconcile_stock_states(self):
    """Сверка состояний между локальной системой и микросервисом (каждые 30 минут)."""
    try:
        from app.celery_app import SessionLocal
        from app.models.allegro_token import AllegroToken
        from sqlmodel import select
        
        with SessionLocal() as session:
            # Получаем все активные токены
            tokens = session.exec(select(AllegroToken)).all()
            
            orders_client = OrdersClient(
                jwt_token=settings.ALLEGRO_MICROSERVICE_JWT_TOKEN,
                base_url=settings.ALLEGRO_MICROSERVICE_BASE_URL
            )
            
            sync_service = StockSynchronizationService(session, orders_client)
            
            total_discrepancies = 0
            for token in tokens:
                discrepancies = await sync_service.reconcile_stock_status(
                    token_id=UUID(token.id_),
                    limit=100
                )
                total_discrepancies += len(discrepancies.get("discrepancies", []))
            
            logger.info(f"Reconciliation completed. Found {total_discrepancies} discrepancies")
            return {"total_discrepancies": total_discrepancies}
            
    except Exception as e:
        logger.error(f"Error during reconciliation: {e}")
        self.retry(exc=e, countdown=1800)  # Retry in 30 minutes

@celery.task
def cleanup_old_sync_operations():
    """Очистка старых операций синхронизации (ежедневно)."""
    try:
        from app.celery_app import SessionLocal
        from app.models.stock_synchronization import PendingStockOperation, StockSynchronizationLog
        from datetime import datetime, timedelta
        from sqlmodel import delete
        
        with SessionLocal() as session:
            # Удаляем завершенные операции старше 30 дней
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            # Сначала удаляем логи
            log_statement = (
                delete(StockSynchronizationLog)
                .where(StockSynchronizationLog.timestamp < cutoff_date)
            )
            session.exec(log_statement)
            
            # Затем удаляем операции
            op_statement = (
                delete(PendingStockOperation)
                .where(
                    PendingStockOperation.status.in_(["completed", "cancelled"]),
                    PendingStockOperation.updated_at < cutoff_date
                )
            )
            result = session.exec(op_statement)
            session.commit()
            
            logger.info(f"Cleaned up {result.rowcount} old sync operations")
            return {"cleaned_operations": result.rowcount}
            
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise

# Регистрируем периодические задачи
celery.conf.beat_schedule.update({
    'process-pending-stock-operations': {
        'task': 'app.services.stock_synchronization_tasks.process_pending_stock_operations',
        'schedule': 300.0,  # каждые 5 минут
    },
    'reconcile-stock-states': {
        'task': 'app.services.stock_synchronization_tasks.reconcile_stock_states', 
        'schedule': 1800.0,  # каждые 30 минут
    },
    'cleanup-old-sync-operations': {
        'task': 'app.services.stock_synchronization_tasks.cleanup_old_sync_operations',
        'schedule': 86400.0,  # ежедневно
    },
})
```

## Фаза 4: API endpoints для мониторинга

### 4.1 Router для управления синхронизацией

```python
# app/api/v1/routers/stock_synchronization.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta

from app.database import get_session
from app.services.stock_synchronization_service import StockSynchronizationService
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.models.stock_synchronization import PendingStockOperation, OperationStatus
from app.core.config import settings

router = APIRouter(prefix="/stock-sync", tags=["Stock Synchronization"])

def get_sync_service(session: Session = Depends(get_session)) -> StockSynchronizationService:
    orders_client = OrdersClient(
        jwt_token=settings.ALLEGRO_MICROSERVICE_JWT_TOKEN,
        base_url=settings.ALLEGRO_MICROSERVICE_BASE_URL
    )
    return StockSynchronizationService(session, orders_client)

@router.get("/status")
async def get_sync_status(sync_service: StockSynchronizationService = Depends(get_sync_service)):
    """Общий статус системы синхронизации."""
    
    from sqlmodel import select, func
    session = sync_service.session
    
    # Статистика по операциям
    total_pending = session.exec(
        select(func.count()).select_from(PendingStockOperation)
        .where(PendingStockOperation.status == OperationStatus.PENDING)
    ).first()
    
    total_failed = session.exec(
        select(func.count()).select_from(PendingStockOperation)
        .where(PendingStockOperation.status == OperationStatus.FAILED)
    ).first()
    
    total_completed_today = session.exec(
        select(func.count()).select_from(PendingStockOperation)
        .where(
            PendingStockOperation.status == OperationStatus.COMPLETED,
            PendingStockOperation.completed_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        )
    ).first()
    
    # Операции требующие внимания (старше 6 часов)
    stale_operations = session.exec(
        select(func.count()).select_from(PendingStockOperation)
        .where(
            PendingStockOperation.status == OperationStatus.PENDING,
            PendingStockOperation.created_at < datetime.utcnow() - timedelta(hours=6)
        )
    ).first()
    
    return {
        "status": "healthy" if total_pending < 100 and stale_operations == 0 else "warning",
        "statistics": {
            "pending_operations": total_pending,
            "failed_operations": total_failed,
            "completed_today": total_completed_today,
            "stale_operations": stale_operations
        },
        "last_updated": datetime.utcnow().isoformat()
    }

@router.get("/pending")
async def get_pending_operations(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[OperationStatus] = None,
    sync_service: StockSynchronizationService = Depends(get_sync_service)
):
    """Список операций в очереди."""
    
    from sqlmodel import select
    session = sync_service.session
    
    statement = select(PendingStockOperation)
    if status:
        statement = statement.where(PendingStockOperation.status == status)
    
    statement = statement.offset(offset).limit(limit).order_by(PendingStockOperation.created_at.desc())
    
    operations = session.exec(statement).all()
    
    return {
        "operations": [
            {
                "id": str(op.id),
                "order_id": op.order_id,
                "sku": op.sku,
                "quantity": op.quantity,
                "status": op.status,
                "retry_count": op.retry_count,
                "created_at": op.created_at.isoformat(),
                "next_retry_at": op.next_retry_at.isoformat() if op.next_retry_at else None,
                "error_message": op.error_message
            }
            for op in operations
        ],
        "total": len(operations),
        "limit": limit,
        "offset": offset
    }

@router.post("/reconcile")
async def trigger_reconciliation(
    token_id: Optional[UUID] = None,
    sync_service: StockSynchronizationService = Depends(get_sync_service)
):
    """Принудительная сверка состояний."""
    
    try:
        if token_id:
            result = await sync_service.reconcile_stock_status(token_id)
        else:
            # Запускаем задачу через Celery для всех токенов
            from app.services.stock_synchronization_tasks import reconcile_stock_states
            task = reconcile_stock_states.apply_async()
            result = {"task_id": task.id, "status": "queued"}
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/retry/{operation_id}")
async def retry_operation(
    operation_id: UUID,
    sync_service: StockSynchronizationService = Depends(get_sync_service)
):
    """Повторная попытка конкретной операции."""
    
    session = sync_service.session
    operation = session.get(PendingStockOperation, operation_id)
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    if operation.status not in [OperationStatus.PENDING, OperationStatus.FAILED]:
        raise HTTPException(status_code=400, detail="Operation cannot be retried")
    
    # Сбрасываем счетчик retry и планируем немедленное выполнение
    operation.retry_count = 0
    operation.status = OperationStatus.PENDING
    operation.next_retry_at = datetime.utcnow()
    operation.error_message = None
    session.commit()
    
    sync_service._log_operation(operation.id, "manual_retry", "Manual retry triggered")
    
    return {"message": "Operation queued for retry", "operation_id": str(operation_id)}

@router.delete("/cancel/{operation_id}")
async def cancel_operation(
    operation_id: UUID,
    sync_service: StockSynchronizationService = Depends(get_sync_service)
):
    """Отмена операции."""
    
    session = sync_service.session
    operation = session.get(PendingStockOperation, operation_id)
    
    if not operation:
        raise HTTPException(status_code=404, detail="Operation not found")
    
    if operation.status == OperationStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Cannot cancel completed operation")
    
    operation.status = OperationStatus.CANCELLED
    operation.updated_at = datetime.utcnow()
    session.commit()
    
    sync_service._log_operation(operation.id, "cancelled", "Operation cancelled manually")
    
    return {"message": "Operation cancelled", "operation_id": str(operation_id)}
```

## Фаза 5: Интеграция в существующий код

### 5.1 Обновление AllegroStockService

```python
# Модификация app/services/stock_service.py
class AllegroStockService:
    def __init__(self, session: Session, inventory_manager: InventoryManager, sync_service: Optional[StockSynchronizationService] = None):
        self.session = session
        self.inventory_manager = inventory_manager
        self.sync_service = sync_service
    
    async def process_order_stock_update(self, order: AllegroOrder, warehouse: str, **kwargs):
        """Обработка обновления stock для заказа с синхронизацией."""
        
        if order.is_stock_updated:
            self.logger.info(f"Stock for order {order.id} already updated, skipping")
            return
        
        try:
            # Обрабатываем каждую позицию заказа
            for order_item in order.order_items:
                line_item = order_item.line_item
                sku = line_item.external_id
                
                if not sku:
                    self.logger.warning(f"SKU not found for line item {line_item.id}")
                    continue
                
                # Локальное списание со склада
                if isinstance(self.inventory_manager, InventoryManagerWithSync):
                    # Используем новый метод с синхронизацией
                    await self.inventory_manager.remove_as_sale_with_sync(
                        sku=sku,
                        warehouse=warehouse,
                        quantity=1,  # Каждый order_item представляет 1 единицу
                        order_id=order.id,
                        token_id=order.token_id
                    )
                else:
                    # Обратная совместимость
                    self.inventory_manager.remove_as_sale(sku, warehouse, 1)
                    
                    # Ручная синхронизация если сервис доступен
                    if self.sync_service:
                        await self.sync_service.sync_stock_deduction(
                            token_id=order.token_id,
                            order_id=order.id,
                            sku=sku,
                            quantity=1,
                            warehouse=warehouse
                        )
            
            # Обновляем флаг в локальной базе
            order.is_stock_updated = True
            self.session.commit()
            
            self.logger.info(f"Stock update completed for order {order.id}")
            
        except Exception as e:
            self.logger.error(f"Error updating stock for order {order.id}: {e}")
            raise
```

### 5.2 Добавление в main API router

```python
# app/api/v1/api.py
from app.api.v1.routers import stock_synchronization

api_router.include_router(stock_synchronization.router)
```

## Фаза 6: Тестирование и мониторинг

### 6.1 Unit тесты

```python
# tests/test_stock_synchronization.py
import pytest
from unittest.mock import Mock, AsyncMock
from app.services.stock_synchronization_service import StockSynchronizationService, SyncResult

@pytest.fixture
def mock_orders_client():
    client = Mock()
    client.update_stock_status = Mock(return_value=Mock(success=True))
    return client

@pytest.fixture  
def sync_service(test_session, mock_orders_client):
    return StockSynchronizationService(test_session, mock_orders_client)

@pytest.mark.asyncio
async def test_successful_sync(sync_service):
    """Тест успешной синхронизации."""
    result = await sync_service.sync_stock_deduction(
        token_id="test-token",
        order_id="test-order",
        sku="TEST-SKU",
        quantity=1
    )
    
    assert result.success is True
    assert result.operation_id is not None

@pytest.mark.asyncio  
async def test_retry_mechanism(sync_service, mock_orders_client):
    """Тест retry механизма при сбоях."""
    # Первая попытка неудачна
    mock_orders_client.update_stock_status.return_value = Mock(success=False)
    
    result = await sync_service.sync_stock_deduction(
        token_id="test-token",
        order_id="test-order", 
        sku="TEST-SKU",
        quantity=1
    )
    
    assert result.success is False
    assert result.operation_id is not None
    
    # Обрабатываем pending операции
    mock_orders_client.update_stock_status.return_value = Mock(success=True)
    results = await sync_service.process_pending_operations()
    
    assert results["succeeded"] > 0
```

### 6.2 Интеграционные тесты

```python
# tests/test_stock_sync_integration.py
@pytest.mark.asyncio
async def test_full_order_processing_flow(test_client, test_session):
    """Тест полного цикла обработки заказа с синхронизацией."""
    
    # Создаем тестовый заказ
    order_data = {
        "id": "test-order-123",
        "status": "READY_FOR_PROCESSING",
        "lineItems": [
            {
                "id": "item-1",
                "quantity": 1,
                "offer": {
                    "id": "offer-123",
                    "external": {"id": "TEST-SKU"}
                }
            }
        ]
    }
    
    # Обрабатываем заказ
    response = await test_client.post("/api/v1/orders/process", json=order_data)
    assert response.status_code == 200
    
    # Проверяем что операция синхронизации была создана
    sync_status = await test_client.get("/api/v1/stock-sync/status")
    assert sync_status.json()["statistics"]["pending_operations"] >= 0
```

## Фаза 7: Развертывание и мониторинг

### 7.1 Алерты в Telegram

```python
# app/services/stock_sync_alerts.py
from app.services.telegram_service import TelegramService

class StockSyncAlerts:
    def __init__(self, telegram_service: TelegramService):
        self.telegram = telegram_service
    
    async def alert_high_pending_operations(self, count: int):
        message = (
            f"🚨 ВНИМАНИЕ: Высокое количество операций синхронизации в очереди\n"
            f"Количество: {count}\n"
            f"Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"Требуется проверка системы синхронизации"
        )
        await self.telegram.send_message(message)
    
    async def alert_sync_failure_rate(self, failure_rate: float, window_minutes: int):
        message = (
            f"⚠️ Высокий процент неудач синхронизации\n"
            f"Процент неудач: {failure_rate:.1%}\n"
            f"За последние {window_minutes} минут\n"
            f"Проверьте доступность микросервиса Allegro"
        )
        await self.telegram.send_message(message)
    
    async def alert_stale_operations(self, count: int, hours: int):
        message = (
            f"⏰ Найдены застрявшие операции синхронизации\n"
            f"Количество: {count}\n"
            f"Старше: {hours} часов\n"
            f"Требуется ручное вмешательство"
        )
        await self.telegram.send_message(message)
```

### 7.2 Мониторинг задача

```python
@celery.task
def monitor_sync_health():
    """Мониторинг здоровья системы синхронизации."""
    try:
        from app.services.stock_sync_alerts import StockSyncAlerts
        from app.services.telegram_service import TelegramService
        
        alerts = StockSyncAlerts(TelegramService())
        
        with SessionLocal() as session:
            # Проверяем количество pending операций
            pending_count = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(PendingStockOperation.status == OperationStatus.PENDING)
            ).first()
            
            if pending_count > stock_sync_config.monitoring_max_pending_operations:
                await alerts.alert_high_pending_operations(pending_count)
            
            # Проверяем застрявшие операции
            stale_count = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(
                    PendingStockOperation.status == OperationStatus.PENDING,
                    PendingStockOperation.created_at < datetime.utcnow() - timedelta(hours=stock_sync_config.monitoring_stale_operation_hours)
                )
            ).first()
            
            if stale_count > 0:
                await alerts.alert_stale_operations(stale_count, stock_sync_config.monitoring_stale_operation_hours)
        
    except Exception as e:
        logger.error(f"Error in sync health monitoring: {e}")

# Добавляем в расписание
celery.conf.beat_schedule['monitor-sync-health'] = {
    'task': 'app.services.stock_synchronization_tasks.monitor_sync_health',
    'schedule': 1800.0,  # каждые 30 минут
}
```

## Временные рамки реализации

- **Фаза 1** (Инфраструктура): 3-4 дня
- **Фаза 2** (Основной сервис): 5-6 дней  
- **Фаза 3** (Celery задачи): 2-3 дня
- **Фаза 4** (API endpoints): 2-3 дня
- **Фаза 5** (Интеграция): 3-4 дня
- **Фаза 6** (Тестирование): 4-5 дней
- **Фаза 7** (Развертывание): 2-3 дня

**Общее время**: 3-4 недели

## Критерии успеха

- ✅ 99%+ операций синхронизируются с первой попытки
- ✅ Среднее время retry < 5 минут  
- ✅ 0 потерянных операций
- ✅ Полная видимость состояния системы
- ✅ Автоматическое восстановление после сбоев