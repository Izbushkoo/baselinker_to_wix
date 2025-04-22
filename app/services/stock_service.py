from sqlmodel import Session, select
from app.models.allegro_order import AllegroOrder, AllegroLineItem, OrderLineItem
from app.services.werehouse.manager import InventoryManager
from app.models.werehouse import Sale
import logging

logger = logging.getLogger(__name__)

class AllegroStockService:
    def __init__(self, db: Session, manager: InventoryManager):
        self.db = db
        self.manager = manager

    def process_order_stock_update(self, order: AllegroOrder, werehouse: str) -> bool:
        """
        Обрабатывает списание товара для заказа Allegro.
        Возвращает True если списание выполнено успешно.
        
        Args:
            order: Заказ Allegro
            warehouse: ID склада с которого производить списание
        """
        try:
            # Проверяем статус и флаг списания
            fulfillment_status = order.fulfillment.get('status')
            if fulfillment_status != 'SENT' or order.is_stock_updated:
                return False

            # Получаем товарные позиции заказа
            order_items_query = (
                select(OrderLineItem)
                .where(OrderLineItem.order_id == order.id)
                .join(AllegroLineItem)
            )
            order_items = self.db.exec(order_items_query).all()

            # Списываем каждую позицию
            for order_item in order_items:
                line_item = order_item.line_item
                # Предполагаем, что external_id это SKU товара
                sku = line_item.external_id
                
                # Получаем остатки по SKU
                stocks = self.manager.get_stock_by_sku(sku)
                if not stocks:
                    logger.warning(f"Товар {sku} не найден на складах")
                    continue
                
                try:
                    # Списываем одну единицу товара с указанного склада
                    self.manager.remove_one(sku, werehouse)
                    logger.info(f"Списана 1 единица товара {sku} со склада {werehouse}")
                    
                    # Создаем запись о продаже
                    sale = Sale(sku=sku, warehouse=werehouse, quantity=1)
                    self.db.add(sale)
                    logger.info(f"Создана запись о продаже товара {sku}")
                    
                except ValueError as e:
                    logger.error(f"Ошибка при списании товара {sku}: {str(e)}")
                    return False

            # Помечаем заказ как обработанный
            order.is_stock_updated = True
            self.db.add(order)
            self.db.commit()
            
            logger.info(f"Успешно обработано списание для заказа {order.id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при обработке списания для заказа {order.id}: {str(e)}")
            self.db.rollback()
            return False 