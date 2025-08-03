from sqlmodel import SQLModel, Field, Session, create_engine, select, Relationship
from sqlalchemy import Column, LargeBinary, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from typing import List, Dict, Optional
from datetime import datetime


# ORM-модели
class Product(SQLModel, table=True):
    '''ORM-модель товара.'''
    sku: str = Field(primary_key=True)
    eans: List[str] = Field(sa_column=Column(JSONB), default_factory=list)
    name: str
    image: Optional[bytes] = Field(sa_column=Column(LargeBinary), default=None, description="Сжатое изображение 100x100 WebP")
    original_image: Optional[bytes] = Field(sa_column=Column(LargeBinary), default=None, description="Оригинальное изображение")
    image_url: Optional[str] = Field(default=None, description="URL для доступа к оригинальному изображению")
    brand: Optional[str] = Field(default=None, description="Бренд товара")
    
    # Связи с другими таблицами
    stocks: List["Stock"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    sales: List["Sale"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    transfers: List["Transfer"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    # Связь с настройками синхронизации Allegro
    allegro_sync_settings: List["ProductAllegroSyncSettings"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class Stock(SQLModel, table=True):
    '''ORM-модель остатка на складе.'''
    sku: str = Field(
        sa_column=Column(
            ForeignKey("product.sku", ondelete="CASCADE", onupdate="CASCADE"),
            primary_key=True
        )
    )
    warehouse: str = Field(primary_key=True)
    quantity: int = Field(default=0)
    
    # Связь с товаром
    product: Optional[Product] = Relationship(back_populates="stocks")


class Sale(SQLModel, table=True):
    '''Лог продаж (списаний) для аналитики.'''
    id: Optional[int] = Field(default=None, primary_key=True)
    sku: str = Field(
        sa_column=Column(
            ForeignKey("product.sku", ondelete="CASCADE", onupdate="CASCADE")
        )
    )
    warehouse: str
    quantity: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Связь с товаром
    product: Optional[Product] = Relationship(back_populates="sales")


class Transfer(SQLModel, table=True):
    '''Лог перемещений товаров между складами.'''
    id: Optional[int] = Field(default=None, primary_key=True)
    sku: str = Field(
        sa_column=Column(
            ForeignKey("product.sku", ondelete="CASCADE", onupdate="CASCADE")
        )
    )
    source: str
    destination: str
    quantity: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Связь с товаром
    product: Optional[Product] = Relationship(back_populates="transfers")