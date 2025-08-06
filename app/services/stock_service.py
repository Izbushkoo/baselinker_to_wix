import os
from typing import Dict, Any, List, Optional
from uuid import UUID
from app.services.warehouse.manager import InventoryManager
from app.models.warehouse import Sale
import logging
from app.core.security import create_access_token
from app.core.config import settings
from app.services.warehouse.manager import Warehouses
from app.services.tg_client import TelegramManager
from app.services.operations_service import get_operations_service
from app.models.operations import OperationType
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient

logger = logging.getLogger(__name__)

class AllegroStockService:
    def __init__(self, manager: InventoryManager):
        self.manager = manager
        self.tg_manager = TelegramManager(chat_id=os.getenv("NOTIFY_GROUP_ID"))
        self.orders_client = OrdersClient(jwt_token=create_access_token(user_id=settings.PROJECT_NAME))

    def process_order_stock_update(self, order_data: Dict[str, Any], warehouse: str, token_id: UUID, **kwargs) -> bool:
        """
        Обрабатывает списание товара для заказа Allegro.
        Возвращает True если списание выполнено успешно.
        
        Args:
            order_data: Словарь с данными заказа из микросервиса
            warehouse: ID склада с которого производить списание
            token_id: ID токена для обновления статуса через микросервис
        """
        try:
            # Получаем данные из словаря заказа
            token = kwargs.get("token", None)
            order_id = order_data.get("allegro_order_id", None)
            status = order_data.get("status")
            technical_flags = order_data.get("technical_flags", {})
            is_stock_updated = technical_flags.get("is_stock_updated", False)
            fulfillment = order_data.get("fulfillment", {})
            line_items = order_data.get("lineItems", [])

            # Проверяем статус и флаг списания
            if status != 'READY_FOR_PROCESSING' or is_stock_updated:
                logger.info(f"Заказ {order_id} пропущен: статус={status}, is_stock_updated={is_stock_updated}")
                return False

            if fulfillment.get("status") == 'CANCELLED':
                logger.info(f"Заказ {order_id} отменен")
                return False

            if not line_items:
                logger.warning(f"Заказ {order_id} не содержит товарных позиций")
                return False

            # Проверяем наличие всех товаров перед списанием
            for line_item in line_items:
                sku = line_item.get("offer", {}).get("external", {}).get("id")
                if not sku:
                    logger.warning(f"Не найден SKU для товара в заказе {order_id}")
                    continue
                    
                stocks = self.manager.get_stock_by_sku(sku)
                if not stocks:
                    message = f"Аккаунт: '{token.get('account_name') if token else 'Не указан'}'\n❌ Товар с SKU '<code>{sku}</code>' не найден в базе (заказ <code>{order_id}</code>)"
                    logger.warning(message)
                    self.tg_manager.send_message(message)
                    return False
                elif stocks.get(warehouse, 0) == 0:
                    message = f"Аккаунт: '{token.get('account_name') if token else 'Не указан'}'\n⚠️ Товар с SKU '<code>{sku}</code>' есть в базе, но остатки нулевые на складе {warehouse} (заказ <code>{order_id}</code>)\nСписания не произошло"
                    logger.warning(message)
                    self.tg_manager.send_message(message)
                    return False

            # Списываем каждую позицию
            products_data = []
            for line_item in line_items:
                sku = line_item.get("offer", {}).get("external", {}).get("id")
                offer_name = line_item.get("offer", {}).get("name", "")
                quantity = int(line_item.get("quantity", 0))
                
                if not sku:
                    continue
                    
                try:
                    # Списываем товар с указанного склада
                    self.manager.remove_as_sale(sku, warehouse, quantity)
                    
                    products_data.append({
                        "sku": sku,
                        "quantity": quantity,
                        "name": offer_name
                    })
                    
                except ValueError as e:
                    message = f"Аккаунт: '{token.get('account_name') if token else 'Не указан'}'\n❌ Товар с SKU '<code>{sku}</code>' не найден в базе (заказ <code>{order_id}</code>)"
                    logger.warning(message)
                    self.tg_manager.send_message(message)
                    return False

            # Помечаем заказ как обработанный через микросервис API
            try:
                self.orders_client.update_stock_status(
                    token_id=token_id,
                    order_id=order_id,
                    is_stock_updated=True
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении статуса списания через API: {e}")
                # Попытаемся откатить списание товара
                for product in products_data:
                    try:
                        # Возвращаем товар обратно на склад
                        self.manager.add_to_warehouse(product["sku"], warehouse, product["quantity"])
                    except Exception as rollback_error:
                        logger.error(f"Ошибка при откате списания для SKU {product['sku']}: {rollback_error}")
                return False

            # Создаем операцию списания для заказа
            if products_data:
                operations_service = get_operations_service()
                operation = operations_service.create_order_operation(
                    warehouse_id=warehouse,
                    products_data=products_data,
                    order_id=order_id,
                    comment=f"Списание по заказу Allegro {order_id}"
                )
            
            logger.info(f"Успешно обработано списание для заказа {order_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при обработке списания для заказа {order_data.get('allegro_order_id', 'unknown')}: {str(e)}")
            return False

    def mark_order_stock_updated(self, order_data: Dict[str, Any], token_id: UUID, warehouse: str = None) -> bool:
        """
        Проставляет флаг списания товара для заказа Allegro без фактического списания.
        Возвращает True если флаг успешно проставлен.
        
        Args:
            order_data: Словарь с данными заказа из микросервиса
            token_id: ID токена для обновления статуса через микросервис
            warehouse: ID склада (не используется в данном методе)
        """
        
        try:
            # Получаем данные из словаря заказа
            order_id = order_data.get("allegro_order_id") or order_data.get("id")
            status = order_data.get("status")
            technical_flags = order_data.get("technical_flags", {})
            is_stock_updated = technical_flags.get("is_stock_updated", False)

            # Проверяем статус и флаг списания
            if status != 'READY_FOR_PROCESSING' or is_stock_updated:
                logger.info(f"Заказ {order_id} пропущен: статус={status}, is_stock_updated={is_stock_updated}")
                return False

            # Помечаем заказ как обработанный через микросервис API
            try:
                self.orders_client.update_stock_status(
                    token_id=token_id,
                    order_id=order_id,
                    is_stock_updated=True
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении статуса списания через API: {e}")
                return False
            
            logger.info(f"Успешно проставлен флаг списания для заказа {order_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при проставлении флага списания для заказа {order_data.get('allegro_order_id', 'unknown')}: {str(e)}")
            return False

    def get_order_line_items(self, order_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Извлекает товарные позиции из данных заказа.
        
        Args:
            order_data: Словарь с данными заказа из микросервиса
            
        Returns:
            List[Dict]: Список товарных позиций
        """
        return order_data.get("lineItems", [])

    def get_order_technical_flags(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Извлекает технические флаги из данных заказа.
        
        Args:
            order_data: Словарь с данными заказа из микросервиса
            
        Returns:
            Dict: Технические флаги заказа
        """
        return order_data.get("technical_flags", {
            "is_stock_updated": False,
            "has_invoice_created": False,
            "invoice_id": None
        })

    def is_order_ready_for_stock_processing(self, order_data: Dict[str, Any]) -> bool:
        """
        Проверяет, готов ли заказ для обработки списания товара.
        
        Args:
            order_data: Словарь с данными заказа из микросервиса
            
        Returns:
            bool: True если заказ готов для списания
        """
        status = order_data.get("status")
        technical_flags = self.get_order_technical_flags(order_data)
        is_stock_updated = technical_flags.get("is_stock_updated", False)
        fulfillment = order_data.get("fulfillment", {})

        # Проверяем основные условия
        if status != 'READY_FOR_PROCESSING':
            return False
            
        if is_stock_updated:
            return False
            
        if fulfillment.get("status") == 'CANCELLED':
            return False

        return True

    def extract_products_from_order(self, order_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Извлекает информацию о товарах из заказа для последующего списания.
        
        Args:
            order_data: Словарь с данными заказа из микросервиса
            
        Returns:
            List[Dict]: Список товаров с SKU, названием и количеством
        """
        products = []
        line_items = self.get_order_line_items(order_data)
        
        for line_item in line_items:
            sku = line_item.get("offer", {}).get("external", {}).get("id")
            offer_name = line_item.get("offer", {}).get("name", "")
            quantity = int(line_item.get("quantity", 1))
            
            if sku:
                products.append({
                    "sku": sku,
                    "name": offer_name,
                    "quantity": quantity
                })
                
        return products