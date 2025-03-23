from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.allegro.allegro_api_service import (
    AsyncAllegroApiService,
    SyncAllegroApiService,
    BaseAllegroApiService
)
from app.data_access.allegro_order_repository import AllegroOrderRepository

class BaseAllegroOrderService:
    def __init__(self, repository: AllegroOrderRepository):
        self.repository = repository

class SyncAllegroOrderService(BaseAllegroOrderService):
    def __init__(
        self,
        session: Session,
        api_service: Optional[SyncAllegroApiService] = None
    ):
        self.session = session
        self.api_service = api_service or SyncAllegroApiService()
        super().__init__(AllegroOrderRepository(session))

    def sync_orders(
        self,
        token: str,
        status: Optional[str] = None,
        fulfillment_status: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[str]:
        """
        Синхронная версия синхронизации заказов из Allegro с локальной базой данных.
        """
        # Получаем заказы из API
        orders_data = self.api_service.get_orders(
            token=token,
            status=status,
            fulfillment_status=fulfillment_status,
            bought_at_gte=from_date,
            bought_at_lte=to_date,
            sort="-lineItems.boughtAt"
        )

        synced_orders = []
        for order_data in orders_data.get("checkoutForms", []):
            # Получаем детали заказа
            order_details = self.api_service.get_order_details(
                token=token,
                order_id=order_data["id"]
            )
            
            # Проверяем существование заказа
            existing_order = self.repository.get_order_by_id(order_data["id"])
            
            if existing_order:
                # Обновляем существующий заказ
                self.repository.update_order(order_data["id"], order_details)
            else:
                # Создаем новый заказ
                self.repository.add_order(order_details)
            
            synced_orders.append(order_data["id"])

        return synced_orders

    def get_order_with_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Синхронная версия получения заказа с деталями."""
        return self.repository.get_order_by_id(order_id)

    def update_order_status(
        self,
        order_id: str,
        token: str,
        new_status: str
    ) -> Optional[Dict[str, Any]]:
        """Синхронная версия обновления статуса заказа."""
        # Получаем актуальные данные заказа из API
        order_details = self.api_service.get_order_details(token, order_id)
        
        if not order_details:
            return None

        # Обновляем статус
        order_details["status"] = new_status
        
        # Обновляем заказ в базе данных
        return self.repository.update_order(order_id, order_details)

class AsyncAllegroOrderService(BaseAllegroOrderService):
    def __init__(
        self,
        session: AsyncSession,
        api_service: Optional[AsyncAllegroApiService] = None
    ):
        self.session = session
        self.api_service = api_service or AsyncAllegroApiService()
        super().__init__(AllegroOrderRepository(session))

    async def sync_orders(
        self,
        token: str,
        status: Optional[str] = None,
        fulfillment_status: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[str]:
        """
        Асинхронная версия синхронизации заказов из Allegro с локальной базой данных.
        """
        # Получаем заказы из API
        orders_data = await self.api_service.get_orders(
            token=token,
            status=status,
            fulfillment_status=fulfillment_status,
            bought_at_gte=from_date,
            bought_at_lte=to_date,
            sort="-lineItems.boughtAt"
        )

        synced_orders = []
        for order_data in orders_data.get("checkoutForms", []):
            # Получаем детали заказа
            order_details = await self.api_service.get_order_details(
                token=token,
                order_id=order_data["id"]
            )
            
            # Проверяем существование заказа
            existing_order = await self.repository.get_order_by_id(order_data["id"])
            
            if existing_order:
                # Обновляем существующий заказ
                await self.repository.update_order(order_data["id"], order_details)
            else:
                # Создаем новый заказ
                await self.repository.add_order(order_details)
            
            synced_orders.append(order_data["id"])

        return synced_orders

    async def get_order_with_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Асинхронная версия получения заказа с деталями."""
        return await self.repository.get_order_by_id(order_id)

    async def update_order_status(
        self,
        order_id: str,
        token: str,
        new_status: str
    ) -> Optional[Dict[str, Any]]:
        """Асинхронная версия обновления статуса заказа."""
        # Получаем актуальные данные заказа из API
        order_details = await self.api_service.get_order_details(token, order_id)
        
        if not order_details:
            return None

        # Обновляем статус
        order_details["status"] = new_status
        
        # Обновляем заказ в базе данных
        return await self.repository.update_order(order_id, order_details)

# Примеры использования:
"""
# Синхронное использование
def sync_example():
    with Session(engine) as session:
        service = SyncAllegroOrderService(session)
        
        # Синхронизация заказов за последние 24 часа
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        
        synced_orders = service.sync_orders(
            token="your_token",
            status="READY_FOR_PROCESSING",
            from_date=yesterday,
            to_date=now
        )
        
        # Получение деталей заказа
        order = service.get_order_with_details("example-order-id")
        
        # Обновление статуса заказа
        updated_order = service.update_order_status(
            "example-order-id",
            "your_token",
            "PROCESSING"
        )

# Асинхронное использование
async def async_example():
    async with AsyncSession(engine) as session:
        service = AsyncAllegroOrderService(session)
        
        # Синхронизация заказов за последние 24 часа
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        
        synced_orders = await service.sync_orders(
            token="your_token",
            status="READY_FOR_PROCESSING",
            from_date=yesterday,
            to_date=now
        )
        
        # Получение деталей заказа
        order = await service.get_order_with_details("example-order-id")
        
        # Обновление статуса заказа
        updated_order = await service.update_order_status(
            "example-order-id",
            "your_token",
            "PROCESSING"
        )
""" 