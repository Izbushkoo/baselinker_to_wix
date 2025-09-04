"""
 * @file: offer_transfer_endpoint.py
 * @description: Интерфейс для работы с микросервисом переноса офферов Allegro
 * @dependencies: base.py, models.py, requests
 * @created: 2024-12-19
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from .base import BaseClient
from .models import (
    OfferTransferRequest,
    OfferTransferResponse,
    MultipleOffersTransferResponse,
    CompareOffersRequest,
    CompareOffersResponse,
    StartTransferRequest,
    TransferSessionResponse,
    StatusResponse,
    MarketPricingRule,
    TransferTemplate,
    TransferMetrics
)


class OfferTransferClient(BaseClient):
    """Клиент для работы с микросервисом переноса офферов"""
    
    def __init__(self, jwt_token: str, base_url: str = None, timeout: Optional[int] = 30):
        super().__init__(jwt_token, base_url, timeout)
        self.endpoint = f"{self.base_url}/api/v1/offer-transfer"
    
    async def test_transfer(
        self, 
        user_id: int, 
        offer_id: str, 
        source_token_id: int, 
        target_token_id: int
    ) -> OfferTransferResponse:
        """
        Тестовый перенос оффера между аккаунтами.
        
        Args:
            user_id: ID пользователя
            offer_id: ID оффера для переноса
            source_token_id: ID токена исходного аккаунта
            target_token_id: ID токена целевого аккаунта
            
        Returns:
            OfferTransferResponse: Результат переноса
        """
        url = f"{self.endpoint}/test-transfer"
        payload = {
            "user_id": user_id,
            "offer_id": offer_id,
            "source_token_id": source_token_id,
            "target_token_id": target_token_id
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return OfferTransferResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при тестовом переносе оффера: {str(e)}")
    
    async def transfer_offer(
        self, 
        offer_id: str, 
        source_token_id: int, 
        target_token_id: int,
        pricing_rules: Optional[Dict[str, MarketPricingRule]] = None
    ) -> OfferTransferResponse:
        """
        Перенос оффера между аккаунтами.
        
        Args:
            offer_id: ID оффера для переноса
            source_token_id: ID токена исходного аккаунта
            target_token_id: ID токена целевого аккаунта
            pricing_rules: Правила ценообразования
            
        Returns:
            OfferTransferResponse: Результат переноса
        """
        url = f"{self.endpoint}/transfer"
        payload = {
            "offer_id": offer_id,
            "source_token_id": source_token_id,
            "target_token_id": target_token_id
        }
        
        if pricing_rules:
            payload["pricing_rules"] = pricing_rules
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return OfferTransferResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при переносе оффера: {str(e)}")
    
    async def transfer_multiple_offers(
        self, 
        offer_ids: List[str], 
        source_token_id: int, 
        target_token_id: int,
        pricing_rules: Optional[Dict[str, MarketPricingRule]] = None
    ) -> MultipleOffersTransferResponse:
        """
        Массовый перенос офферов между аккаунтами.
        
        Args:
            offer_ids: Список ID офферов для переноса
            source_token_id: ID токена исходного аккаунта
            target_token_id: ID токена целевого аккаунта
            pricing_rules: Правила ценообразования
            
        Returns:
            MultipleOffersTransferResponse: Результаты массового переноса
        """
        url = f"{self.endpoint}/transfer-multiple"
        payload = {
            "offer_ids": offer_ids,
            "source_token_id": source_token_id,
            "target_token_id": target_token_id
        }
        
        if pricing_rules:
            payload["pricing_rules"] = pricing_rules
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return MultipleOffersTransferResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при массовом переносе офферов: {str(e)}")
    
    async def compare_offers(
        self, 
        source_token_id: int, 
        target_token_id: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> CompareOffersResponse:
        """
        Сравнить офферы между аккаунтами.
        
        Args:
            source_token_id: ID токена исходного аккаунта
            target_token_id: ID токена целевого аккаунта
            filters: Фильтры для офферов
            
        Returns:
            CompareOffersResponse: Результат сравнения
        """
        url = f"{self.endpoint}/compare-offers"
        payload = {
            "source_token_id": source_token_id,
            "target_token_id": target_token_id
        }
        
        if filters:
            payload["filters"] = filters
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            # Детальное логирование сырого ответа от микросервиса
            raw_response = response.json()
            print(f"=== СЫРОЙ ОТВЕТ ОТ МИКРОСЕРВИСА compare_offers ===")
            print(f"URL: {url}")
            print(f"Payload: {payload}")
            print(f"Status Code: {response.status_code}")
            print(f"Raw Response: {raw_response}")
            
            # Логируем структуру available_offers если есть
            if 'available_offers' in raw_response and raw_response['available_offers']:
                print(f"Количество офферов в сыром ответе: {len(raw_response['available_offers'])}")
                if len(raw_response['available_offers']) > 0:
                    first_raw_offer = raw_response['available_offers'][0]
                    print(f"Первый оффер в сыром ответе: {first_raw_offer}")
                    print(f"Тип первого оффера: {type(first_raw_offer)}")
                    if isinstance(first_raw_offer, dict):
                        print(f"Ключи первого оффера: {list(first_raw_offer.keys())}")
                        for key, value in first_raw_offer.items():
                            print(f"  {key}: {value} (тип: {type(value)})")
            
            return CompareOffersResponse(**raw_response)
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при сравнении офферов: {str(e)}")
        except Exception as e:
            print(f"=== ОШИБКА ПРИ ОБРАБОТКЕ ОТВЕТА ===")
            print(f"Тип ошибки: {type(e)}")
            print(f"Ошибка: {e}")
            if hasattr(e, '__dict__'):
                print(f"Детали ошибки: {e.__dict__}")
            raise
    
    async def start_transfer_session(
        self, 
        offer_ids: List[str], 
        source_token_id: int, 
        target_token_id: int,
        markets: List[str],
        pricing_rules: Dict[str, MarketPricingRule],
        excluded_offer_ids: Optional[List[str]] = None,
        template_name: Optional[str] = None
    ) -> TransferSessionResponse:
        """
        Запустить сессию переноса офферов.
        
        Args:
            offer_ids: Список ID офферов для переноса
            source_token_id: ID токена исходного аккаунта
            target_token_id: ID токена целевого аккаунта
            markets: Целевые рынки
            pricing_rules: Правила ценообразования
            excluded_offer_ids: ID офферов для исключения
            template_name: Название использованного шаблона
            
        Returns:
            TransferSessionResponse: Информация о сессии
        """
        url = f"{self.endpoint}/start"
        payload = {
            "offer_ids": offer_ids,
            "source_token_id": source_token_id,
            "target_token_id": target_token_id,
            "markets": markets,
            "pricing_rules": pricing_rules
        }
        
        if excluded_offer_ids:
            payload["excluded_offer_ids"] = excluded_offer_ids
        if template_name:
            payload["template_name"] = template_name
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferSessionResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при запуске сессии переноса: {str(e)}")
    
    async def get_transfer_session_status(self, session_id: str) -> TransferSessionResponse:
        """
        Получить статус сессии переноса.
        
        Args:
            session_id: ID сессии
            
        Returns:
            TransferSessionResponse: Статус сессии
        """
        url = f"{self.endpoint}/session/{session_id}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferSessionResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении статуса сессии: {str(e)}")
    
    async def pause_transfer_session(self, session_id: str) -> StatusResponse:
        """
        Приостановить сессию переноса.
        
        Args:
            session_id: ID сессии
            
        Returns:
            StatusResponse: Результат операции
        """
        url = f"{self.endpoint}/session/{session_id}/pause"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при приостановке сессии: {str(e)}")
    
    async def resume_transfer_session(self, session_id: str) -> StatusResponse:
        """
        Возобновить сессию переноса.
        
        Args:
            session_id: ID сессии
            
        Returns:
            StatusResponse: Результат операции
        """
        url = f"{self.endpoint}/session/{session_id}/resume"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при возобновлении сессии: {str(e)}")
    
    async def cancel_transfer_session(self, session_id: str) -> StatusResponse:
        """
        Отменить сессию переноса.
        
        Args:
            session_id: ID сессии
            
        Returns:
            StatusResponse: Результат операции
        """
        url = f"{self.endpoint}/session/{session_id}"
        
        try:
            response = requests.delete(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при отмене сессии: {str(e)}")
    
    async def get_user_templates(self) -> List[TransferTemplate]:
        """
        Получить шаблоны пользователя.
        
        Returns:
            List[TransferTemplate]: Список шаблонов
        """
        url = f"{self.endpoint}/templates"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            templates_data = response.json()
            return [TransferTemplate(**template) for template in templates_data]
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении шаблонов: {str(e)}")
    
    async def create_template(
        self, 
        name: str, 
        markets: List[str], 
        pricing_rules: Dict[str, MarketPricingRule],
        description: Optional[str] = None,
        filter_settings: Optional[Dict[str, Any]] = None,
        transfer_settings: Optional[Dict[str, Any]] = None
    ) -> TransferTemplate:
        """
        Создать новый шаблон.
        
        Args:
            name: Название шаблона
            markets: Целевые рынки
            pricing_rules: Правила ценообразования
            description: Описание шаблона
            filter_settings: Настройки фильтрации
            transfer_settings: Настройки переноса
            
        Returns:
            TransferTemplate: Созданный шаблон
        """
        url = f"{self.endpoint}/templates"
        payload = {
            "name": name,
            "markets": markets,
            "pricing_rules": pricing_rules
        }
        
        if description:
            payload["description"] = description
        if filter_settings:
            payload["filter_settings"] = filter_settings
        if transfer_settings:
            payload["transfer_settings"] = transfer_settings
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при создании шаблона: {str(e)}")
    
    async def apply_template(self, template_id: int) -> Dict[str, Any]:
        """
        Применить шаблон.
        
        Args:
            template_id: ID шаблона
            
        Returns:
            Dict[str, Any]: Конфигурация шаблона
        """
        url = f"{self.endpoint}/templates/{template_id}/apply"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при применении шаблона: {str(e)}")
    
    async def get_transfer_metrics(self, days: int = 30) -> TransferMetrics:
        """
        Получить метрики переноса офферов.
        
        Args:
            days: Количество дней для анализа
            
        Returns:
            TransferMetrics: Метрики системы
        """
        url = f"{self.endpoint}/metrics"
        params = {"days": days}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferMetrics(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении метрик: {str(e)}")
    
    async def get_system_health(self) -> Dict[str, Any]:
        """
        Получить состояние системы.
        
        Returns:
            Dict[str, Any]: Состояние системы
        """
        url = f"{self.endpoint}/monitoring/health"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении состояния системы: {str(e)}")
    
    async def get_current_metrics(self) -> Dict[str, Any]:
        """
        Получить текущие метрики системы.
        
        Returns:
            Dict[str, Any]: Текущие метрики
        """
        url = f"{self.endpoint}/monitoring/metrics"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении метрик: {str(e)}")
    
    async def get_available_markets(self) -> List[Dict[str, Any]]:
        """
        Получить список доступных рынков.
        
        Returns:
            List[Dict[str, Any]]: Список рынков
        """
        url = f"{self.endpoint}/markets"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            markets_data = response.json()
            return markets_data.get("markets", [])
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении списка рынков: {str(e)}")
    
    async def get_currency_rates(self, force_refresh: bool = False) -> Dict[str, float]:
        """
        Получить курсы валют.
        
        Args:
            force_refresh: Принудительно обновить кэш
            
        Returns:
            Dict[str, float]: Курсы валют
        """
        url = f"{self.endpoint}/markets/currency-rates"
        params = {"force_refresh": force_refresh}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            rates_data = response.json()
            return rates_data.get("rates", {})
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при получении курсов валют: {str(e)}")
    
    async def preview_pricing(
        self, 
        offers: List[Dict[str, Any]], 
        markets: List[str], 
        pricing_rules: Dict[str, MarketPricingRule]
    ) -> List[Dict[str, Any]]:
        """
        Предварительный расчет цен.
        
        Args:
            offers: Список офферов
            markets: Целевые рынки
            pricing_rules: Правила ценообразования
            
        Returns:
            List[Dict[str, Any]]: Предварительные расчеты
        """
        url = f"{self.endpoint}/markets/pricing/preview"
        payload = {
            "offers": offers,
            "markets": markets,
            "pricing_rules": pricing_rules
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            preview_data = response.json()
            return preview_data.get("previews", [])
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка при расчете цен: {str(e)}")
