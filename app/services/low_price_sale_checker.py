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
    
    def check_order_prices(
        self, 
        operation: Dict[str, Any],
        line_items: List[Dict[str, Any]]
    ) -> List[LowPriceViolation]:
        """
        Проверяет цены всех позиций заказа на соответствие минимальным ценам
        
        Args:
            operation: Данные операции
            line_items: Список позиций заказа
            
        Returns:
            Список нарушений минимальных цен
        """
        # Отладочное логирование
        self.logger.info(f"check_order_prices called with operation: {operation}")
        self.logger.info(f"line_items count: {len(line_items) if line_items else 0}")
        self.logger.info(f"price_checking_enabled: {stock_sync_config.price_checking_enabled}")
        self.logger.info(f"prices_service.is_available(): {self.prices_service.is_available()}")
        
        # Проверяем включена ли проверка цен в конфигурации
        if not stock_sync_config.price_checking_enabled:
            self.logger.info("Price checking disabled in config")
            return []
        
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
        
        try:
            # Получаем все SKU из заказа для батчевого запроса
            skus = []
            for item in line_items:
                sku = self._extract_sku(item)
                if sku:
                    skus.append(sku)
            
            if not skus:
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation.get("id"),
                    action=LogAction.PRICE_CHECK_FAILED,
                    details="Не удалось извлечь SKU из позиций заказа",
                    additional_context={
                        "order_id": operation.get("order_id")
                    }
                )
                return []
            
            # Получаем минимальные цены для всех SKU
            prices_data = self.prices_service.get_prices_by_skus(skus)
            
            # Проверяем каждую позицию
            for line_item in line_items:
                violation = self._check_line_item_price(line_item, prices_data)
                if violation:
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
            
        except Exception as e:
            self.standardized_logger.log_action_with_timing(
                operation_id=operation.get("id"),
                action=LogAction.PRICE_CHECK_FAILED,
                details=f"Ошибка при проверке цен: {e}",
                additional_context={
                    "order_id": operation.get("order_id"),
                    "error": str(e)
                }
            )
            # Возвращаем пустой список при ошибке, не блокируя основной процесс
        
        return violations
    
    def _extract_sku(self, line_item: Dict[str, Any]) -> Optional[str]:
        """
        Извлекает SKU из line_item заказа Allegro
        
        Args:
            line_item: Позиция заказа
            
        Returns:
            SKU товара или None если не найден
        """
        try:
            self.logger.info(f"Extracting SKU from line_item: {line_item}")
            
            # Структура line_item из Allegro API
            # offer.external.id содержит SKU
            sku = line_item.get("offer", {}).get("external", {}).get("id")
            
            if sku:
                self.logger.info(f"Found SKU: {sku}")
            else:
                self.logger.info("No SKU found in line_item")
                
            return sku if sku else None
        except Exception as e:
            self.logger.warning(f"Error extracting SKU from line_item: {e}")
            return None
    
    def _extract_sale_price(self, line_item: Dict[str, Any]) -> Optional[Decimal]:
        """
        Извлекает цену продажи из line_item заказа Allegro
        
        Args:
            line_item: Позиция заказа
            
        Returns:
            Цена продажи или None если не найдена
        """
        try:
            self.logger.info(f"Extracting sale price from line_item: {line_item}")
            
            # Приоритет извлечения цены:
            # 1. price.amount (цена со скидкой)
            # 2. originalPrice.amount (оригинальная цена)
            
            # Пытаемся получить цену со скидкой
            price_data = line_item.get("price", {})
            if price_data and "amount" in price_data:
                amount_str = price_data["amount"]
                if amount_str:
                    price = Decimal(str(amount_str))
                    self.logger.info(f"Found sale price (discounted): {price}")
                    return price
            
            # Если цена со скидкой не найдена, берем оригинальную цену
            original_price_data = line_item.get("originalPrice", {})
            if original_price_data and "amount" in original_price_data:
                amount_str = original_price_data["amount"]
                if amount_str:
                    price = Decimal(str(amount_str))
                    self.logger.info(f"Found sale price (original): {price}")
                    return price
            
            self.logger.info("No sale price found in line_item")
            return None
            
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Error parsing price from line_item: {e}")
            return None
    
    def _extract_product_name(self, line_item: Dict[str, Any]) -> str:
        """
        Извлекает название товара из line_item
        
        Args:
            line_item: Позиция заказа
            
        Returns:
            Название товара или "Неизвестный товар"
        """
        try:
            product_name = line_item.get("offer", {}).get("name", "")
            if product_name:
                self.logger.info(f"Found product name: {product_name}")
            else:
                self.logger.info("No product name found, using default")
                product_name = "Неизвестный товар"
            return product_name
        except Exception:
            self.logger.warning("Error extracting product name, using default")
            return "Неизвестный товар"
    
    def _should_check_price(self, minimum_price: Optional[Decimal]) -> bool:
        """
        Определяет нужно ли проверять цену
        
        Args:
            minimum_price: Минимальная цена
            
        Returns:
            True если нужно проверять, False если пропустить
        """
        should_check = minimum_price is not None and minimum_price > 0
        self.logger.info(f"Should check price for minimum_price {minimum_price}: {should_check}")
        return should_check
    
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
                self.logger.info(f"No SKU found in line_item")
                return None
            
            sale_price = self._extract_sale_price(line_item)
            if sale_price is None:
                self.logger.info(f"No sale price found for SKU {sku}")
                return None
            
            product_name = self._extract_product_name(line_item)
            self.logger.info(f"Checking price for SKU {sku}, product: {product_name}, sale_price: {sale_price}")
            
            # Получаем минимальную цену
            price_response = prices_data.get(sku)
            if not price_response:
                self.logger.info(f"No minimum price found for SKU {sku}")
                # Если минимальная цена не найдена, пропускаем проверку
                return None
            
            minimum_price = price_response.min_price
            self.logger.info(f"Minimum price for SKU {sku}: {minimum_price}")
            
            # Проверяем нужно ли проверять цену
            if not self._should_check_price(minimum_price):
                self.logger.info(f"Price checking skipped for SKU {sku} (minimum_price: {minimum_price})")
                return None
            
            # Проверяем нарушение минимальной цены
            if sale_price < minimum_price:
                self.logger.info(f"Price violation detected for SKU {sku}: sale_price {sale_price} < minimum_price {minimum_price}")
                violation = LowPriceViolation(
                    sku=sku,
                    product_name=product_name,
                    sale_price=sale_price,
                    minimum_price=minimum_price
                )
                
                self.logger.warning(f"Price violation: SKU {sku}, sale_price {sale_price}, minimum_price {minimum_price}, violation_amount {violation.violation_amount}, violation_percentage {violation.violation_percentage}")
                
                return violation
            else:
                self.logger.info(f"No price violation for SKU {sku}: sale_price {sale_price} >= minimum_price {minimum_price}")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error checking price for line_item: {e}")
            return None
    
    def create_violation_summary(
        self,
        violations: List[LowPriceViolation],
        account_name: str,
        order_id: str,
        operation_id: Optional[str] = None
    ) -> Optional[LowPriceViolationSummary]:
        """
        Создает сводку по нарушениям минимальных цен
        
        Args:
            violations: Список нарушений
            account_name: Название аккаунта
            order_id: ID заказа
            operation_id: ID операции (опционально)
            
        Returns:
            Сводка нарушений или None если нарушений нет
        """
        if not violations:
            self.logger.info("No violations to create summary for")
            return None
        
        # Вычисляем общую сумму нарушений
        total_violation_amount = sum(violation.violation_amount for violation in violations)
        self.logger.info(f"Creating violation summary: {len(violations)} violations, total amount: {total_violation_amount}")
        
        summary = LowPriceViolationSummary(
            account_name=account_name,
            order_id=order_id,
            operation_id=operation_id,
            violations=violations,
            total_violation_amount=total_violation_amount
        )
        
        self.logger.info(f"Violation summary created: {summary.violation_count} violations, total amount: {summary.total_violation_amount}")
        return summary
