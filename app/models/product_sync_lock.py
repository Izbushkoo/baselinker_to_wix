"""
 * @file: product_sync_lock.py
 * @description: Модель блокировки синхронизации товара по SKU
 * @dependencies: SQLModel, datetime
 * @created: 2024-06-13
"""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field

class ProductSyncLock(SQLModel, table=True):
    sku: str = Field(primary_key=True, description="SKU товара")
    locked_at: datetime = Field(default_factory=datetime.utcnow, description="Время установки блокировки")
    lock_owner: str = Field(description="Идентификатор владельца блокировки (например, UUID задачи)")
    status: str = Field(default="in_progress", description="Статус: in_progress, success, error")
    last_error: Optional[str] = Field(default=None, description="Последняя ошибка, если была")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Время последнего обновления записи") 