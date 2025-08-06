from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class SyncResult(BaseModel):
    """Результат операции синхронизации."""
    success: bool
    operation_id: Optional[UUID] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ProcessingResult(BaseModel):
    """Результат обработки операций из очереди."""
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    max_retries_reached: int = 0
    details: List[Dict[str, Any]] = Field(default_factory=list)


class ReconciliationResult(BaseModel):
    """Результат сверки состояний."""
    total_checked: int = 0
    discrepancies_found: int = 0
    auto_fixed: int = 0
    requires_manual_review: int = 0
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)


class StockValidationResult(BaseModel):
    """Результат валидации складских остатков."""
    valid: bool
    available_quantity: int = 0
    error_message: str = ""
    warehouse: str = ""
    sku: str = ""
    required_quantity: int = 0
    
    @property
    def shortage_quantity(self) -> int:
        """Количество недостающего товара."""
        return max(0, self.required_quantity - self.available_quantity)
    
    @property
    def shortage_percentage(self) -> float:
        """Процент недостающего товара."""
        if self.required_quantity <= 0:
            return 0.0
        return (self.shortage_quantity / self.required_quantity) * 100


class OrderValidationResult(BaseModel):
    """Результат валидации всего заказа."""
    valid: bool
    total_items: int = 0
    valid_items: int = 0
    invalid_items: int = 0
    validation_details: Dict[str, StockValidationResult] = Field(default_factory=dict)
    error_summary: List[str] = Field(default_factory=list)
    
    @property
    def validation_success_rate(self) -> float:
        """Процент успешно валидированных позиций."""
        if self.total_items <= 0:
            return 100.0
        return (self.valid_items / self.total_items) * 100


class SyncStatistics(BaseModel):
    """Статистика системы синхронизации."""
    pending_operations: int
    failed_operations: int
    completed_today: int
    stale_operations: int
    health_status: str
    last_updated: str
    error: Optional[str] = None