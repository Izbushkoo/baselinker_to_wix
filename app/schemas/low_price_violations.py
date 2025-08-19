"""
 * @file: low_price_violations.py
 * @description: Схемы данных для нарушений минимальных цен при продажах
 * @dependencies: pydantic, decimal
 * @created: 2025-01-15
"""

from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, computed_field


class LowPriceViolation(BaseModel):
    """
    Модель данных для нарушения минимальной цены при продаже товара
    """
    sku: str = Field(..., description="SKU товара")
    product_name: str = Field(..., description="Название товара")
    sale_price: Decimal = Field(..., description="Цена продажи")
    minimum_price: Decimal = Field(..., description="Минимальная цена")
    
    @computed_field
    @property
    def violation_amount(self) -> Decimal:
        """Сумма нарушения (минимальная цена - цена продажи)"""
        return self.minimum_price - self.sale_price
    
    @computed_field
    @property
    def violation_percentage(self) -> float:
        """Процент нарушения относительно минимальной цены"""
        if self.minimum_price == 0:
            return 0.0
        return float((self.violation_amount / self.minimum_price) * 100)
    
    class Config:
        frozen = True  # Immutable model
        json_encoders = {
            Decimal: lambda v: str(v)
        }


class LowPriceViolationSummary(BaseModel):
    """
    Сводка по нарушениям минимальных цен для заказа
    """
    account_name: str = Field(..., description="Название аккаунта")
    order_id: str = Field(..., description="ID заказа")
    operation_id: Optional[str] = Field(None, description="ID операции")
    violations: list[LowPriceViolation] = Field(..., description="Список нарушений")
    total_violation_amount: Decimal = Field(..., description="Общая сумма нарушений")
    
    @computed_field
    @property
    def violation_count(self) -> int:
        """Количество нарушений в заказе"""
        return len(self.violations)
    
    @computed_field
    @property
    def has_violations(self) -> bool:
        """Есть ли нарушения в заказе"""
        return self.violation_count > 0
    
    class Config:
        frozen = True
        json_encoders = {
            Decimal: lambda v: str(v)
        }
