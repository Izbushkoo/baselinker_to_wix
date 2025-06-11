from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx
from pydantic import BaseModel
import requests
import logging

logger = logging.getLogger(__name__)


class NotFoundDetails(Exception):
    """
    Исключение, возникающее при отсутствии деталей заказа.
    """
    def __init__(self, message: str = "Детали не найдены"):
        self.message = message
        super().__init__(self.message)


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
            now = datetime.now().replace(tzinfo=None)
            if updated_at_gte and updated_at_gte.replace(tzinfo=None) > now:
                logger.warning(f"Указана будущая дата {updated_at_gte}, используем текущую дату")
                updated_at_gte = now
                
            params = {
                'offset': offset,
                'limit': limit
            }
            
            if status:
                params['status'] = status
            if updated_at_gte:
                # Убираем информацию о часовом поясе перед форматированием
                gte_date = updated_at_gte.replace(tzinfo=None)
                params['updatedAt.gte'] = gte_date.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            if updated_at_lte:
                # Убираем информацию о часовом поясе перед форматированием
                lte_date = updated_at_lte.replace(tzinfo=None)
                params['updatedAt.lte'] = lte_date.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            if sort:
                params['sort'] = sort
                
            response = self.client.get(
                "/order/checkout-forms",
                headers=self._get_headers(token),
                params=params
            )
            
            response.raise_for_status()
            return response.json()
                
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise NotFoundDetails(f"Детали заказа '{order_id}' не найдены")
            raise ValueError(f"Ошибка при получении деталей заказа: {str(e)}")

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

    def get_order_events_v2(
        self,
        token: str,
        from_event_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Получает события заказов с расширенными параметрами фильтрации.
        
        Args:
            token: Токен доступа
            from_event_id: ID события, начиная с которого нужно получить события
            types: Список типов событий для фильтрации
            limit: Максимальное количество событий в ответе (1-1000)
            
        Returns:
            Dict[str, Any]: Ответ от API с событиями заказов
        """
        params = {"limit": min(limit, 1000)}  # Ограничиваем максимальное значение
        
        if from_event_id:
            params["from"] = from_event_id
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

    def get_orders_v2(
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
        payment_id: Optional[str] = None,
        surcharge_id: Optional[str] = None,
        delivery_method_id: Optional[str] = None,
        marketplace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получает список заказов с расширенными параметрами фильтрации.
        
        Args:
            token: Токен доступа
            offset: Смещение для пагинации
            limit: Количество заказов на странице
            status: Статус заказа
            fulfillment_status: Статус выполнения
            items_sent_status: Статус отправки товаров
            bought_at_gte: Минимальная дата покупки
            bought_at_lte: Максимальная дата покупки
            buyer_login: Логин покупателя
            sort: Параметр сортировки
            updated_at_gte: Минимальная дата обновления
            updated_at_lte: Максимальная дата обновления
            payment_id: ID платежа
            surcharge_id: ID доплаты
            delivery_method_id: ID метода доставки
            marketplace_id: ID маркетплейса
            
        Returns:
            Dict[str, Any]: Ответ от API с заказами
        """
        params = self._prepare_order_params(
            offset, limit, status, fulfillment_status, items_sent_status,
            bought_at_gte, bought_at_lte, buyer_login, sort,
            updated_at_gte, updated_at_lte
        )

        # Добавляем новые параметры
        if payment_id:
            params["payment.id"] = payment_id
        if surcharge_id:
            params["surcharges.id"] = surcharge_id
        if delivery_method_id:
            params["delivery.method.id"] = delivery_method_id
        if marketplace_id:
            params["marketplace.id"] = marketplace_id

        try:
            response = self.client.get(
                "/order/checkout-forms",
                headers=self._get_headers(token),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении заказов: {str(e)}")

    def get_order_events_statistics(self, token: str) -> Dict[str, Any]:
        """
        Получает статистику событий заказов, включая ID последнего события.
        
        Args:
            token: Токен доступа
            
        Returns:
            Dict[str, Any]: Ответ от API со статистикой событий
        """
        try:
            response = self.client.get(
                "/order/event-stats",
                headers=self._get_headers(token)
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении статистики событий: {str(e)}")

    def get_offers(
        self,
        token: str,
        external_ids: Optional[List[str]] = None,
        limit: int = 20,
        offset: int = 0,
        sort: Optional[str] = None,
        publication_status: Optional[List[str]] = None,
        publication_marketplace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получает список офферов продавца с возможностью фильтрации.
        
        Args:
            token: Токен доступа
            external_ids: Список внешних идентификаторов для фильтрации
            limit: Максимальное количество офферов в ответе (1-1000)
            offset: Смещение для пагинации
            sort: Параметр сортировки
            publication_status: Статус публикации оффера
            publication_marketplace: ID маркетплейса
            
        Returns:
            Dict[str, Any]: Ответ от API с офферами
            
        Raises:
            ValueError: При ошибке получения данных
        """
        params = {
            "limit": min(limit, 1000),  # Ограничиваем максимальное значение
            "offset": offset
        }

        if external_ids:
            for external_id in external_ids:
                if len(external_id) > 100:
                    raise ValueError("Длина external.id не должна превышать 100 символов")
                params["external.id"] = external_ids

        if sort:
            params["sort"] = sort
        if publication_status:
            params["publication.status"] = publication_status
        if publication_marketplace:
            params["publication.marketplace"] = publication_marketplace

        try:
            response = self.client.get(
                "/offers/listing",
                headers=self._get_headers(token),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении офферов: {str(e)}")

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

    async def get_order_events_v2(
        self,
        token: str,
        from_event_id: Optional[str] = None,
        types: Optional[List[str]] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Получает события заказов с расширенными параметрами фильтрации.
        
        Args:
            token: Токен доступа
            from_event_id: ID события, начиная с которого нужно получить события
            types: Список типов событий для фильтрации
            limit: Максимальное количество событий в ответе (1-1000)
            
        Returns:
            Dict[str, Any]: Ответ от API с событиями заказов
        """
        params = {"limit": min(limit, 1000)}  # Ограничиваем максимальное значение
        
        if from_event_id:
            params["from"] = from_event_id
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

    async def get_orders_v2(
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
        payment_id: Optional[str] = None,
        surcharge_id: Optional[str] = None,
        delivery_method_id: Optional[str] = None,
        marketplace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получает список заказов с расширенными параметрами фильтрации.
        
        Args:
            token: Токен доступа
            offset: Смещение для пагинации
            limit: Количество заказов на странице
            status: Статус заказа
            fulfillment_status: Статус выполнения
            items_sent_status: Статус отправки товаров
            bought_at_gte: Минимальная дата покупки
            bought_at_lte: Максимальная дата покупки
            buyer_login: Логин покупателя
            sort: Параметр сортировки
            updated_at_gte: Минимальная дата обновления
            updated_at_lte: Максимальная дата обновления
            payment_id: ID платежа
            surcharge_id: ID доплаты
            delivery_method_id: ID метода доставки
            marketplace_id: ID маркетплейса
            
        Returns:
            Dict[str, Any]: Ответ от API с заказами
        """
        params = self._prepare_order_params(
            offset, limit, status, fulfillment_status, items_sent_status,
            bought_at_gte, bought_at_lte, buyer_login, sort,
            updated_at_gte, updated_at_lte
        )

        # Добавляем новые параметры
        if payment_id:
            params["payment.id"] = payment_id
        if surcharge_id:
            params["surcharges.id"] = surcharge_id
        if delivery_method_id:
            params["delivery.method.id"] = delivery_method_id
        if marketplace_id:
            params["marketplace.id"] = marketplace_id

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

    async def get_offers(
        self,
        token: str,
        external_ids: Optional[List[str]] = None,
        limit: int = 20,
        offset: int = 0,
        sort: Optional[str] = None,
        publication_status: Optional[List[str]] = None,
        publication_marketplace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Асинхронная версия получения списка офферов продавца с возможностью фильтрации.
        
        Args:
            token: Токен доступа
            external_ids: Список внешних идентификаторов для фильтрации
            limit: Максимальное количество офферов в ответе (1-1000)
            offset: Смещение для пагинации
            sort: Параметр сортировки
            publication_status: Статус публикации оффера
            publication_marketplace: ID маркетплейса
            
        Returns:
            Dict[str, Any]: Ответ от API с офферами
            
        Raises:
            ValueError: При ошибке получения данных
        """
        params = {
            "limit": min(limit, 1000),  # Ограничиваем максимальное значение
            "offset": offset
        }

        if external_ids:
            for external_id in external_ids:
                if len(external_id) > 100:
                    raise ValueError("Длина external.id не должна превышать 100 символов")
                params["external.id"] = external_ids

        if sort:
            params["sort"] = sort
        if publication_status:
            params["publication.status"] = publication_status
        if publication_marketplace:
            params["publication.marketplace"] = publication_marketplace

        try:
            async with self.client as client:
                response = await client.get(
                    "/offers/listing",
                    headers=self._get_headers(token),
                    params=params
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении офферов: {str(e)}")

