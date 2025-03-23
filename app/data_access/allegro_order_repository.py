from typing import Optional, Dict, Any
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from datetime import datetime
from app.utils.logging_config import logger

from app.models.allegro_order import (
    AllegroOrder,
    AllegroBuyer,
    AllegroLineItem,
    OrderLineItem,
)

class AllegroOrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def _safe_get(self, data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Безопасно получает значение из вложенного словаря.
        
        Args:
            data: Словарь с данными
            keys: Последовательность ключей для доступа к вложенным данным
            default: Значение по умолчанию, если данные не найдены
        """
        current = data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key, default)
            if current is None:
                return default
        return current

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """
        Безопасно преобразует значение в float.
        """
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def _safe_datetime(self, value: str) -> Optional[datetime]:
        """
        Безопасно преобразует строку в datetime.
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    def add_order(self, token_id: str, order_data: dict) -> AllegroOrder:
        """
        Создает новый заказ в базе данных со всеми связанными данными.
        
        Args:
            token_id: ID токена Allegro
            order_data (dict): Полные данные заказа в формате JSON от API Allegro
        
        Returns:
            AllegroOrder: Созданный заказ
        """

        logger.info(f"Добавление заказа: {order_data}")

        # Создаем покупателя
        buyer_data = self._safe_get(order_data, "buyer", default={})
        buyer = AllegroBuyer(
            id=self._safe_get(buyer_data, "id", default=""),
            email=self._safe_get(buyer_data, "email", default=""),
            login=self._safe_get(buyer_data, "login", default=""),
            first_name=self._safe_get(buyer_data, "firstName", default=""),
            last_name=self._safe_get(buyer_data, "lastName", default=""),
            company_name=self._safe_get(buyer_data, "companyName"),
            phone_number=self._safe_get(buyer_data, "phoneNumber", default=""),
            address=self._safe_get(buyer_data, "address", default={})
        )
        self.session.add(buyer)
        
        # Создаем заказ
        order = AllegroOrder(
            id=self._safe_get(order_data, "id", default=""),
            status=self._safe_get(order_data, "status", default=""),
            token_id=token_id,
            buyer=buyer,
            payment=self._safe_get(order_data, "payment", default={}),
            fulfillment=self._safe_get(order_data, "fulfillment", default={}),
            delivery=self._safe_get(order_data, "delivery", default={})
        )
        self.session.add(order)
        
        # Создаем товарные позиции
        delivery = self._safe_get(order_data, "delivery", default={})
        line_items = self._safe_get(delivery, "lineItems", default=[])
        # line_items = self._safe_get(order_data,"delivery", "lineItems", default=[])
        for item_data in line_items:
            item_id = self._safe_get(item_data, "id", default="")
            quantity = self._safe_get(item_data, "quantity", default=1)
            if not item_id:
                continue
                
            # Проверяем, существует ли уже такая позиция
            existing_item = self.session.exec(
                select(AllegroLineItem).where(AllegroLineItem.id == item_id)
            ).first()
            
            if existing_item:
                # Если позиция существует, создаем связь с заказом
                for _ in range(quantity):
                    order_item = OrderLineItem(
                        order_id=order.id,
                        line_item_id=existing_item.id
                    )
                    self.session.add(order_item)
            else:
                # Если позиция не существует, создаем новую
                offer_data = self._safe_get(item_data, "offer", default={})
                line_item = AllegroLineItem(
                    id=item_id,
                    offer_id=self._safe_get(offer_data, "id", default=""),
                    offer_name=self._safe_get(offer_data, "name", default=""),
                    external_id=self._safe_get(offer_data, "external", "id", default=""),
                    original_price=self._safe_get(item_data, "originalPrice", default={}),
                    price=self._safe_get(item_data, "price", default={})
                )
                self.session.add(line_item)
                
                # Создаем связь с заказом
                for _ in range(quantity):
                    order_item = OrderLineItem(
                        order_id=order.id,
                        line_item_id=line_item.id
                    )
                    self.session.add(order_item)
        
        try:
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            raise ValueError(f"Ошибка при сохранении заказа: {str(e)}")
        
        return order

    def get_order_by_id(self, order_id: str) -> Optional[AllegroOrder]:
        """
        Получает заказ по его ID со всеми связанными данными.
        
        Args:
            order_id (str): ID заказа
        
        Returns:
            Optional[AllegroOrder]: Найденный заказ или None
        """
        if not order_id:
            return None

        try:
            statement = (
                select(AllegroOrder)
                .where(AllegroOrder.id == order_id)
                .options(
                    selectinload(AllegroOrder.buyer),
                    selectinload(AllegroOrder.token),
                    selectinload(AllegroOrder.order_items).selectinload(OrderLineItem.line_item)
                )
            )
            result = self.session.exec(statement).first()
            return result
        except Exception as e:
            raise ValueError(f"Ошибка при получении заказа: {str(e)}")

    def update_order(self, token_id: str, order_id: str, order_data: dict) -> Optional[AllegroOrder]:
        """
        Обновляет существующий заказ новыми данными.
        
        Args:
            token_id: ID токена Allegro
            order_id (str): ID заказа для обновления
            order_data (dict): Новые данные заказа
        
        Returns:
            Optional[AllegroOrder]: Обновленный заказ или None, если заказ не найден
        """
        if not order_id or not order_data:
            return None

        try:
            order = self.get_order_by_id(order_id)
            if not order:
                return None

            # Обновляем основные данные заказа
            order.status = self._safe_get(order_data, "status", default=order.status)
            order.updated_at = self._safe_datetime(self._safe_get(order_data, "updatedAt"))
            order.token_id = token_id
            
            # Обновляем данные покупателя
            if order.buyer:
                buyer_data = self._safe_get(order_data, "buyer", default={})
                order.buyer.email = self._safe_get(buyer_data, "email", default=order.buyer.email)
                order.buyer.phone_number = self._safe_get(buyer_data, "phoneNumber", default=order.buyer.phone_number)
                order.buyer.login = self._safe_get(buyer_data, "login", default=order.buyer.login)
                order.buyer.first_name = self._safe_get(buyer_data, "firstName", default=order.buyer.first_name)
                order.buyer.last_name = self._safe_get(buyer_data, "lastName", default=order.buyer.last_name)
                order.buyer.company_name = self._safe_get(buyer_data, "companyName", default=order.buyer.company_name)
                order.buyer.address = self._safe_get(buyer_data, "address", default=order.buyer.address)

            # Обновляем JSON структуры
            order.payment = self._safe_get(order_data, "payment", default=order.payment)
            order.fulfillment = self._safe_get(order_data, "fulfillment", default=order.fulfillment)
            order.delivery = self._safe_get(order_data, "delivery", default=order.delivery)

            # Обновляем товарные позиции
            line_items = self._safe_get(order_data, "delivery", "lineItems")
            if line_items is not None:
                # Удаляем старые связи
                self.session.exec(
                    select(OrderLineItem).where(OrderLineItem.order_id == order_id)
                ).delete()
                
                # Добавляем новые связи
                for item_data in line_items:
                    item_id = self._safe_get(item_data, "id", default="")
                    quantity = self._safe_get(item_data, "quantity", default=1)
                    if not item_id:
                        continue
                        
                    # Проверяем, существует ли уже такая позиция
                    existing_item = self.session.exec(
                        select(AllegroLineItem).where(AllegroLineItem.id == item_id)
                    ).first()
                    
                    if existing_item:
                        # Если позиция существует, создаем связь с заказом
                        for _ in range(quantity):
                            order_item = OrderLineItem(
                                order_id=order.id,
                                line_item_id=existing_item.id
                            )
                            self.session.add(order_item)
                    else:
                        # Если позиция не существует, создаем новую
                        offer_data = self._safe_get(item_data, "offer", default={})
                        line_item = AllegroLineItem(
                            id=item_id,
                            offer_id=self._safe_get(offer_data, "id", default=""),
                            offer_name=self._safe_get(offer_data, "name", default=""),
                            external_id=self._safe_get(offer_data, "external", "id", default=""),
                            original_price=self._safe_get(item_data, "originalPrice", default={}),
                            price=self._safe_get(item_data, "price", default={})
                        )
                        self.session.add(line_item)
                        
                        # Создаем связь с заказом
                        for _ in range(quantity):
                            order_item = OrderLineItem(
                                order_id=order.id,
                                line_item_id=line_item.id
                            )
                            self.session.add(order_item)

            self.session.commit()
            return order
            
        except Exception as e:
            self.session.rollback()
            raise ValueError(f"Ошибка при обновлении заказа: {str(e)}")

    def get_all_orders_basic_info(self) -> list:
        """
        Получает базовую информацию о всех заказах.
        """
        try:
            statement = select(AllegroOrder.id, AllegroOrder.updated_at)
            result = self.session.exec(statement).all()
            orders = [{"id": order.id, "updateTime": order.updated_at} for order in result]
            if not orders:
                logger.info("В базе данных нет заказов")
            else:
                logger.info(f"Найдено {len(orders)} заказов в базе данных")
            return orders
        except Exception as e:
            logger.error(f"Ошибка при получении списка заказов: {str(e)}")
            raise ValueError(f"Ошибка при получении списка заказов: {str(e)}")

    def add_order_with_existing_buyer(self, token_id: str, order_data: dict) -> AllegroOrder:
        """
        Добавляет заказ, используя существующего покупателя.
        
        Args:
            token_id: ID токена Allegro
            order_data: Данные заказа
        
        Returns:
            AllegroOrder: Созданный заказ
        """
        try:
            # Получаем существующего покупателя
            buyer_data = self._safe_get(order_data, "buyer", default={})
            buyer_id = self._safe_get(buyer_data, "id", default="")
            
            if not buyer_id:
                raise ValueError("ID покупателя не указан в данных заказа")
            
            # Ищем существующего покупателя
            statement = select(AllegroBuyer).where(AllegroBuyer.id == buyer_id)
            buyer = self.session.exec(statement).first()
            
            if not buyer:
                raise ValueError(f"Покупатель с ID {buyer_id} не найден")
            
            # Создаем заказ с существующим покупателем
            order = AllegroOrder(
                id=self._safe_get(order_data, "id", default=""),
                status=self._safe_get(order_data, "status", default=""),
                token_id=token_id,
                buyer=buyer,
                payment=self._safe_get(order_data, "payment", default={}),
                fulfillment=self._safe_get(order_data, "fulfillment", default={}),
                delivery=self._safe_get(order_data, "delivery", default={})
            )
            self.session.add(order)
            
            # Создаем товарные позиции
            delivery = self._safe_get(order_data, "delivery", default={})
            line_items = self._safe_get(delivery, "lineItems", default=[])
            for item_data in line_items:
                item_id = self._safe_get(item_data, "id", default="")
                quantity = self._safe_get(item_data, "quantity", default=1)
                if not item_id:
                    continue
                    
                # Проверяем, существует ли уже такая позиция
                existing_item = self.session.exec(
                    select(AllegroLineItem).where(AllegroLineItem.id == item_id)
                ).first()
                
                if existing_item:
                    # Если позиция существует, создаем связь с заказом
                    for _ in range(quantity):
                        order_item = OrderLineItem(
                            order_id=order.id,
                            line_item_id=existing_item.id
                        )
                        self.session.add(order_item)
                else:
                    # Если позиция не существует, создаем новую
                    offer_data = self._safe_get(item_data, "offer", default={})
                    line_item = AllegroLineItem(
                        id=item_id,
                        offer_id=self._safe_get(offer_data, "id", default=""),
                        offer_name=self._safe_get(offer_data, "name", default=""),
                        external_id=self._safe_get(offer_data, "external", "id", default=""),
                        original_price=self._safe_get(item_data, "originalPrice", default={}),
                        price=self._safe_get(item_data, "price", default={})
                    )
                    self.session.add(line_item)
                    
                    # Создаем связь с заказом
                    for _ in range(quantity):
                        order_item = OrderLineItem(
                            order_id=order.id,
                            line_item_id=line_item.id
                        )
                        self.session.add(order_item)
            
            self.session.commit()
            return order
            
        except Exception as e:
            self.session.rollback()
            raise ValueError(f"Ошибка при создании заказа: {str(e)}") 