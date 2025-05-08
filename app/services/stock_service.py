import os
from sqlmodel import Session, select
from app.models.allegro_order import AllegroOrder, AllegroLineItem, OrderLineItem
from app.services.warehouse.manager import InventoryManager
from app.models.warehouse import Sale
import logging
from app.services.warehouse.manager import Warehouses
from app.services.tg_client import TelegramManager
from app.services.operations_service import get_operations_service
from app.models.operations import OperationType

logger = logging.getLogger(__name__)

class AllegroStockService:
    def __init__(self, db: Session, manager: InventoryManager):
        self.db = db
        self.manager = manager
        self.tg_manager = TelegramManager(chat_id=os.getenv("NOTIFY_GROUP_ID"))

    def process_order_stock_update(self, order: AllegroOrder, warehouse: str) -> bool:
        """
        Обрабатывает списание товара для заказа Allegro.
        Возвращает True если списание выполнено успешно.
        
        Args:
            order: Заказ Allegro
            warehouse: ID склада с которого производить списание
        """
        try:
            # Проверяем статус и флаг списания
            if order.status != 'READY_FOR_PROCESSING' or order.is_stock_updated:
                return False

            if order.fulfillment.get("status") == 'CANCELLED':
                return False

            # Получаем товарные позиции заказа
            order_items_query = (
                select(OrderLineItem)
                .where(OrderLineItem.order_id == order.id)
                .join(AllegroLineItem)
            )
            order_items = self.db.exec(order_items_query).all()
            # Проверяем наличие всех товаров перед списанием
            for order_item in order_items:
                line_item = order_item.line_item
                sku = line_item.external_id
                stocks = self.manager.get_stock_by_sku(sku)
                if not stocks:
                    message = f"❌ Товар с SKU '<code>{sku}</code>' не найден в базе (заказ <code>{order.id}</code>)"
                    logger.warning(message)
                    self.tg_manager.send_message(message)
                    return False
                elif stocks.get(Warehouses.A.value, 0) == 0:
                    message = f"⚠️ Товар с SKU '<code>{sku}</code>' есть в базе, но остатки нулевые на складе {Warehouses.A.value} (заказ <code>{order.id}</code>)\nСписания не произошло"
                    logger.warning(message)
                    self.tg_manager.send_message(message)
                    return False

            # Списываем каждую позицию
            for order_item in order_items:
                line_item = order_item.line_item
                sku = line_item.external_id
                
                try:
                    # Списываем одну единицу товара с указанного склада
                    self.manager.remove_as_sale(sku, warehouse, 1)
                    
                except ValueError as e:
                    message = f"❌ Товар с SKU '<code>{sku}</code>' не найден в базе (заказ <code>{order.id}</code>)"
                    logger.warning(message)
                    self.tg_manager.send_message(message)
                    return False

            # Помечаем заказ как обработанный
            order.is_stock_updated = True
            self.db.add(order)
            self.db.commit()

            # Создаем операцию списания для заказа
            operations_service = get_operations_service()
            products_data = [
                {
                    "sku": item.line_item.external_id,
                    "quantity": 1,
                    "name": item.line_item.offer_name
                } for item in order_items
            ]
            
            operation = operations_service.create_order_operation(
                warehouse_id=warehouse,
                products_data=products_data,
                order_id=order.id,
                comment=f"Списание по заказу Allegro {order.id}"
            )
            
            logger.info(f"Успешно обработано списание для заказа {order.id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при обработке списания для заказа {order.id}: {str(e)}")
            self.db.rollback()
            return False 

    def mark_order_stock_updated(self, order: AllegroOrder, warehouse: str = None) -> bool:
        """
        Проставляет флаг списания товара для заказа Allegro без фактического списания.
        Возвращает True если флаг успешно проставлен.
        
        Args:
            order: Заказ Allegro
        """
        
        try:
            # Проверяем статус и флаг списания
            if order.status != 'READY_FOR_PROCESSING' or order.is_stock_updated:
                return False

            # Помечаем заказ как обработанный
            order.is_stock_updated = True
            self.db.add(order)
            self.db.commit()
            
            logger.info(f"Успешно проставлен флаг списания для заказа {order.id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при проставлении флага списания для заказа {order.id}: {str(e)}")
            self.db.rollback()
            return False 