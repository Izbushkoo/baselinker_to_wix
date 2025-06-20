"""
 * @file: product.py
 * @description: Pydantic схемы для работы с продуктами (создание, обновление, ответы)
 * @dependencies: app.models.warehouse.Product
 * @created: 2024-03-21
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List
from fastapi import UploadFile


class ProductBase(BaseModel):
    """Базовая схема для продукта"""
    model_config = ConfigDict(from_attributes=True)
    
    name: str = Field(..., min_length=1, max_length=255, description="Название товара")
    sku: str = Field(..., min_length=1, max_length=50, description="Уникальный идентификатор товара")
    ean: Optional[str] = Field(None, max_length=1000, description="EAN коды через запятую")

    @field_validator('ean')
    @classmethod
    def validate_ean(cls, v):
        """Валидация EAN кодов"""
        if v is not None:
            # Разбиваем по запятой и проверяем каждый EAN
            eans = [e.strip() for e in v.split(',') if e.strip()]
            for ean in eans:
                if not ean.isdigit() or len(ean) not in [8, 12, 13, 14]:
                    raise ValueError(f"Некорректный EAN код: {ean}")
        return v


class ProductCreate(ProductBase):
    """Схема для создания нового продукта"""
    warehouse: str = Field(..., description="Склад для размещения товара")
    quantity: int = Field(..., ge=0, description="Начальное количество товара")


class ProductUpdate(BaseModel):
    """Схема для обновления продукта (частичное обновление)"""
    model_config = ConfigDict(from_attributes=True)
    
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название товара")
    sku: Optional[str] = Field(None, min_length=1, max_length=50, description="Уникальный идентификатор товара")
    ean: Optional[str] = Field(None, max_length=1000, description="EAN коды через запятую")
    
    @field_validator('ean')
    @classmethod
    def validate_ean(cls, v):
        """Валидация EAN кодов"""
        if v is not None:
            # Разбиваем по запятой и проверяем каждый EAN
            eans = [e.strip() for e in v.split(',') if e.strip()]
            for ean in eans:
                if not ean.isdigit() or len(ean) not in [8, 12, 13, 14]:
                    raise ValueError(f"Некорректный EAN код: {ean}")
        return v
    
    @field_validator('sku')
    @classmethod
    def validate_sku_format(cls, v):
        """Валидация формата SKU"""
        if v is not None:
            # Проверяем, что SKU содержит только буквы, цифры, дефисы и подчеркивания
            if not v.replace('-', '').replace('_', '').isalnum():
                raise ValueError("SKU может содержать только буквы, цифры, дефисы и подчеркивания")
        return v


class ProductResponse(BaseModel):
    """Схема для ответа с данными продукта"""
    model_config = ConfigDict(from_attributes=True)
    
    sku: str
    name: str
    eans: List[str]
    ean: Optional[str] = None  # Первый EAN для отображения
    image: Optional[str] = None  # Base64 изображение
    total_stock: int = 0
    stocks: dict = {}


class ProductEditForm(BaseModel):
    """Схема для формы редактирования продукта"""
    model_config = ConfigDict(from_attributes=True)
    
    name: str = Field(..., min_length=1, max_length=255)
    sku: str = Field(..., min_length=1, max_length=50)
    ean: Optional[str] = Field(None, max_length=1000)
    current_image: Optional[str] = Field(None, description="Base64 текущего изображения")
    
    @field_validator('ean')
    @classmethod
    def validate_ean(cls, v):
        """Валидация EAN кодов"""
        if v is not None:
            eans = [e.strip() for e in v.split(',') if e.strip()]
            for ean in eans:
                if not ean.isdigit() or len(ean) not in [8, 12, 13, 14]:
                    raise ValueError(f"Некорректный EAN код: {ean}")
        return v


class ProductUpdateRequest(BaseModel):
    """Схема для запроса обновления продукта с файлом"""
    model_config = ConfigDict(from_attributes=True)
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    sku: Optional[str] = Field(None, min_length=1, max_length=50)
    ean: Optional[str] = Field(None, max_length=1000)
    image: Optional[UploadFile] = None
    
    @field_validator('ean')
    @classmethod
    def validate_ean(cls, v):
        """Валидация EAN кодов"""
        if v is not None:
            eans = [e.strip() for e in v.split(',') if e.strip()]
            for ean in eans:
                if not ean.isdigit() or len(ean) not in [8, 12, 13, 14]:
                    raise ValueError(f"Некорректный EAN код: {ean}")
        return v


class ProductEditOperation(BaseModel):
    """Схема для логирования операции редактирования продукта"""
    model_config = ConfigDict(from_attributes=True)
    
    sku: str
    old_values: dict
    new_values: dict
    user_email: str
    timestamp: str 