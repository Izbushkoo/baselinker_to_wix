from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import JSON
from uuid import UUID, uuid4

class AllegroBuyer(SQLModel, table=True):
    __tablename__ = "allegro_buyers"
    
    id: str = Field(primary_key=True)  # allegro_id из API
    email: str
    login: str
    first_name: str
    last_name: str
    company_name: Optional[str] = None
    phone_number: str
    address: Dict[str, Any] = Field(default={}, sa_type=JSON)  # JSON структура адреса
    
    # Связь с заказами
    orders: List["AllegroOrder"] = Relationship(back_populates="buyer")

class AllegroLineItem(SQLModel, table=True):
    __tablename__ = "allegro_line_items"
    
    id: str = Field(primary_key=True)  # allegro_id из API
    
    # Данные о товаре
    offer_id: str
    offer_name: str
    external_id: str
    
    # JSON структуры для цен
    original_price: Dict[str, Any] = Field(default={}, sa_type=JSON)  # Структура originalPrice
    price: Dict[str, Any] = Field(default={}, sa_type=JSON)  # Структура price
    
    # Связь с заказами через промежуточную таблицу
    order_items: List["OrderLineItem"] = Relationship(back_populates="line_item")

class OrderLineItem(SQLModel, table=True):
    __tablename__ = "order_line_items"
    
    id: Optional[UUID] = Field(default_factory=uuid4, primary_key=True)
    order_id: str = Field(foreign_key="allegro_orders.id")
    line_item_id: str = Field(foreign_key="allegro_line_items.id")
    
    # Связи
    order: "AllegroOrder" = Relationship(back_populates="order_items")
    line_item: AllegroLineItem = Relationship(back_populates="order_items")

class AllegroOrder(SQLModel, table=True):
    __tablename__ = "allegro_orders"
    
    id: str = Field(primary_key=True)  # allegro_id из API
    status: str
    updated_at: datetime = Field()
    belongs_to: str = Field(nullable=False, default="1")
    
    # Связь с токеном
    token_id: str = Field(foreign_key="allegro_tokens.id_")
    token: "AllegroToken" = Relationship(back_populates="orders")
    
    # Связь с покупателем
    buyer_id: str = Field(foreign_key="allegro_buyers.id")
    buyer: AllegroBuyer = Relationship(back_populates="orders")
    
    # JSON структуры для вложенных данных
    payment: Dict[str, Any] = Field(default={}, sa_type=JSON)  # Вся структура payment
    fulfillment: Dict[str, Any] = Field(default={}, sa_type=JSON)  # Вся структура fulfillment
    delivery: Dict[str, Any] = Field(default={}, sa_type=JSON)  # Вся структура delivery
    
    # Связь с товарными позициями через промежуточную таблицу
    order_items: List[OrderLineItem] = Relationship(back_populates="order") 