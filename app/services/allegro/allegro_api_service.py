from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx
from pydantic import BaseModel
import requests
import logging

logger = logging.getLogger(__name__)

class BaseAllegroApiService:
    def __init__(self, base_url: str = "https://api.allegro.pl/"):
        self.base_url = base_url

    def _get_headers(self, token: str) -> Dict[str, str]:
        """Формирует заголовки для запросов к API."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/vnd.allegro.public.v1+json",
            "Accept": "application/vnd.allegro.public.v1+json",
        }

    def _prepare_order_params(
        self,
        offset: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        fulfillment_status: Optional[str] = None,
        items_sent_status: Optional[str] = None,
        bought_at_gte: Optional[datetime] = None,
        bought_at_lte: Optional[datetime] = None,
        buyer_login: Optional[str] = None,
        sort: Optional[str] = None,
        updated_at_gte: Optional[datetime] = None,
        updated_at_lte: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Подготавливает параметры для запроса заказов."""
        params = {
            "offset": offset,
            "limit": limit
        }

        if status:
            params["status"] = status
        if fulfillment_status:
            params["fulfillment.status"] = fulfillment_status
        if items_sent_status:
            params["fulfillment.shipmentSummary.lineItemsSent"] = items_sent_status
        if bought_at_gte:
            params["lineItems.boughtAt.gte"] = bought_at_gte.isoformat()
        if bought_at_lte:
            params["lineItems.boughtAt.lte"] = bought_at_lte.isoformat()
        if buyer_login:
            params["buyer.login"] = buyer_login
        if sort:
            params["sort"] = sort
        if updated_at_gte:
            params["updatedAt.gte"] = updated_at_gte.isoformat()
        if updated_at_lte:
            params["updatedAt.lte"] = updated_at_lte.isoformat()

        return params

class SyncAllegroApiService(BaseAllegroApiService):
    def __init__(self, base_url: str = "https://api.allegro.pl"):
        super().__init__(base_url)
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=30.0
        )

    def get_orders(
        self,
        token: str,
        status: str = None,
        offset: int = 0,
        limit: int = 100,
        updated_at_gte: datetime = None,
        updated_at_lte: datetime = None,
        sort: str = None
    ) -> Dict[str, Any]:
        """
        Получает список заказов с фильтрацией.
        
        Args:
            token: Токен доступа
            status: Статус заказа
            offset: Смещение для пагинации
            limit: Количество заказов на странице
            updated_at_gte: Минимальная дата обновления
            updated_at_lte: Максимальная дата обновления
            sort: Параметр сортировки
            
        Returns:
            Dict[str, Any]: Ответ от API с заказами
        """
        try:
            # Проверяем, не является ли дата будущей
            if updated_at_gte and updated_at_gte > datetime.now():
                logger.warning(f"Указана будущая дата {updated_at_gte}, используем текущую дату")
                updated_at_gte = datetime.now()
                
            params = {
                'offset': offset,
                'limit': limit
            }
            
            if status:
                params['status'] = status
            if updated_at_gte:
                # Форматируем дату в ISO 8601 с Z в конце
                params['updatedAt.gte'] = updated_at_gte.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            if updated_at_lte:
                params['updatedAt.lte'] = updated_at_lte.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            if sort:
                params['sort'] = sort
                
            headers = {
                'Authorization': f'Bearer {token}',
                'Accept': 'application/vnd.allegro.public.v1+json'
            }
            
            logger.info(f"Отправляем запрос к API Allegro с параметрами: {params}")
            
            response = requests.get(
                f"{self.base_url}/order/checkout-forms",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"Client error '{response.status_code} {response.reason}' for url '{response.url}'"
                logger.error(error_msg)
                
                # Логируем тело ответа с ошибкой
                try:
                    error_body = response.json()
                    logger.error(f"Тело ответа с ошибкой: {error_body}")
                except:
                    logger.error(f"Не удалось получить тело ответа: {response.text}")
                
                raise ValueError(f"Ошибка при получении заказов: {error_msg}")
                
        except Exception as e:
            logger.error(f"Ошибка при получении заказов: {str(e)}")
            raise

    def get_order_details(self, token: str, order_id: str) -> Dict[str, Any]:
        """Синхронная версия получения деталей заказа."""
        try:
            response = self.client.get(
                f"/order/checkout-forms/{order_id}",
                headers=self._get_headers(token)
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении деталей заказа: {str(e)}")

    def get_order_events(
        self,
        token: str,
        types: Optional[List[str]] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Синхронная версия получения событий заказов."""
        params = {"limit": limit}
        if types:
            params["type"] = types

        try:
            response = self.client.get(
                "/order/events",
                headers=self._get_headers(token),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении событий заказов: {str(e)}")

class AsyncAllegroApiService(BaseAllegroApiService):
    def __init__(self, base_url: str = "https://api.allegro.pl"):
        super().__init__(base_url)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0
        )

    async def get_orders(
        self,
        token: str,
        offset: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        fulfillment_status: Optional[str] = None,
        items_sent_status: Optional[str] = None,
        bought_at_gte: Optional[datetime] = None,
        bought_at_lte: Optional[datetime] = None,
        buyer_login: Optional[str] = None,
        sort: Optional[str] = None,
        updated_at_gte: Optional[datetime] = None,
        updated_at_lte: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Асинхронная версия получения списка заказов."""
        params = self._prepare_order_params(
            offset, limit, status, fulfillment_status, items_sent_status,
            bought_at_gte, bought_at_lte, buyer_login, sort,
            updated_at_gte, updated_at_lte
        )

        try:
            async with self.client as client:
                response = await client.get(
                    "/order/checkout-forms",
                    headers=self._get_headers(token),
                    params=params
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении заказов: {str(e)}")

    async def get_order_details(self, token: str, order_id: str) -> Dict[str, Any]:
        """Асинхронная версия получения деталей заказа."""
        try:
            async with self.client as client:
                response = await client.get(
                    f"/order/checkout-forms/{order_id}",
                    headers=self._get_headers(token)
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении деталей заказа: {str(e)}")

    async def get_order_events(
        self,
        token: str,
        types: Optional[List[str]] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Асинхронная версия получения событий заказов."""
        params = {"limit": limit}
        if types:
            params["type"] = types

        try:
            async with self.client as client:
                response = await client.get(
                    "/order/events",
                    headers=self._get_headers(token),
                    params=params
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении событий заказов: {str(e)}")

