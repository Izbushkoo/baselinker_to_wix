from sqlmodel import SQLModel, Field
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy import JSON, ForeignKey
from uuid import UUID, uuid4

class OperationType(str, Enum):
    STOCK_IN = "stock_in"  # Приход товара (одиночный)
    STOCK_IN_FILE = "stock_in_file"  # Массовый приход товара через файл
    STOCK_OUT_ORDER = "stock_out_order"  # Списание по заказу
    STOCK_OUT_MANUAL = "stock_out_manual"  # Ручное списание
    TRANSFER = "transfer"  # Перемещение между складами
    TRANSFER_FILE = "transfer_file"  # Массовое перемещение через файл
    PRODUCT_CREATE = "product_create"  # Создание нового товара
    PRODUCT_DELETE = "product_delete"  # Удаление товара

class Operation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # Тип операции
    operation_type: str = Field(...)
    
    # Временные метки
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Информация об исполнителе
    user_email: Optional[str] = None  # Email пользователя, если операция выполнена вручную

    # Связанные идентификаторы
    order_id: Optional[str] = None  # ID заказа, если операция связана с заказом
    file_name: Optional[str] = None  # Имя файла, если операция выполнена через файл
    
    # Информация о складах
    warehouse_id: Optional[str] = Field(default=None)  # Основной склад (опциональный для удаления товара)
    target_warehouse_id: Optional[str] = None  # Целевой склад для перемещений
    
    # Данные о товарах (хранятся в JSON для гибкости)
    products_data: Dict = Field(default={}, sa_type=JSON)
    # Формат products_data для разных типов операций:
    # Одиночная операция: {"sku": "ABC123", "quantity": 5}
    # Массовая операция: {"products": [{"sku": "ABC123", "quantity": 5}, {"sku": "XYZ789", "quantity": 3}]}
    # Создание товара: {"sku": "ABC123", "name": "Product Name", "initial_quantity": 10}
    # Удаление товара: {"sku": "ABC123"}
    
    # Дополнительная информация
    comment: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
