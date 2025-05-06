from sqlmodel import SQLModel, Field
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy import JSON, ForeignKey
from uuid import UUID, uuid4

class OperationType(str, Enum):
    STOCK_IN = "stock_in"  # Приход товара (одиночный)
    STOCK_IN_BULK = "stock_in_bulk"  # Массовый приход товара через файл
    STOCK_OUT_ORDER = "stock_out_order"  # Списание по заказу
    STOCK_OUT_MANUAL = "stock_out_manual"  # Ручное списание
    TRANSFER = "transfer"  # Перемещение между складами
    TRANSFER_BULK = "transfer_bulk"  # Массовое перемещение через файл

class Operation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Тип операции
    operation_type: OperationType = Field(...)
    
    # Временные метки
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Информация об исполнителе
    user_email: Optional[str] = None  # Email пользователя, если операция выполнена вручную
    is_automatic: bool = Field(default=False)  # Флаг автоматической операции    
    # Связанные идентификаторы
    order_id: Optional[str] = None  # ID заказа, если операция связана с заказом
    file_name: Optional[str] = None  # Имя файла, если операция выполнена через файл
    
    # Информация о складах
    warehouse_id: str = Field(...)  # Основной склад
    target_warehouse_id: Optional[str] = None  # Целевой склад для перемещений
    
    # Данные о товарах (хранятся в JSON для гибкости)
    products_data: Dict = Field(default={}, sa_type=JSON)
    # Формат products_data для разных типов операций:
    # Одиночная операция: {"sku": "ABC123", "quantity": 5}
    # Массовая операция: {"products": [{"sku": "ABC123", "quantity": 5}, {"sku": "XYZ789", "quantity": 3}]}
    
    # Дополнительная информация
    comment: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
