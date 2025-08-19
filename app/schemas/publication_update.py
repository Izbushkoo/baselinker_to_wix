"""
 * @file: publication_update.py
 * @description: Pydantic схемы для API обновления данных о публикации офферт Allegro
 * @dependencies: pydantic
 * @created: 2024-12-19
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class PublicationUpdateRequest(BaseModel):
    """Запрос на обновление данных о публикации"""
    skus: Optional[List[str]] = Field(None, description="Список SKU для обновления. Если None - обновить все товары")
    batch_size: Optional[int] = Field(100, ge=1, le=1000, description="Размер батча для обработки")


class PublicationUpdateResponse(BaseModel):
    """Ответ на запрос обновления данных о публикации"""
    status: str = Field(..., description="Статус операции: 'started', 'completed', 'already_running', 'error'")
    total_products: int = Field(..., description="Общее количество товаров для обработки")
    updated_products: Optional[int] = Field(None, description="Количество обновленных товаров")
    skipped_products: Optional[int] = Field(None, description="Количество пропущенных товаров")
    errors: List[str] = Field(default_factory=list, description="Список ошибок")
    task_id: Optional[str] = Field(None, description="ID Celery задачи")
    message: str = Field(..., description="Описание результата операции")


class PublicationDateResponse(BaseModel):
    """Ответ с данными о дате публикации товара"""
    sku: str = Field(..., description="SKU товара")
    first_publication_date: Optional[datetime] = Field(None, description="Дата первой публикации офферты")
    offer_count: int = Field(..., description="Количество офферт для товара")
    last_updated: datetime = Field(..., description="Время последнего обновления данных")


class PublicationUpdateStatus(BaseModel):
    """Статус выполнения задачи обновления"""
    task_id: str = Field(..., description="ID Celery задачи")
    status: str = Field(..., description="Статус задачи: 'PENDING', 'STARTED', 'SUCCESS', 'FAILURE'")
    progress: Optional[float] = Field(None, ge=0, le=100, description="Прогресс выполнения в процентах")
    result: Optional[PublicationUpdateResponse] = Field(None, description="Результат выполнения")
    error: Optional[str] = Field(None, description="Описание ошибки")
    created_at: datetime = Field(..., description="Время создания задачи")
    updated_at: datetime = Field(..., description="Время последнего обновления")
