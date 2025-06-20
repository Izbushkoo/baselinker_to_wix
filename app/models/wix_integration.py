"""
 * @file: wix_integration.py
 * @description: Модели для интеграции с Wix API и управления аккаунтами
 * @dependencies: SQLModel, datetime, enum
 * @created: 2024-03-21
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
from sqlmodel import SQLModel, Field, Relationship, select
from sqlmodel import Session


class SyncType(str, Enum):
    """Типы синхронизации"""
    UPDATE = "update"
    CREATE = "create"
    DELETE = "delete"
    VERIFY = "verify"


class SyncStatus(str, Enum):
    """Статусы синхронизации"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class MarketplaceType(str, Enum):
    """Типы маркетплейсов"""
    WIX = "wix"
    ALLEGRO = "allegro"
    AMAZON = "amazon"
    EBAY = "ebay"


class WixAccount(SQLModel, table=True):
    """Модель аккаунта Wix"""
    __tablename__ = "wix_accounts"
    
    id: int = Field(primary_key=True)
    name: str = Field(description="Название аккаунта")
    api_key: str = Field(description="API ключ Wix")
    site_id: str = Field(description="ID сайта Wix")
    account_id: str = Field(description="ID аккаунта Wix")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Связи
    inventory_syncs: List["WixInventorySync"] = Relationship(back_populates="wix_account")
    products: List["WixProductMapping"] = Relationship(back_populates="wix_account")


class WixProductMapping(SQLModel, table=True):
    """Модель связи товаров с Wix"""
    __tablename__ = "wix_product_mappings"
    
    id: int = Field(primary_key=True)
    wix_account_id: int = Field(foreign_key="wix_accounts.id")
    product_sku: str = Field(foreign_key="product.sku")
    wix_product_id: str = Field(description="ID товара в Wix")
    wix_inventory_item_id: str = Field(description="ID элемента инвентаря в Wix")
    wix_variant_id: Optional[str] = Field(default=None, description="ID варианта товара")
    is_active: bool = Field(default=True)
    last_sync_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Связи
    wix_account: WixAccount = Relationship(back_populates="products")


class WixInventorySync(SQLModel, table=True):
    """Модель истории синхронизации с Wix"""
    __tablename__ = "wix_inventory_syncs"
    
    id: int = Field(primary_key=True)
    wix_account_id: int = Field(foreign_key="wix_accounts.id")
    product_sku: str = Field(foreign_key="product.sku")
    sync_type: SyncType = Field(description="Тип синхронизации")
    local_quantity: int = Field(description="Количество в локальной базе")
    wix_quantity: int = Field(description="Количество в Wix до синхронизации")
    new_wix_quantity: int = Field(description="Количество в Wix после синхронизации")
    status: SyncStatus = Field(default=SyncStatus.PENDING)
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Связи
    wix_account: WixAccount = Relationship(back_populates="inventory_syncs")


class MarketplaceAccount(SQLModel, table=True):
    """Базовая модель для аккаунтов маркетплейсов"""
    __tablename__ = "marketplace_accounts"
    
    id: int = Field(primary_key=True)
    name: str = Field(description="Название аккаунта")
    marketplace_type: MarketplaceType = Field(description="Тип маркетплейса")
    credentials: Dict = Field(description="Креденшиалы в JSON формате")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow) 