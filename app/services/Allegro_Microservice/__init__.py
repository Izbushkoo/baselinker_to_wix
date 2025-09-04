"""
 * @file: __init__.py
 * @description: Главный файл для экспорта всех интерфейсов микросервиса Allegro
 * @dependencies: Все endpoint файлы
 * @created: 2024-12-19
"""

from typing import Dict
from .base import BaseClient
from .offer_transfer_endpoint import OfferTransferClient
from .markets_endpoint import MarketsClient
from .monitoring_endpoint import MonitoringClient
from .templates_endpoint import TemplatesClient
from .offers_endpoint import AllegroOffersMicroserviceClient
from .orders_endpoint import OrdersClient
from .sync_endpoint import SyncClient
from .tokens_endpoint import AllegroTokenMicroserviceClient

# Экспорт всех клиентов
__all__ = [
    "BaseClient",
    "OfferTransferClient",
    "MarketsClient", 
    "MonitoringClient",
    "TemplatesClient",
    "AllegroOffersMicroserviceClient",
    "OrdersClient",
    "SyncClient",
    "AllegroTokenMicroserviceClient"
]

# Создание фабрики клиентов для удобства использования
class AllegroMicroserviceFactory:
    """Фабрика для создания клиентов микросервиса Allegro"""
    
    def __init__(self, jwt_token: str, base_url: str = None):
        self.jwt_token = jwt_token
        self.base_url = base_url
    
    def create_offer_transfer_client(self) -> OfferTransferClient:
        """Создать клиент для переноса офферов"""
        return OfferTransferClient(self.jwt_token, base_url=self.base_url)
    
    def create_markets_client(self) -> MarketsClient:
        """Создать клиент для работы с рынками"""
        return MarketsClient(self.jwt_token, base_url=self.base_url)
    
    def create_monitoring_client(self) -> MonitoringClient:
        """Создать клиент для мониторинга"""
        return MonitoringClient(self.jwt_token, base_url=self.base_url)
    
    def create_templates_client(self) -> TemplatesClient:
        """Создать клиент для работы с шаблонами"""
        return TemplatesClient(self.jwt_token, base_url=self.base_url)
    
    def create_offers_client(self) -> AllegroOffersMicroserviceClient:
        """Создать клиент для работы с офферами"""
        return AllegroOffersMicroserviceClient(self.jwt_token, base_url=self.base_url)
    
    def create_orders_client(self) -> OrdersClient:
        """Создать клиент для работы с заказами"""
        return OrdersClient(self.jwt_token, base_url=self.base_url)
    
    def create_sync_client(self) -> SyncClient:
        """Создать клиент для синхронизации"""
        return SyncClient(self.jwt_token, base_url=self.base_url)
    
    def create_tokens_client(self) -> AllegroTokenMicroserviceClient:
        """Создать клиент для работы с токенами"""
        return AllegroTokenMicroserviceClient(self.jwt_token, base_url=self.base_url)
    
    def create_all_clients(self) -> Dict[str, BaseClient]:
        """Создать все доступные клиенты"""
        return {
            "offer_transfer": self.create_offer_transfer_client(),
            "markets": self.create_markets_client(),
            "monitoring": self.create_monitoring_client(),
            "templates": self.create_templates_client(),
            "offers": self.create_offers_client(),
            "orders": self.create_orders_client(),
            "sync": self.create_sync_client(),
            "tokens": self.create_tokens_client()
        }


# Удобные функции для быстрого создания клиентов
def create_offer_transfer_client(jwt_token: str, base_url: str = None) -> OfferTransferClient:
    """Быстро создать клиент для переноса офферов"""
    return OfferTransferClient(jwt_token, base_url)


def create_markets_client(jwt_token: str, base_url: str = None) -> MarketsClient:
    """Быстро создать клиент для работы с рынками"""
    return MarketsClient(jwt_token, base_url)


def create_monitoring_client(jwt_token: str, base_url: str = None) -> MonitoringClient:
    """Быстро создать клиент для мониторинга"""
    return MonitoringClient(jwt_token, base_url)


def create_templates_client(jwt_token: str, base_url: str = None) -> TemplatesClient:
    """Быстро создать клиент для работы с шаблонами"""
    return TemplatesClient(jwt_token, base_url)


def create_factory(jwt_token: str, base_url: str = None) -> AllegroMicroserviceFactory:
    """Создать фабрику клиентов"""
    return AllegroMicroserviceFactory(jwt_token, base_url)
