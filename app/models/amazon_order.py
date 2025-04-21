import uuid
from typing import List, Optional, Dict
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column
from sqlalchemy.types import JSON


# Таблица заказов
class Order(SQLModel, table=True):
    # Основной идентификатор заказа (amazon_order_id) используется в качестве первичного ключа
    amazon_order_id: str = Field(primary_key=True, description="Уникальный идентификатор заказа в Amazon")

    # Дополнительные поля заказа, взятые из документации API. Можно добавлять или изменять поля по необходимости.
    seller_order_id: Optional[str] = Field(default=None, description="Идентификатор заказа продавца")
    purchase_date: Optional[datetime] = Field(default=None, description="Дата покупки")
    last_update_date: Optional[datetime] = Field(default=None, description="Дата последнего обновления")
    order_status: Optional[str] = Field(default=None, description="Статус заказа")
    fulfillment_channel: Optional[str] = Field(default=None, description="Канал выполнения заказа")
    sales_channel: Optional[str] = Field(default=None, description="Канал продаж")
    order_channel: Optional[str] = Field(default=None, description="Канал заказа")

    # Поля, содержащие вложенные структуры, храним как JSON
    order_total: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                        description="Общая сумма заказа (например, с информацией о валюте и сумме)")
    shipping_address: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                             description="Адрес доставки в формате JSON")

    # Прочие поля
    number_of_items_shipped: Optional[int] = Field(default=None, description="Количество отправленных позиций")
    number_of_items_unshipped: Optional[int] = Field(default=None, description="Количество неотправленных позиций")
    payment_method: Optional[str] = Field(default=None, description="Метод оплаты")
    shipping_service: Optional[str] = Field(default=None, description="Служба доставки")

    # Если есть дополнительные вложенные данные, которые не хочется проецировать в отдельные столбцы – можно поместить их сюда
    additional_data: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                            description="Дополнительные вложенные данные заказа")

    # Определяем связь «один-ко-многим» с таблицей OrderItem. Это позволит выполнять запросы для получения всех позиций заказа.
    order_items: List["OrderItem"] = Relationship(back_populates="order")


# Таблица позиций заказа (order items)
class OrderItem(SQLModel, table=True):
    # В качестве первичного ключа используется собственное автоинкрементное поле id
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, description="Уникальный идентификатор позиции заказа")

    # Внешний ключ, связывающий позицию с заказом по amazon_order_id
    amazon_order_id: str = Field(foreign_key="order.amazon_order_id",
                                 description="ID заказа, к которому принадлежит позиция")

    # Поля, описываемые в документации для позиций заказа
    order_item_id: Optional[str] = Field(default=None, description="Уникальный идентификатор позиции заказа")
    asin: Optional[str] = Field(default=None, description="Amazon Standard Identification Number товара")
    seller_sku: Optional[str] = Field(default=None, description="SKU продавца")

    # Вложенные объекты, такие как информация о цене, храним в формате JSON
    item_price: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description="Цена товара (JSON)")
    shipping_price: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                           description="Стоимость доставки (JSON)")
    gift_wrap_price: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                            description="Стоимость упаковки подарка (JSON)")
    item_tax: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description="Налог на товар (JSON)")
    shipping_tax: Optional[Dict] = Field(default=None, sa_column=Column(JSON), description="Налог на доставку (JSON)")

    quantity_ordered: Optional[int] = Field(default=None, description="Количество заказанного товара")
    gift_message_text: Optional[str] = Field(default=None, description="Сообщение в подарке")

    # Дополнительные вложенные данные для позиции заказа
    additional_data: Optional[Dict] = Field(default=None, sa_column=Column(JSON),
                                            description="Дополнительные вложенные данные позиции заказа")

    # Определяем обратную связь – каждая позиция заказа принадлежит одному заказу
    order: "Order" = Relationship(back_populates="order_items")



