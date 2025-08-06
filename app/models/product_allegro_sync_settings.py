"""
 * @file: product_allegro_sync_settings.py
 * @description: Модель для хранения глобальных настроек синхронизации товара с каждым аккаунтом Allegro
 * @dependencies: SQLModel, Product
 * @created: 2024-12-19
"""

from typing import Optional
from datetime import datetime
from decimal import Decimal
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import ForeignKey, Column, UniqueConstraint


class ProductAllegroSyncSettings(SQLModel, table=True):
    """
    Модель для хранения глобальных настроек синхронизации товара с конкретным аккаунтом Allegro.
    Настройки едины для всех пользователей системы:
    - Админы могут редактировать настройки
    - Обычные пользователи могут только просматривать
    Использует product_sku + account_name для идентификации, что позволит легко мигрировать
    в микросервисную архитектуру.
    """
    __tablename__ = "product_allegro_sync_settings"
    
    # Первичный ключ
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Внешний ключ на товар
    product_sku: str = Field(
        sa_column=Column(
            ForeignKey("product.sku", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False
        ),
        description="SKU товара"
    )
    
    # Идентификатор аккаунта Allegro (account_name из токена)
    allegro_account_name: str = Field(
        nullable=False,
        description="Название аккаунта Allegro (из токена, для идентификации)"
    )
    
    # Настройки синхронизации остатков
    stock_sync_enabled: bool = Field(
        default=False,
        description="Включена ли синхронизация остатков для этого аккаунта"
    )
    
    # Настройки синхронизации цен
    price_sync_enabled: bool = Field(
        default=False,
        description="Включена ли синхронизация цен для этого аккаунта"
    )
    
    # Мультипликатор цены для этого аккаунта
    price_multiplier: Decimal = Field(
        default=Decimal("1.0"),
        description="Мультипликатор цены для этого аккаунта (например, 1.2 для наценки 20%)"
    )
    
    # Метаданные
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Дата создания настроек"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Дата последнего обновления настроек"
    )
    
    # Дополнительные поля для отслеживания синхронизации
    last_stock_sync_at: Optional[datetime] = Field(
        default=None,
        description="Время последней синхронизации остатков"
    )
    last_price_sync_at: Optional[datetime] = Field(
        default=None,
        description="Время последней синхронизации цены"
    )
    
    # Связи с другими моделями
    product: Optional["Product"] = Relationship(
        back_populates="allegro_sync_settings"
    )
    
    # Уникальное ограничение для комбинации product_sku + allegro_account_name
    __table_args__ = (
        UniqueConstraint('product_sku', 'allegro_account_name', name='_product_account_uc'),
    )
    
    def __repr__(self) -> str:
        return f"<ProductAllegroSyncSettings(product_sku='{self.product_sku}', account='{self.allegro_account_name}', stock_sync={self.stock_sync_enabled}, price_sync={self.price_sync_enabled})>"
    
    @classmethod
    def get_by_account(cls, session, account_name: str, product_sku: str = None):
        """
        Получить настройки синхронизации по аккаунту.
        Если указан product_sku, то для конкретного товара.
        """
        from sqlmodel import select
        
        query = select(cls).where(cls.allegro_account_name == account_name)
        
        if product_sku:
            query = query.where(cls.product_sku == product_sku)
            
        return session.exec(query).first() if product_sku else session.exec(query).all()
    
    @classmethod
    def get_by_product(cls, session, product_sku: str):
        """
        Получить все настройки синхронизации для товара.
        """
        from sqlmodel import select
        
        query = select(cls).where(cls.product_sku == product_sku)
        return session.exec(query).all()
    
    @classmethod
    def get_enabled_for_stock_sync(cls, session, account_name: str):
        """
        Получить все товары с включенной синхронизацией остатков для аккаунта.
        """
        from sqlmodel import select
        
        query = select(cls).where(
            cls.allegro_account_name == account_name,
            cls.stock_sync_enabled == True
        )
        return session.exec(query).all()
    
    @classmethod
    def get_enabled_for_price_sync(cls, session, account_name: str):
        """
        Получить все товары с включенной синхронизацией цен для аккаунта.
        """
        from sqlmodel import select
        
        query = select(cls).where(
            cls.allegro_account_name == account_name,
            cls.price_sync_enabled == True
        )
        return session.exec(query).all() 