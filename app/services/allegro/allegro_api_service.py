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
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Начинаем получение событий заказов для токена: {token[:10]}...")
        logger.info(f"Параметры запроса: from_event_id={from_event_id}, types={types}, limit={limit}")
        
        params = {"limit": min(limit, 1000)}  # Ограничиваем максимальное значение
        
        if from_event_id:
            params["from"] = from_event_id
        if types:
            params["type"] = types

        logger.info(f"Финальные параметры запроса: {params}")

        try:
            logger.info("Отправляем запрос к /order/events")
            response = self.client.get(
                "/order/events",
                headers=self._get_headers(token),
                params=params
            )
            logger.info(f"Получен ответ с кодом: {response.status_code}")
            
            response.raise_for_status()
            data = response.json()
            logger.info(f"Получены данные событий: {data}")
            
            return data
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка при получении событий заказов: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Код ответа: {e.response.status_code}")
                logger.error(f"Текст ответа: {e.response.text}")
            raise ValueError(f"Ошибка при получении событий заказов: {str(e)}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении событий заказов: {str(e)}")
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
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Начинаем получение статистики событий для токена: {token[:10]}...")
        
        try:
            logger.info("Отправляем запрос к /order/event-stats")
            response = self.client.get(
                "/order/event-stats",
                headers=self._get_headers(token)
            )
            logger.info(f"Получен ответ с кодом: {response.status_code}")
            
            response.raise_for_status()
            data = response.json()
            logger.info(f"Получены данные статистики: {data}")
            
            return data
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка при получении статистики событий: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Код ответа: {e.response.status_code}")
                logger.error(f"Текст ответа: {e.response.text}")
            raise ValueError(f"Ошибка при получении статистики событий: {str(e)}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении статистики событий: {str(e)}")
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
            # Передаем список external_ids как отдельные параметры
            params["external.id"] = external_ids

        if sort:
            params["sort"] = sort
        if publication_status:
            params["publication.status"] = publication_status
        if publication_marketplace:
            params["publication.marketplace"] = publication_marketplace

        try:
            response = self.client.get(
                "/sale/offers",
                headers=self._get_headers(token),
                params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при получении офферов: {str(e)}")

    def update_offer_stock(
        self,
        token: str,
        offer_id: str,
        stock_available: int
    ) -> Dict[str, Any]:
        """
        Обновляет остаток товара в оффере через групповую операцию изменения количества.
        
        Args:
            token: Токен доступа
            offer_id: ID оффера для обновления
            stock_available: Количество доступного товара
            
        Returns:
            Dict[str, Any]: Ответ от API
            
        Raises:
            ValueError: При ошибке обновления остатка
        """
        import uuid
        
        # Генерируем уникальный UUID для команды
        command_id = str(uuid.uuid4())
        
        # Подготавливаем данные для групповой операции изменения количества
        update_data = {
            "modification": {
                "changeType": "FIXED",  # Устанавливаем точное количество
                "value": stock_available
            },
            "offerCriteria": [{
                "type": "CONTAINS_OFFERS",
                "offers": [{
                    "id": offer_id
                }]
            }]
        }
        
        # Заголовки для PUT запроса
        headers = self._get_headers(token)
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"
        
        try:
            response = self.client.put(
                f"/sale/offer-quantity-change-commands/{command_id}",
                headers=headers,
                json=update_data
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при обновлении остатка оффера {offer_id}: {str(e)}")

    def update_offer(
        self,
        token: str,
        offer_id: str,
        stock_available: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Обновляет оффер через PATCH запрос (устаревший метод).
        Для обновления остатков используйте update_offer_stock.
        
        Args:
            token: Токен доступа
            offer_id: ID оффера для обновления
            stock_available: Количество доступного товара
            **kwargs: Дополнительные параметры для обновления
            
        Returns:
            Dict[str, Any]: Ответ от API
            
        Raises:
            ValueError: При ошибке обновления оффера
        """
        # Если только обновляем остаток, используем новый метод
        if stock_available is not None and not kwargs:
            return self.update_offer_stock(token, offer_id, stock_available)
        
        # Подготавливаем данные для обновления
        update_data = {}
        
        if stock_available is not None:
            update_data["stock"] = {
                "available": stock_available
            }
        
        # Добавляем дополнительные параметры
        update_data.update(kwargs)
        
        if not update_data:
            raise ValueError("Не указаны данные для обновления")
        
        # Заголовки для PATCH запроса
        headers = self._get_headers(token)
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"
        
        try:
            response = self.client.patch(
                f"/sale/offers/{offer_id}",
                headers=headers,
                json=update_data
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при обновлении оффера {offer_id}: {str(e)}")

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
            # Передаем список external_ids как отдельные параметры
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

    async def update_offer(
        self,
        token: str,
        offer_id: str,
        stock_available: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Асинхронная версия обновления оффера через PATCH запрос.
        
        Args:
            token: Токен доступа
            offer_id: ID оффера для обновления
            stock_available: Количество доступного товара
            **kwargs: Дополнительные параметры для обновления
            
        Returns:
            Dict[str, Any]: Ответ от API
            
        Raises:
            ValueError: При ошибке обновления оффера
        """
        # Подготавливаем данные для обновления
        update_data = {}
        
        if stock_available is not None:
            update_data["stock"] = {
                "available": stock_available
            }
        
        # Добавляем дополнительные параметры
        update_data.update(kwargs)
        
        if not update_data:
            raise ValueError("Не указаны данные для обновления")
        
        # Заголовки для PATCH запроса
        headers = self._get_headers(token)
        headers["Content-Type"] = "application/vnd.allegro.public.v1+json"
        
        try:
            async with self.client as client:
                response = await client.patch(
                    f"/sale/offers/{offer_id}",
                    headers=headers,
                    json=update_data
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise ValueError(f"Ошибка при обновлении оффера {offer_id}: {str(e)}")

