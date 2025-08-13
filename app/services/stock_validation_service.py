import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import Session

from app.services.warehouse.manager import InventoryManager
from app.core.stock_sync_config import stock_sync_config
from app.schemas.stock_synchronization import (
    StockValidationResult, 
    OrderValidationResult
)

class StockValidationService:
    """
    Сервис для валидации складских остатков перед синхронизацией.
    Проверяет доступность товаров и корректность данных.
    """
    
    def __init__(
        self, 
        session: Session, 
        inventory_manager: InventoryManager
    ):
        self.session = session
        self.inventory_manager = inventory_manager
        self.logger = logging.getLogger("stock.validation")
        self.config = stock_sync_config
    
    def validate_stock_deduction(
        self,
        sku: str,
        warehouse: str,
        required_quantity: int,
        check_reserved: bool = False
    ) -> StockValidationResult:
        """
        Валидация возможности списания товара с указанного склада.
        
        Args:
            sku: SKU товара
            warehouse: Склад для списания
            required_quantity: Требуемое количество
            check_reserved: Проверять ли зарезервированные остатки
            
        Returns:
            StockValidationResult с результатом валидации
        """
        try:
            # Получаем остатки товара на складе
            stock_data = self.inventory_manager.get_stock_by_sku(sku)
            available_quantity = stock_data.get(warehouse, 0)
            
            # Базовая проверка наличия товара
            if not stock_data:
                return StockValidationResult(
                    valid=False,
                    sku=sku,
                    warehouse=warehouse,
                    available_quantity=0,
                    required_quantity=required_quantity,
                    error_message=f"Товар с SKU '{sku}' не найден в системе"
                )
            
            # Проверка наличия на конкретном складе
            if warehouse not in stock_data:
                return StockValidationResult(
                    valid=False,
                    sku=sku,
                    warehouse=warehouse,
                    available_quantity=0,
                    required_quantity=required_quantity,
                    error_message=f"Товар '{sku}' отсутствует на складе '{warehouse}'"
                )
            
            # Проверка количества
            if available_quantity < required_quantity:
                return StockValidationResult(
                    valid=False,
                    sku=sku,
                    warehouse=warehouse,
                    available_quantity=available_quantity,
                    required_quantity=required_quantity,
                    error_message=f"Недостаточно товара на складе '{warehouse}'. Доступно: {available_quantity}, требуется: {required_quantity}"
                )
            
            # Проверка критических остатков (warning)
            warnings = []
            if available_quantity <= self.config.validation_low_stock_threshold:
                warnings.append(f"Критически низкий остаток товара '{sku}' на складе '{warehouse}': {available_quantity} шт.")
            
            # Валидация успешна
            return StockValidationResult(
                valid=True,
                sku=sku,
                warehouse=warehouse,
                available_quantity=available_quantity,
                required_quantity=required_quantity,
                error_message=""
            )
            
        except Exception as e:
            self.logger.error(f"Ошибка валидации товара {sku} на складе {warehouse}: {e}")
            return StockValidationResult(
                valid=False,
                sku=sku,
                warehouse=warehouse,
                available_quantity=0,
                required_quantity=required_quantity,
                error_message=f"Системная ошибка валидации: {str(e)}"
            )
    
    def validate_order_stock_availability(
        self,
        order_data: Dict[str, Any],
        warehouse: str = "Ирина"
    ) -> OrderValidationResult:
        """
        Валидация доступности всех товаров в заказе.
        
        Args:
            order_data: Данные заказа из микросервиса
            warehouse: Склад для проверки
            
        Returns:
            OrderValidationResult с детальной информацией по каждому товару
        """
        result = OrderValidationResult(valid=True)
        # logger.info(f"order Data in validate_order_stock_availability: {order_data}")
        line_items = order_data.get("lineItems", [])
        
        if not line_items:
            result.valid = False
            result.error_summary.append("Заказ не содержит товарных позиций")
            return result
        
        # Валидируем каждую позицию заказа
        for line_item in line_items:
            sku = line_item.get("offer", {}).get("external", {}).get("id")
            quantity = int(line_item.get("quantity", 1))
            offer_name = line_item.get("offer", {}).get("name", "")
            
            result.total_items += 1
            
            if not sku:
                validation_result = StockValidationResult(
                    valid=False,
                    sku="unknown",
                    warehouse=warehouse,
                    available_quantity=0,
                    required_quantity=quantity,
                    error_message="Отсутствует SKU в данных товара"
                )
                result.validation_details[f"item_{result.total_items}"] = validation_result
                result.invalid_items += 1
                result.error_summary.append(f"Товар '{offer_name}': отсутствует SKU")
                continue
            
            # Валидируем конкретный товар
            validation_result = self.validate_stock_deduction(
                sku=sku,
                warehouse=warehouse,
                required_quantity=quantity
            )
            
            result.validation_details[sku] = validation_result
            
            if validation_result.valid:
                result.valid_items += 1
            else:
                result.invalid_items += 1
                result.error_summary.append(f"Товар '{sku}': {validation_result.error_message}")
        
        # Общий результат валидации заказа
        result.valid = result.invalid_items == 0
        
        # Логируем результат
        if result.valid:
            self.logger.info(f"Валидация заказа {order_data.get('id', 'unknown')} успешна: {result.valid_items} позиций проверено")
        else:
            self.logger.warning(f"Валидация заказа {order_data.get('id', 'unknown')} провалена: {result.invalid_items} из {result.total_items} позиций недоступны")
        
        return result
    
    def validate_bulk_stock_operations(
        self,
        operations: List[Dict[str, Any]],
        warehouse: str = "Ирина"
    ) -> List[StockValidationResult]:
        """
        Массовая валидация операций списания.
        
        Args:
            operations: Список операций [{sku, quantity, ...}, ...]
            warehouse: Склад для проверки
            
        Returns:
            List[StockValidationResult] результаты для каждой операции
        """
        results = []
        
        for operation in operations:
            sku = operation.get("sku")
            quantity = operation.get("quantity", 1)
            
            if not sku:
                results.append(StockValidationResult(
                    valid=False,
                    sku="unknown",
                    warehouse=warehouse,
                    available_quantity=0,
                    required_quantity=quantity,
                    error_message="Отсутствует SKU в операции"
                ))
                continue
            
            validation_result = self.validate_stock_deduction(
                sku=sku,
                warehouse=warehouse,
                required_quantity=quantity
            )
            
            results.append(validation_result)
        
        # Логируем статистику
        valid_count = sum(1 for r in results if r.valid)
        invalid_count = len(results) - valid_count
        
        self.logger.info(f"Массовая валидация завершена: {valid_count} успешных, {invalid_count} провальных из {len(results)} операций")
        
        return results
    
    def get_stock_availability_report(
        self,
        sku_list: List[str],
        warehouse: str = "Ирина"
    ) -> Dict[str, StockValidationResult]:
        """
        Отчет о доступности товаров на складе.
        
        Args:
            sku_list: Список SKU для проверки
            warehouse: Склад для проверки
            
        Returns:
            Dict[str, StockValidationResult] отчет по каждому SKU
        """
        report = {}
        
        for sku in sku_list:
            # Проверяем доступность с минимальным количеством
            validation_result = self.validate_stock_deduction(
                sku=sku,
                warehouse=warehouse,
                required_quantity=1
            )
            
            report[sku] = validation_result
        
        return report
    
    def check_warehouse_health(
        self,
        warehouse: str = "Ирина"
    ) -> Dict[str, Any]:
        """
        Проверка "здоровья" склада - общая статистика остатков.
        
        Args:
            warehouse: Склад для проверки
            
        Returns:
            Dict с различными метриками склада
        """
        try:
            # Получаем все товары на складе через inventory manager
            # (нужно будет добавить метод получения всех остатков по складу)
            
            health_info = {
                "warehouse": warehouse,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "healthy",
                "total_skus": 0,
                "zero_stock_skus": 0,
                "low_stock_skus": 0,
                "warnings": []
            }
            
            # Здесь можно добавить более детальную логику проверки здоровья склада
            # Пока возвращаем базовую структуру
            
            return health_info
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке здоровья склада {warehouse}: {e}")
            return {
                "warehouse": warehouse,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "error",
                "error": str(e)
            }
    
    def pre_sync_validation(
        self,
        token_id: str,
        order_id: str,
        sku: str,
        quantity: int,
        warehouse: str = "Ирина"
    ) -> StockValidationResult:
        """
        Валидация перед синхронизацией конкретной операции.
        Включает дополнительные проверки для синхронизации.
        
        Args:
            token_id: ID токена
            order_id: ID заказа
            sku: SKU товара
            quantity: Количество
            warehouse: Склад
            
        Returns:
            StockValidationResult с дополнительной информацией для синхронизации
        """
        # Базовая валидация
        result = self.validate_stock_deduction(sku, warehouse, quantity)
        
        if result.valid:
            self.logger.info(f"Pre-sync валидация успешна для заказа {order_id}, SKU {sku}, количество {quantity}")
        else:
            self.logger.warning(f"Pre-sync валидация провалена для заказа {order_id}: {result.error_message}")
        
        return result