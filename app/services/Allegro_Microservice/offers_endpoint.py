import requests
from typing import Optional, List, Dict, Any
from uuid import UUID
from app.services.Allegro_Microservice.base import BaseClient
from app.services.Allegro_Microservice.models import OfferListResponse, MicroserviceOfferResponse
from app.models.offer import ExternalStockUpdateRequest


class AllegroOffersMicroserviceClient(BaseClient):
    """
    Клиент для работы с API управления офферами Allegro.
    """
    
    def __init__(self, jwt_token: str, **kwargs):
        super().__init__(jwt_token, **kwargs)
        self.prefix = "/api/v1/offers"
        self.base_url += self.prefix

    def get_offers_by_external_id(
        self,
        token_ids: List[UUID],
        external_id: str
    ) -> OfferListResponse:
        """
        Получить все офферы с указанным external_id для выбранных токенов.
        
        Args:
            token_ids: Список ID токенов для доступа к Allegro API
            external_id: External ID для поиска офферов
            
        Returns:
            List[Dict]: Список результатов с офферами для каждого токена
        """
        url = f"{self.base_url}/by-external-id"
        
        # Преобразуем UUID в строки для параметров запроса
        token_id_strings = [str(token_id) for token_id in token_ids]
        
        params = {
            "token_ids": token_id_strings,
            "external_id": external_id
        }
        
        response = requests.get(
            url, 
            params=params, 
            headers=self.headers, 
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return OfferListResponse(offers=data, total_count=len(data) if isinstance(data, list) else None)

    def update_stock(
        self,
        external_id: str,
        stock: int,
        token_ids: Optional[List[UUID]] = None
    ) -> OfferListResponse:
        """
        Обновить запас офферов для указанных токенов пользователя.
        
        Args:
            external_id: External ID оферт для обновления
            stock: Новый запас
            token_ids: Список ID токенов (если не указан - для всех токенов)
            
        Returns:
            List[Dict]: Список результатов обновления для каждого токена
        """
        url = f"{self.base_url}/update-stock"
        
        # Подготавливаем тело запроса
        body = ExternalStockUpdateRequest(
            external_id=external_id,
            stock=stock
        )
        
        # Подготавливаем параметры запроса
        params = {}
        if token_ids:
            # Преобразуем UUID в строки для параметров запроса
            token_id_strings = [str(token_id) for token_id in token_ids]
            params["token_ids"] = token_id_strings
        
        response = requests.post(
            url,
            json=body.dict(),
            params=params if params else None,
            headers=self.headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return OfferListResponse(offers=data, total_count=len(data) if isinstance(data, list) else None)

    def get_offers_by_token(
        self,
        token_id: UUID,
        external_ids: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> OfferListResponse:
        """
        Получить оферты для конкретного токена (дополнительный метод).
        
        Args:
            token_id: ID токена
            external_ids: Список external_id для фильтрации (опционально)
            limit: Лимит количества оферт
            offset: Смещение для пагинации
            
        Returns:
            Dict: Результат с офферами
        """
        url = f"{self.base_url}/token/{token_id}"
        
        params = {
            "limit": limit,
            "offset": offset
        }
        
        if external_ids:
            params["external_ids"] = external_ids
        
        response = requests.get(
            url,
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return OfferListResponse(offers=data, total_count=len(data) if isinstance(data, list) else None)

    def get_offer_details(
        self,
        token_id: UUID,
        offer_id: str
    ) -> MicroserviceOfferResponse:
        """
        Получить детальную информацию об оффере.
        
        Args:
            token_id: ID токена
            offer_id: ID оффера
            
        Returns:
            Dict: Детальная информация об оффере
        """
        url = f"{self.base_url}/token/{token_id}/offer/{offer_id}"
        
        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return MicroserviceOfferResponse(offer=data)

    def update_offer_stock(
        self,
        token_id: UUID,
        offer_id: str,
        stock: int
    ) -> MicroserviceOfferResponse:
        """
        Обновить запас конкретного оффера.
        
        Args:
            token_id: ID токена
            offer_id: ID оффера
            stock: Новый запас
            
        Returns:
            Dict: Результат обновления
        """
        url = f"{self.base_url}/token/{token_id}/offer/{offer_id}/stock"
        
        payload = {"stock": stock}
        
        response = requests.put(
            url,
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return MicroserviceOfferResponse(offer=data)

    def update_offer_price(
        self,
        token_id: UUID,
        offer_id: str,
        price: float,
        currency: str = "PLN"
    ) -> MicroserviceOfferResponse:
        """
        Обновить цену конкретного оффера.
        
        Args:
            token_id: ID токена
            offer_id: ID оффера
            price: Новая цена
            currency: Валюта (по умолчанию PLN)
            
        Returns:
            Dict: Результат обновления
        """
        url = f"{self.base_url}/token/{token_id}/offer/{offer_id}/price"
        
        payload = {
            "price": price,
            "currency": currency
        }
        
        response = requests.put(
            url,
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return MicroserviceOfferResponse(offer=data)