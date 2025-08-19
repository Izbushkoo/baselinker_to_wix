"""
 * @file: low_price_sale_checker.py
 * @description: Сервис для проверки цен продаж на соответствие минимальным ценам
 * @dependencies: PricesService, StandardizedLogger, app.schemas.low_price_violations
 * @created: 2025-01-15
"""

from typing import List, Dict, Any, Optional
from decimal import Decimal
import logging

from app.services.prices_service import PricesService, PriceDataResponse
from app.services.standardized_logger import StandardizedLogger, LogAction
from app.schemas.low_price_violations import LowPriceViolation, LowPriceViolationSummary
from app.core.stock_sync_config import stock_sync_config


class LowPriceSaleChecker:
    """
    Сервис для проверки цен продаж на соответствие минимальным ценам
    """
    
    def __init__(self, prices_service: PricesService, logger: StandardizedLogger):
        self.prices_service = prices_service
        self.standardized_logger = logger
        self.logger = logging.getLogger("low_price_checker")
    
    def check_order_prices(self, operation: Dict[str, Any]) -> Optional[LowPriceViolationSummary]:
        """
        Проверяет цены заказа на соответствие минимальным ценам.
        
        Args:
            operation: Операция с данными заказа
            
        Returns:
            LowPriceViolationSummary или None если нет нарушений
        """
        line_items = operation.get('line_items', [])
        if not line_items:
            return None
            
        if not stock_sync_config.price_checking_enabled:
            return None
            
        if not self.prices_service.is_available():
            self.standardized_logger.log_action_with_timing(
                operation_id=operation.get("id"),
                action=LogAction.PRICE_SERVICE_UNAVAILABLE,
                details="PricesService недоступен, пропускаем проверку цен",
                additional_context={
                    "order_id": operation.get("order_id"),
                    "service_status": "unavailable"
                }
            )
            return []
        
        if not line_items:
            return []
        
        self.standardized_logger.log_action_with_timing(
            operation_id=operation.get("id"),
            action=LogAction.PRICE_CHECK_STARTED,
            details="Начинаем проверку цен для заказа",
            additional_context={
                "order_id": operation.get("order_id"),
                "line_items_count": len(line_items)
            }
        )
        
        violations = []
        
        # Получаем все SKU из заказа для батчевого запроса
        skus = []
        for item in line_items:
            sku = self._extract_sku(item)
            if sku:
                skus.append(sku)
        
        if not skus:
            return None
        
        # Получаем минимальные цены для всех SKU
        prices_by_sku = self.prices_service.get_prices_by_skus(skus)
        
        for line_item in line_items:
            sku = self._extract_sku(line_item)
            if not sku:
                continue
                
            sale_price = self._extract_sale_price(line_item)
            if not sale_price:
                continue
                
            product_name = self._extract_product_name(line_item)
            
            # Получаем минимальную цену для SKU
            minimum_price = prices_by_sku.get(sku)
            if not minimum_price:
                continue
                
            # Проверяем нарушение минимальной цены
            violation = self._check_price_for_sku(sku, sale_price, minimum_price.min_price)
            if violation:
                violation.product_name = product_name
                violations.append(violation)
        
        self.standardized_logger.log_action_with_timing(
            operation_id=operation.get("id"),
            action=LogAction.PRICE_CHECK_COMPLETED,
            details="Проверка цен завершена",
            additional_context={
                "order_id": operation.get("order_id"),
                "violations_count": len(violations)
            }
        )
        
        return violations
    
    def _extract_sku(self, line_item: Dict[str, Any]) -> Optional[str]:
        """Извлекает SKU из позиции заказа"""
        try:
            if 'offer' in line_item and 'external' in line_item['offer']:
                return line_item['offer']['external'].get('id')
        except Exception as e:
            self.logger.error(f"Error extracting SKU from line_item: {e}")
        return None
    
    def _extract_sale_price(self, line_item: Dict[str, Any]) -> Optional[Decimal]:
        """Извлекает цену продажи из позиции заказа"""
        try:
            # Сначала проверяем цену с учетом скидок
            if 'price' in line_item and 'amount' in line_item['price']:
                price_str = line_item['price']['amount']
                if price_str:
                    return Decimal(price_str)
            
            # Если нет цены с учетом скидок, берем оригинальную цену
            if 'originalPrice' in line_item and 'amount' in line_item['originalPrice']:
                price_str = line_item['originalPrice']['amount']
                if price_str:
                    return Decimal(price_str)
                    
        except Exception as e:
            self.logger.error(f"Error extracting sale price from line_item: {e}")
        return None
    
    def _extract_product_name(self, line_item: Dict[str, Any]) -> str:
        """Извлекает название продукта из позиции заказа"""
        try:
            if 'offer' in line_item and 'name' in line_item['offer']:
                return line_item['offer']['name']
        except Exception as e:
            self.logger.error(f"Error extracting product name from line_item: {e}")
        return "Неизвестный товар"
    
    def _should_check_price(self, minimum_price: Optional[Decimal]) -> bool:
        """
        Определяет нужно ли проверять цену
        
        Args:
            minimum_price: Минимальная цена
            
        Returns:
            True если нужно проверять, False если пропустить
        """
        return minimum_price is not None and minimum_price > 0
    
    def _check_price_for_sku(self, sku: str, sale_price: Decimal, minimum_price: Optional[Decimal]) -> Optional[LowPriceViolation]:
        """Проверяет цену для конкретного SKU"""
        if not self._should_check_price(minimum_price):
            return None
            
        if sale_price < minimum_price:
            violation_amount = minimum_price - sale_price
            violation_percentage = (violation_amount / minimum_price) * 100
            
            self.logger.warning(
                f"Price violation: SKU {sku}, sale_price {sale_price}, "
                f"minimum_price {minimum_price}, violation_amount {violation_amount}, "
                f"violation_percentage {violation_percentage:.1f}"
            )
            
            return LowPriceViolation(
                sku=sku,
                sale_price=sale_price,
                minimum_price=minimum_price,
                violation_amount=violation_amount,
                violation_percentage=violation_percentage
            )
        
        return None
    
    def _check_line_item_price(
        self, 
        line_item: Dict[str, Any], 
        prices_data: Dict[str, PriceDataResponse]
    ) -> Optional[LowPriceViolation]:
        """
        Проверяет цену одной позиции заказа
        
        Args:
            line_item: Позиция заказа
            prices_data: Словарь минимальных цен по SKU
            
        Returns:
            Объект нарушения или None если нарушений нет
        """
        try:
            # Извлекаем данные из line_item
            sku = self._extract_sku(line_item)
            if not sku:
                return None
            
            sale_price = self._extract_sale_price(line_item)
            if sale_price is None:
                return None
            
            product_name = self._extract_product_name(line_item)
            
            # Получаем минимальную цену
            price_response = prices_data.get(sku)
            if not price_response:
                # Если минимальная цена не найдена, пропускаем проверку
                return None
            
            minimum_price = price_response.min_price
            
            # Проверяем нужно ли проверять цену
            if not self._should_check_price(minimum_price):
                return None
            
            # Проверяем нарушение минимальной цены
            violation = self._check_price_for_sku(sku, sale_price, minimum_price)
            if violation:
                return violation
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error checking price for line_item: {e}")
            return None
    
    def _create_violation_summary(self, violations: List[LowPriceViolation]) -> Optional[LowPriceViolationSummary]:
        """Создает сводку нарушений минимальных цен"""
        if not violations:
            return None
            
        total_violation_amount = sum(violation.violation_amount for violation in violations)
        
        summary = LowPriceViolationSummary(
            violation_count=len(violations),
            total_violation_amount=total_violation_amount,
            violations=violations
        )
        
        return summary
