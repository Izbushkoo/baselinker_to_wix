from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, Column
from uuid import UUID, uuid4
from enum import Enum


class OperationType(str, Enum):
    """Типы операций синхронизации складских остатков."""
    DEDUCTION = "deduction"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class OperationStatus(str, Enum):
    """Статусы операций синхронизации."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PendingStockOperation(SQLModel, table=True):
    """
    Модель для отслеживания операций синхронизации складских остатков.
    
    Хранит информацию о операциях, которые требуют синхронизации 
    между локальной системой и микросервисом Allegro.
    """
    __tablename__ = "pending_stock_operations"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_id: str = Field(index=True, description="ID заказа Allegro")
    operation_type: OperationType = Field(description="Тип операции")
    status: OperationStatus = Field(default=OperationStatus.PENDING, index=True, description="Статус операции")
    
    # Детали операции
    sku: str = Field(index=True, description="SKU товара")
    quantity: int = Field(description="Количество")
    warehouse: str = Field(default="Ирина", description="Название склада")
    
    # Retry механизм
    retry_count: int = Field(default=0, description="Количество попыток")
    max_retries: int = Field(default=5, description="Максимальное количество попыток")
    next_retry_at: datetime = Field(index=True, description="Время следующей попытки")
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True, description="Время создания")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Время обновления")
    completed_at: Optional[datetime] = Field(default=None, description="Время завершения")
    error_message: Optional[str] = Field(default=None, description="Сообщение об ошибке")
    
    # Связи с другими таблицами
    token_id: str = Field(index=True, description="ID токена Allegro из микросервиса")
    allegro_order_id: Optional[str] = Field(foreign_key="allegro_orders.id", default=None, description="ID заказа в системе")

    def is_ready_for_retry(self) -> bool:
        """Проверяет, готова ли операция для повторной попытки."""
        return (
            self.status == OperationStatus.PENDING and
            self.retry_count < self.max_retries and
            self.next_retry_at <= datetime.utcnow()
        )
    
    def increment_retry(self, exponential_base: float = 2.0, initial_delay: int = 60, max_delay: int = 3600):
        """Увеличивает счетчик попыток и планирует следующую попытку."""
        self.retry_count += 1
        self.updated_at = datetime.utcnow()
        
        if self.retry_count >= self.max_retries:
            self.status = OperationStatus.FAILED
        else:
            # Exponential backoff с jitter
            delay = min(
                initial_delay * (exponential_base ** (self.retry_count - 1)),
                max_delay
            )
            self.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)


class StockSynchronizationLog(SQLModel, table=True):
    """
    Лог всех операций синхронизации для аудита и отладки.
    
    Хранит детальную информацию о каждом действии в процессе синхронизации.
    """
    __tablename__ = "stock_synchronization_logs"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    operation_id: UUID = Field(foreign_key="pending_stock_operations.id", index=True, description="ID операции")
    action: str = Field(index=True, description="Действие (created, retry, completed, failed, rolled_back)")
    status: str = Field(description="Статус (info, warning, error)")
    details: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON), description="Детали операции")
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True, description="Время события")
    execution_time_ms: Optional[int] = Field(default=None, description="Время выполнения в миллисекундах")

    def __str__(self) -> str:
        return f"Log({self.action}) for operation {self.operation_id} at {self.timestamp}"