"""
 * @file: product_allegro_sync_service.py
 * @description: Сервис для работы с настройками синхронизации товаров с Allegro
 * @dependencies: SQLModel, ProductAllegroSyncSettings, AllegroToken, Product
 * @created: 2024-12-19
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.product_allegro_sync_settings import ProductAllegroSyncSettings
from app.models.allegro_token import AllegroToken
from app.models.warehouse import Product


class ProductAllegroSyncService:
    """
    Сервис для работы с настройками синхронизации товаров с Allegro.
    Инкапсулирует логику работы с моделью ProductAllegroSyncSettings.
    """

    def __init__(self, session: Session | AsyncSession):
        """
        Инициализация сервиса.
        
        Args:
            session: Сессия базы данных (синхронная или асинхронная)
        """
        self.session = session
        self.is_async = isinstance(session, AsyncSession)

    async def get_product_sync_settings(self, product_sku: str) -> List[ProductAllegroSyncSettings]:
        """
        Получить все настройки синхронизации для товара.
        
        Args:
            product_sku: SKU товара
            
        Returns:
            Список настроек синхронизации для всех аккаунтов
        """
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.product_sku == product_sku
        )
        
        if self.is_async:
            result = await self.session.exec(query)
        else:
            result = self.session.exec(query)
            
        return result.all()

    async def get_account_sync_settings(
        self, 
        product_sku: str, 
        account_name: str
    ) -> Optional[ProductAllegroSyncSettings]:
        """
        Получить настройки синхронизации для конкретного товара и аккаунта.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            
        Returns:
            Настройки синхронизации или None, если не найдены
        """
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.product_sku == product_sku,
            ProductAllegroSyncSettings.allegro_account_name == account_name
        )
        
        if self.is_async:
            result = await self.session.exec(query)
        else:
            result = self.session.exec(query)
            
        return result.first()

    async def create_or_update_sync_settings(
        self,
        product_sku: str,
        account_name: str,
        stock_sync_enabled: bool = True,
        price_sync_enabled: bool = False,
        price_multiplier: Decimal = Decimal("1.0")
    ) -> ProductAllegroSyncSettings:
        """
        Создать или обновить настройки синхронизации.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            stock_sync_enabled: Включена ли синхронизация остатков
            price_sync_enabled: Включена ли синхронизация цен
            price_multiplier: Мультипликатор цены
            
        Returns:
            Созданные или обновленные настройки
        """
        # Проверяем существующие настройки
        existing_settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if existing_settings:
            # Обновляем существующие настройки
            existing_settings.stock_sync_enabled = stock_sync_enabled
            existing_settings.price_sync_enabled = price_sync_enabled
            existing_settings.price_multiplier = price_multiplier
            existing_settings.updated_at = datetime.utcnow()
            
            if self.is_async:
                await self.session.commit()
                await self.session.refresh(existing_settings)
            else:
                self.session.commit()
                self.session.refresh(existing_settings)
                
            return existing_settings
        else:
            # Создаем новые настройки
            new_settings = ProductAllegroSyncSettings(
                product_sku=product_sku,
                allegro_account_name=account_name,
                stock_sync_enabled=stock_sync_enabled,
                price_sync_enabled=price_sync_enabled,
                price_multiplier=price_multiplier
            )
            
            self.session.add(new_settings)
            
            if self.is_async:
                await self.session.commit()
                await self.session.refresh(new_settings)
            else:
                self.session.commit()
                self.session.refresh(new_settings)
                
            return new_settings

    async def toggle_stock_sync(self, product_sku: str, account_name: str) -> bool:
        """
        Переключить синхронизацию остатков для товара и аккаунта.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            
        Returns:
            Новое состояние синхронизации остатков
        """
        settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if settings:
            settings.stock_sync_enabled = not settings.stock_sync_enabled
            settings.updated_at = datetime.utcnow()
            new_status = settings.stock_sync_enabled
        else:
            # Создаем новые настройки с включенной синхронизацией остатков
            settings = await self.create_or_update_sync_settings(
                product_sku=product_sku,
                account_name=account_name,
                stock_sync_enabled=True,
                price_sync_enabled=False,
                price_multiplier=Decimal("1.0")
            )
            new_status = True
            
        if self.is_async:
            await self.session.commit()
        else:
            self.session.commit()
            
        return new_status

    async def toggle_price_sync(self, product_sku: str, account_name: str) -> bool:
        """
        Переключить синхронизацию цен для товара и аккаунта.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            
        Returns:
            Новое состояние синхронизации цен
        """
        settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if settings:
            settings.price_sync_enabled = not settings.price_sync_enabled
            settings.updated_at = datetime.utcnow()
            new_status = settings.price_sync_enabled
        else:
            # Создаем новые настройки с включенной синхронизацией цен
            settings = await self.create_or_update_sync_settings(
                product_sku=product_sku,
                account_name=account_name,
                stock_sync_enabled=True,
                price_sync_enabled=True,
                price_multiplier=Decimal("1.0")
            )
            new_status = True
            
        if self.is_async:
            await self.session.commit()
        else:
            self.session.commit()
            
        return new_status

    async def update_price_multiplier(
        self, 
        product_sku: str, 
        account_name: str, 
        multiplier: Decimal
    ) -> ProductAllegroSyncSettings:
        """
        Обновить мультипликатор цены для товара и аккаунта.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            multiplier: Новый мультипликатор цены
            
        Returns:
            Обновленные настройки синхронизации
        """
        settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if settings:
            settings.price_multiplier = multiplier
            settings.updated_at = datetime.utcnow()
        else:
            # Создаем новые настройки с указанным мультипликатором
            settings = await self.create_or_update_sync_settings(
                product_sku=product_sku,
                account_name=account_name,
                stock_sync_enabled=True,
                price_sync_enabled=False,
                price_multiplier=multiplier
            )
            
        if self.is_async:
            await self.session.commit()
            await self.session.refresh(settings)
        else:
            self.session.commit()
            self.session.refresh(settings)
            
        return settings

    async def get_products_for_stock_sync(self, account_name: str) -> List[ProductAllegroSyncSettings]:
        """
        Получить все товары с включенной синхронизацией остатков для аккаунта.
        
        Args:
            account_name: Название аккаунта Allegro
            
        Returns:
            Список товаров с включенной синхронизацией остатков
        """
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.allegro_account_name == account_name,
            ProductAllegroSyncSettings.stock_sync_enabled == True
        )
        
        if self.is_async:
            result = await self.session.exec(query)
        else:
            result = self.session.exec(query)
            
        return result.all()

    def get_products_for_stock_sync_sync(self, account_name: str) -> List[ProductAllegroSyncSettings]:
        """
        Синхронная версия метода get_products_for_stock_sync для использования в Celery задачах.
        
        Args:
            account_name: Название аккаунта Allegro
            
        Returns:
            Список товаров с включенной синхронизацией остатков
        """
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.allegro_account_name == account_name,
            ProductAllegroSyncSettings.stock_sync_enabled == True
        )
        
        result = self.session.exec(query)
        return result.all()

    async def get_products_for_price_sync(self, account_name: str) -> List[ProductAllegroSyncSettings]:
        """
        Получить все товары с включенной синхронизацией цен для аккаунта.
        
        Args:
            account_name: Название аккаунта Allegro
            
        Returns:
            Список товаров с включенной синхронизацией цен
        """
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.allegro_account_name == account_name,
            ProductAllegroSyncSettings.price_sync_enabled == True
        )
        
        if self.is_async:
            result = await self.session.exec(query)
        else:
            result = self.session.exec(query)
            
        return result.all()

    async def update_last_sync_time(
        self, 
        product_sku: str, 
        account_name: str, 
        sync_type: str = "stock"
    ) -> None:
        """
        Обновить время последней синхронизации.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            sync_type: Тип синхронизации ("stock" или "price")
        """
        settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if settings:
            current_time = datetime.utcnow()
            
            if sync_type == "stock":
                settings.last_stock_sync_at = current_time
            elif sync_type == "price":
                settings.last_price_sync_at = current_time
                
            settings.updated_at = current_time
            
            if self.is_async:
                await self.session.commit()
            else:
                self.session.commit()

    async def should_sync_product(
        self, 
        product_sku: str, 
        account_name: str, 
        sync_type: str = "stock"
    ) -> bool:
        """
        Проверить, нужно ли синхронизировать товар с аккаунтом.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            sync_type: Тип синхронизации ("stock" или "price")
            
        Returns:
            True, если синхронизация включена, False - иначе
        """
        settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if not settings:
            # Если настроек нет, по умолчанию синхронизация отключена
            return False
        
        if sync_type == "stock":
            return settings.stock_sync_enabled
        elif sync_type == "price":
            return settings.price_sync_enabled
        else:
            return False

    def should_sync_product_sync(
        self, 
        product_sku: str, 
        account_name: str, 
        sync_type: str = "stock"
    ) -> bool:
        """
        Синхронная версия метода should_sync_product для использования в Celery задачах.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            sync_type: Тип синхронизации ("stock" или "price")
            
        Returns:
            True, если синхронизация включена, False - иначе
        """
        # Получаем настройки синхронизации
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.product_sku == product_sku,
            ProductAllegroSyncSettings.allegro_account_name == account_name
        )
        
        result = self.session.exec(query)
        settings = result.first()
        
        if not settings:
            # Если настроек нет, по умолчанию синхронизация отключена
            return False
        
        if sync_type == "stock":
            return settings.stock_sync_enabled
        elif sync_type == "price":
            return settings.price_sync_enabled
        else:
            return False

    async def get_price_multiplier(self, product_sku: str, account_name: str) -> Decimal:
        """
        Получить мультипликатор цены для товара и аккаунта.
        
        Args:
            product_sku: SKU товара
            account_name: Название аккаунта Allegro
            
        Returns:
            Мультипликатор цены (по умолчанию 1.0)
        """
        settings = await self.get_account_sync_settings(product_sku, account_name)
        
        if settings:
            return settings.price_multiplier
        else:
            return Decimal("1.0")

    async def get_all_account_settings(self, account_name: str) -> List[ProductAllegroSyncSettings]:
        """
        Получить все настройки синхронизации для аккаунта.
        
        Args:
            account_name: Название аккаунта Allegro
            
        Returns:
            Список всех настроек синхронизации для аккаунта
        """
        query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.allegro_account_name == account_name
        )
        
        if self.is_async:
            result = await self.session.exec(query)
        else:
            result = self.session.exec(query)
            
        return result.all()

    async def delete_account_settings(self, account_name: str) -> int:
        """
        Удалить все настройки синхронизации для аккаунта.
        Полезно при удалении аккаунта Allegro.
        
        Args:
            account_name: Название аккаунта Allegro
            
        Returns:
            Количество удаленных записей
        """
        settings_list = await self.get_all_account_settings(account_name)
        
        for settings in settings_list:
            if self.is_async:
                await self.session.delete(settings)
            else:
                self.session.delete(settings)
        
        if self.is_async:
            await self.session.commit()
        else:
            self.session.commit()
            
        return len(settings_list)

    async def delete_product_settings(self, product_sku: str) -> int:
        """
        Удалить все настройки синхронизации для товара.
        Полезно при удалении товара.
        
        Args:
            product_sku: SKU товара
            
        Returns:
            Количество удаленных записей
        """
        settings_list = await self.get_product_sync_settings(product_sku)
        
        for settings in settings_list:
            if self.is_async:
                await self.session.delete(settings)
            else:
                self.session.delete(settings)
        
        if self.is_async:
            await self.session.commit()
        else:
            self.session.commit()
            
        return len(settings_list)


# Функции-хелперы для создания сервиса
def get_sync_service(session: Session) -> ProductAllegroSyncService:
    """
    Создать сервис синхронизации для синхронной сессии.
    
    Args:
        session: Синхронная сессия базы данных
        
    Returns:
        Экземпляр сервиса синхронизации
    """
    return ProductAllegroSyncService(session)


def get_async_sync_service(session: AsyncSession) -> ProductAllegroSyncService:
    """
    Создать сервис синхронизации для асинхронной сессии.
    
    Args:
        session: Асинхронная сессия базы данных
        
    Returns:
        Экземпляр сервиса синхронизации
    """
    return ProductAllegroSyncService(session) 