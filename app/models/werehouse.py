from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlalchemy import Column, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from typing import List, Dict, Optional
from datetime import datetime


# ORM-модели
class Product(SQLModel, table=True):
    '''ORM-модель товара.'''
    sku: str = Field(primary_key=True)
    eans: List[str] = Field(sa_column=Column(JSONB), default_factory=list)
    name: str
    image: Optional[bytes] = Field(sa_column=Column(LargeBinary), default=None)

class Stock(SQLModel, table=True):
    '''ORM-модель остатка на складе.'''
    sku: str = Field(foreign_key='product.sku', primary_key=True)
    warehouse: str = Field(primary_key=True)
    quantity: int = Field(default=0)

class Sale(SQLModel, table=True):
    '''Лог продаж (списаний) для аналитики.'''
    id: Optional[int] = Field(default=None, primary_key=True)
    sku: str = Field(foreign_key='product.sku')
    warehouse: str
    quantity: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)