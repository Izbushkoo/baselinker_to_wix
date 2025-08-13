from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
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


class NotificationStatus(str, Enum):
    """Статусы уведомлений."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # Подавлено из-за частых повторов


class PendingStockOperation(SQLModel, table=True):
    """
    Модель для отслеживания операций синхронизации складских остатков.
    
    Каждая позиция заказа (SKU) создает отдельную операцию.
    Операции группируются по заказу (token_id + order_id).
    """
    __tablename__ = "pending_stock_operations"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Идентификация операции
    token_id: str = Field(index=True, description="ID токена Allegro из микросервиса")
    order_id: str = Field(index=True, description="ID заказа Allegro")
    account_name: Optional[str] = Field(default=None, index=True, description="Имя аккаунта Allegro")
    
    # Детали операции
    operation_type: OperationType = Field(description="Тип операции")
    status: OperationStatus = Field(default=OperationStatus.PENDING, index=True, description="Статус операции")
    warehouse: str = Field(default="Ирина", description="Название склада")
    
    # Retry механизм
    retry_count: int = Field(default=0, description="Количество выполненных попыток")
    next_retry_at: Optional[datetime] = Field(default=None, index=True, description="Время следующей попытки")
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True, description="Время создания")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Время обновления")
    completed_at: Optional[datetime] = Field(default=None, description="Время завершения")
    error_message: Optional[str] = Field(default=None, description="Сообщение об ошибке")
    
    # Дополнительные поля
    allegro_order_id: Optional[str] = Field(default=None, index=True, description="ID заказа Allegro (без связи, таблица в микросервисе)")
    line_items: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON), description="Позиции заказа (lineItems) от микросервиса")

    def is_ready_for_retry(self, max_retries: int = 5) -> bool:
        """Проверяет, готова ли операция для повторной попытки."""
        return (
            self.status == OperationStatus.PENDING and
            self.retry_count < max_retries and
            (self.next_retry_at is None or self.next_retry_at <= datetime.utcnow())
        )
    
    def increment_retry(self, exponential_base: float = 2.0, initial_delay: int = 60, max_delay: int = 3600):
        """Увеличивает счетчик попыток и планирует следующую попытку."""
        self.retry_count += 1
        self.updated_at = datetime.utcnow()
        
        # Планируем следующую попытку с exponential backoff
        delay = min(
            initial_delay * (exponential_base ** (self.retry_count - 1)),
            max_delay
        )
        self.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)

    @property
    def order_key(self) -> str:
        """Ключ заказа для группировки операций."""
        return f"{self.token_id}:{self.order_id}"

    @property
    def unique_operation_key(self) -> str:
        """Уникальный ключ операции (заказ)."""
        return f"{self.token_id}:{self.order_id}"


class OrderNotificationTracker(SQLModel, table=True):
    """
    Отслеживание уведомлений по заказам для предотвращения спама.
    
    Группирует уведомления по заказу (token_id + order_id) и контролирует
    частоту отправки для предотвращения спама.
    """
    __tablename__ = "order_notification_tracker"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Идентификация заказа
    token_id: str = Field(index=True, description="ID токена Allegro")
    order_id: str = Field(index=True, description="ID заказа")
    account_name: str = Field(description="Название аккаунта для персонализации")
    
    # Статус уведомлений
    validation_failure_notified: bool = Field(default=False, description="Отправлено уведомление о провале валидации")
    max_retries_notified: bool = Field(default=False, description="Отправлено уведомление о превышении лимита попыток")
    
    # Контроль частоты
    last_notification_at: Optional[datetime] = Field(default=None, description="Время последнего уведомления")
    notification_count: int = Field(default=0, description="Количество отправленных уведомлений")
    suppression_until: Optional[datetime] = Field(default=None, description="Подавление уведомлений до указанного времени")
    
    # Метаданные
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True, description="Время создания")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Время обновления")
    
    # Дополнительная информация о заказе
    order_details: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON), description="Детали заказа")

    def can_send_notification(self, notification_type: str, min_interval_minutes: int = 30) -> bool:
        """
        Проверяет, можно ли отправить уведомление.
        
        Args:
            notification_type: Тип уведомления ('validation_failure', 'max_retries', 'retry_failure')
            min_interval_minutes: Минимальный интервал между уведомлениями в минутах
            
        Returns:
            bool: True если можно отправить уведомление
        """
        now = datetime.utcnow()
        
        # Проверяем подавление уведомлений
        if self.suppression_until and now < self.suppression_until:
            return False
        
        # Проверяем уже отправленные критические уведомления
        if notification_type == 'validation_failure' and self.validation_failure_notified:
            return False
        if notification_type == 'max_retries' and self.max_retries_notified:
            return False
        
        # Проверяем минимальный интервал
        if self.last_notification_at:
            time_since_last = now - self.last_notification_at
            if time_since_last < timedelta(minutes=min_interval_minutes):
                return False
        
        return True

    def record_notification(self, notification_type: str, suppress_for_hours: int = 0):
        """
        Записывает факт отправки уведомления.
        
        Args:
            notification_type: Тип уведомления
            suppress_for_hours: Подавить уведомления на указанное количество часов
        """
        now = datetime.utcnow()
        
        self.last_notification_at = now
        self.notification_count += 1
        self.updated_at = now
        
        # Отмечаем специальные типы уведомлений
        if notification_type == 'validation_failure':
            self.validation_failure_notified = True
        elif notification_type == 'max_retries':
            self.max_retries_notified = True
        
        # Устанавливаем подавление если нужно
        if suppress_for_hours > 0:
            self.suppression_until = now + timedelta(hours=suppress_for_hours)

    @property
    def order_key(self) -> str:
        """Ключ заказа для идентификации."""
        return f"{self.token_id}:{self.order_id}"


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