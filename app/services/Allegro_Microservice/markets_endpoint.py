"""
 * @file: markets_endpoint.py
 * @description: Интерфейс для работы с микросервисом рынков Allegro и ценообразования
 * @dependencies: base.py, models.py, requests
 * @created: 2024-12-19
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from .base import BaseClient
from .models import (
    MarketResponse,
    CurrencyRatesResponse,
    PricingPreviewRequest,
    PricingPreviewResponse,
    StatusResponse,
    MarketInfo,
    MarketPricingRule
)


class MarketsClient(BaseClient):
    """Клиент для работы с микросервисом рынков и ценообразования"""
    
    def __init__(self, jwt_token: str, base_url: str = None, timeout: Optional[int] = 30):
        super().__init__(jwt_token, base_url, timeout)
        self.endpoint = f"{self.base_url}/api/v1/markets"
    
    async def get_available_markets(self) -> MarketResponse:
        """
        Получить список доступных рынков Allegro.
        
        Возвращает информацию о всех поддерживаемых рынках:
        - Польша (PL) - PLN
        - Словакия (SK) - EUR  
        - Чехия (CZ) - CZK
        - Венгрия (HU) - HUF
        - Бизнес Чехия (BUSINESS_CZ) - CZK
        
        Returns:
            MarketResponse: Список рынков с информацией о валютах и курсах
        """
        url = f"{self.endpoint}/"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return MarketResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения списка рынков: {str(e)}")
    
    async def get_currency_rates(self, force_refresh: bool = False) -> CurrencyRatesResponse:
        """
        Получить актуальные курсы валют.
        
        Args:
            force_refresh: Принудительно обновить кэш курсов валют
            
        Returns:
            CurrencyRatesResponse: Курсы валют для всех поддерживаемых рынков
        """
        url = f"{self.endpoint}/currency-rates"
        params = {"force_refresh": force_refresh}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return CurrencyRatesResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения курсов валют: {str(e)}")
    
    async def preview_pricing(
        self, 
        offers: List[Dict[str, Any]], 
        markets: List[str], 
        pricing_rules: Dict[str, MarketPricingRule]
    ) -> PricingPreviewResponse:
        """
        Предварительный расчет цен для офферов.
        
        Позволяет увидеть, как будут выглядеть цены на различных рынках
        до фактического переноса офферов.
        
        Args:
            offers: Список офферов для расчета
            markets: Целевые рынки
            pricing_rules: Правила ценообразования для каждого рынка
            
        Returns:
            PricingPreviewResponse: Предварительные расчеты цен
        """
        url = f"{self.endpoint}/pricing/preview"
        payload = {
            "offers": offers,
            "markets": markets,
            "pricing_rules": pricing_rules
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return PricingPreviewResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка расчета цен: {str(e)}")
    
    async def clear_currency_cache(self) -> StatusResponse:
        """
        Очистить кэш курсов валют.
        
        Полезно для получения самых актуальных курсов валют
        при подозрении на устаревшие данные.
        
        Returns:
            StatusResponse: Результат очистки кэша
        """
        url = f"{self.endpoint}/currency-rates/clear-cache"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка очистки кэша: {str(e)}")
    
    async def get_supported_currencies(self) -> List[str]:
        """
        Получить список поддерживаемых валют.
        
        Returns:
            List[str]: Список всех поддерживаемых валют
        """
        url = f"{self.endpoint}/supported-currencies"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения списка валют: {str(e)}")
    
    async def get_market_info(self, market_code: str) -> Optional[MarketInfo]:
        """
        Получить информацию о конкретном рынке.
        
        Args:
            market_code: Код рынка (например, "PL", "CZ", "SK", "HU")
            
        Returns:
            Optional[MarketInfo]: Информация о рынке или None, если не найден
        """
        markets = await self.get_available_markets()
        
        for market in markets.markets:
            if market.code == market_code:
                return market
        
        return None
    
    async def get_market_exchange_rate(self, market_code: str, force_refresh: bool = False) -> Optional[float]:
        """
        Получить курс обмена для конкретного рынка.
        
        Args:
            market_code: Код рынка
            force_refresh: Принудительно обновить кэш
            
        Returns:
            Optional[float]: Курс обмена или None, если не найден
        """
        rates = await self.get_currency_rates(force_refresh=force_refresh)
        return rates.rates.get(market_code)
    
    async def calculate_price_for_market(
        self, 
        base_price: float, 
        base_currency: str, 
        target_market: str,
        pricing_rule: MarketPricingRule
    ) -> Optional[float]:
        """
        Рассчитать цену для конкретного рынка.
        
        Args:
            base_price: Базовая цена
            base_currency: Базовая валюта
            target_market: Целевой рынок
            pricing_rule: Правило ценообразования
            
        Returns:
            Optional[float]: Рассчитанная цена или None, если ошибка
        """
        try:
            # Получаем курс обмена
            exchange_rate = await self.get_market_exchange_rate(target_market)
            if not exchange_rate:
                return None
            
            # Применяем правило ценообразования
            if pricing_rule.type == "multiply":
                return base_price * exchange_rate * pricing_rule.value
            elif pricing_rule.type == "add":
                return base_price * exchange_rate + pricing_rule.value
            elif pricing_rule.type == "convert_with_markup":
                markup = 1 + (pricing_rule.value / 100)
                return base_price * exchange_rate * markup
            elif pricing_rule.type == "custom":
                # Кастомная формула (например, "price * 1.2 + 5")
                return base_price * exchange_rate * 1.2 + 5
            else:
                return base_price * exchange_rate
                
        except Exception as e:
            raise Exception(f"Ошибка при расчете цены для рынка {target_market}: {str(e)}")
    
    async def get_markets_by_currency(self, currency: str) -> List[MarketInfo]:
        """
        Получить все рынки с определенной валютой.
        
        Args:
            currency: Код валюты (например, "PLN", "EUR", "CZK", "HUF")
            
        Returns:
            List[MarketInfo]: Список рынков с указанной валютой
        """
        markets = await self.get_available_markets()
        
        return [market for market in markets.markets if market.currency == currency]
    
    async def validate_market_compatibility(self, source_market: str, target_markets: List[str]) -> Dict[str, bool]:
        """
        Проверить совместимость исходного рынка с целевыми.
        
        Args:
            source_market: Код исходного рынка
            target_markets: Список кодов целевых рынков
            
        Returns:
            Dict[str, bool]: Словарь совместимости для каждого целевого рынка
        """
        # Простая логика проверки - можно расширить
        compatibility_map = {
            "PL": ["CZ", "SK", "HU"],  # Польша -> Чехия, Словакия, Венгрия
            "CZ": ["PL", "SK", "HU"],  # Чехия -> Польша, Словакия, Венгрия
            "SK": ["PL", "CZ", "HU"],  # Словакия -> Польша, Чехия, Венгрия
            "HU": ["PL", "CZ", "SK"]   # Венгрия -> Польша, Чехия, Словакия
        }
        
        source_markets = compatibility_map.get(source_market, [])
        return {market: market in source_markets for market in target_markets}
    
    async def get_market_statistics(self) -> Dict[str, Any]:
        """
        Получить статистику по рынкам.
        
        Returns:
            Dict[str, Any]: Статистика использования рынков
        """
        url = f"{self.endpoint}/statistics"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения статистики рынков: {str(e)}")
    
    async def get_market_health_check(self) -> Dict[str, Any]:
        """
        Проверить состояние рынков.
        
        Returns:
            Dict[str, Any]: Состояние рынков и доступность API
        """
        url = f"{self.endpoint}/health"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка проверки состояния рынков: {str(e)}")
    
    async def get_market_updates(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Получить обновления по рынкам.
        
        Args:
            since: Время, с которого получать обновления
            
        Returns:
            List[Dict[str, Any]]: Список обновлений
        """
        url = f"{self.endpoint}/updates"
        params = {}
        
        if since:
            params["since"] = since.isoformat()
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json().get("updates", [])
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения обновлений рынков: {str(e)}")
    
    async def subscribe_to_market_updates(self, market_codes: List[str]) -> StatusResponse:
        """
        Подписаться на обновления по рынкам.
        
        Args:
            market_codes: Список кодов рынков для подписки
            
        Returns:
            StatusResponse: Результат подписки
        """
        url = f"{self.endpoint}/subscribe"
        payload = {"market_codes": market_codes}
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка подписки на обновления рынков: {str(e)}")
    
    async def unsubscribe_from_market_updates(self, market_codes: List[str]) -> StatusResponse:
        """
        Отписаться от обновлений по рынкам.
        
        Args:
            market_codes: Список кодов рынков для отписки
            
        Returns:
            StatusResponse: Результат отписки
        """
        url = f"{self.endpoint}/unsubscribe"
        payload = {"market_codes": market_codes}
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка отписки от обновлений рынков: {str(e)}")
