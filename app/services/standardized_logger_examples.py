"""
Примеры использования StandardizedLogger в сервисе синхронизации складских остатков.

Этот файл содержит примеры того, как правильно использовать стандартизированную
систему логирования для замены существующих вызовов _log_operation.
"""

from datetime import datetime
from uuid import UUID
from sqlmodel import Session

from app.services.standardized_logger import StandardizedLogger, ValidationResult, get_standardized_logger
from app.models.stock_synchronization import OperationStatus, LogAction


class StockSynchronizationServiceExample:
    """
    Пример интеграции StandardizedLogger в StockSynchronizationService.
    
    Показывает, как заменить существующие вызовы _log_operation на
    стандартизированные методы логирования.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.standardized_logger = get_standardized_logger(session)
    
    def create_operation_example(self, operation_id: UUID, order_id: str, account_name: str):
        """Пример логирования создания операции."""
        
        # СТАРЫЙ СПОСОБ:
        # self._log_operation(
        #     operation.id,
        #     "created",
        #     f"Операция создана для заказа {order_id}, аккаунт {account_name}"
        # )
        
        # НОВЫЙ СПОСОБ:
        self.standardized_logger.log_operation_created(
            operation_id=operation_id,
            order_id=order_id,
            account_name=account_name,
            warehouse="Ирина",
            operation_type="deduction"
        )
    
    def load_line_items_example(self, operation_id: UUID, order_id: str, account_name: str):
        """Пример логирования загрузки позиций заказа."""
        
        # Начало загрузки
        self.standardized_logger.log_line_items_loading(
            operation_id=operation_id,
            order_id=order_id,
            account_name=account_name
        )
        
        try:
            start_time = datetime.utcnow()
            
            # Здесь происходит загрузка line_items...
            line_items = []  # Результат загрузки
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if line_items:
                # Успешная загрузка
                self.standardized_logger.log_line_items_loaded(
                    operation_id=operation_id,
                    order_id=order_id,
                    items_count=len(line_items),
                    execution_time_ms=execution_time
                )
            else:
                # Ошибка загрузки
                self.standardized_logger.log_line_items_load_failed(
                    operation_id=operation_id,
                    order_id=order_id,
                    error_message="Не удалось загрузить позиции заказа из микросервиса",
                    execution_time_ms=execution_time
                )
                
        except Exception as e:
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self.standardized_logger.log_error_with_context(
                operation_id=operation_id,
                error=e,
                context={
                    "order_id": order_id,
                    "account_name": account_name,
                    "action": "load_line_items"
                },
                action=LogAction.LINE_ITEMS_LOAD_FAILED
            )
    
    def validate_stock_example(self, operation_id: UUID, validation_result):
        """Пример логирования валидации остатков."""
        
        # СТАРЫЙ СПОСОБ:
        # validation_details = {
        #     "total_items": validation_result.total_items,
        #     "valid_items": validation_result.valid_items,
        #     "invalid_items": validation_result.invalid_items,
        #     "validation_errors": validation_result.error_summary,
        #     "items_details": []
        # }
        # self._log_operation(
        #     operation.id,
        #     "stock_validation_failed",
        #     f"Провал валидации остатков: {validation_result.invalid_items} из {validation_result.total_items} позиций недоступно",
        #     execution_time_ms=None,
        #     status="warning",
        #     detailed_info=validation_details
        # )
        
        # НОВЫЙ СПОСОБ:
        if validation_result.valid:
            self.standardized_logger.log_stock_validation_passed(
                operation_id=operation_id,
                items_count=validation_result.total_items
            )
        else:
            # Создаем ValidationResult для стандартизированного логирования
            validation_result_obj = ValidationResult(
                valid=validation_result.valid,
                total_items=validation_result.total_items,
                valid_items=validation_result.valid_items,
                invalid_items=validation_result.invalid_items,
                error_summary=validation_result.error_summary,
                validation_details=validation_result.validation_details
            )
            
            self.standardized_logger.log_validation_failure(
                operation_id=operation_id,
                validation_result=validation_result_obj
            )
    
    def deduct_stock_example(self, operation_id: UUID, sku: str, quantity: int, warehouse: str):
        """Пример логирования списания остатков."""
        
        start_time = datetime.utcnow()
        
        try:
            # Здесь происходит списание...
            # inventory_manager.remove_as_sale(sku, warehouse, quantity)
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # СТАРЫЙ СПОСОБ:
            # self._log_operation(
            #     operation.id,
            #     "stock_deducted",
            #     f"Успешно списано {quantity} единиц товара {sku} со склада {warehouse}"
            # )
            
            # НОВЫЙ СПОСОБ:
            self.standardized_logger.log_stock_deduction_completed(
                operation_id=operation_id,
                sku=sku,
                quantity=quantity,
                warehouse=warehouse,
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self.standardized_logger.log_stock_deduction_failed(
                operation_id=operation_id,
                error_message=str(e),
                execution_time_ms=execution_time
            )
    
    def sync_with_microservice_example(self, operation_id: UUID, order_id: str):
        """Пример логирования синхронизации с микросервисом."""
        
        # Начало синхронизации
        self.standardized_logger.log_microservice_sync_started(
            operation_id=operation_id,
            order_id=order_id
        )
        
        start_time = datetime.utcnow()
        
        try:
            # Здесь происходит синхронизация...
            # result = self.orders_client.update_stock_status(...)
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # СТАРЫЙ СПОСОБ:
            # self._log_operation(
            #     operation.id, 
            #     "sync_success", 
            #     "Синхронизация с микросервисом успешна",
            #     execution_time_ms=execution_time
            # )
            
            # НОВЫЙ СПОСОБ:
            self.standardized_logger.log_microservice_sync_success(
                operation_id=operation_id,
                order_id=order_id,
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # СТАРЫЙ СПОСОБ:
            # self._log_operation(
            #     operation.id, 
            #     "sync_failed", 
            #     f"Синхронизация с микросервисом провалена: {str(e)}",
            #     execution_time_ms=execution_time
            # )
            
            # НОВЫЙ СПОСОБ:
            self.standardized_logger.log_microservice_sync_failed(
                operation_id=operation_id,
                order_id=order_id,
                error_message=str(e),
                execution_time_ms=execution_time
            )
    
    def status_transition_example(self, operation_id: UUID):
        """Пример логирования переходов статусов."""
        
        # НОВЫЙ СПОСОБ - логирование переходов статусов:
        self.standardized_logger.log_status_transition(
            operation_id=operation_id,
            from_status=OperationStatus.PENDING,
            to_status=OperationStatus.PROCESSING,
            reason="Line items loaded successfully",
            additional_context={"items_count": 5}
        )
        
        self.standardized_logger.log_status_transition(
            operation_id=operation_id,
            from_status=OperationStatus.PROCESSING,
            to_status=OperationStatus.STOCK_DEDUCTED,
            reason="Stock deduction completed",
            additional_context={"deducted_items": 5}
        )
        
        self.standardized_logger.log_status_transition(
            operation_id=operation_id,
            from_status=OperationStatus.STOCK_DEDUCTED,
            to_status=OperationStatus.COMPLETED,
            reason="Microservice sync successful"
        )
    
    def retry_logic_example(self, operation_id: UUID, retry_count: int):
        """Пример логирования retry логики."""
        
        if retry_count < 5:
            # Планируем следующую попытку
            next_retry_at = datetime.utcnow()  # + delay
            self.standardized_logger.log_retry_scheduled(
                operation_id=operation_id,
                retry_count=retry_count,
                next_retry_at=next_retry_at,
                reason="Previous attempt failed, retrying"
            )
        else:
            # Превышен лимит попыток
            self.standardized_logger.log_max_retries_reached(
                operation_id=operation_id,
                max_retries=5,
                final_error="Connection timeout"
            )
            
            self.standardized_logger.log_operation_failed(
                operation_id=operation_id,
                final_error="Max retries exceeded",
                retry_count=retry_count
            )


# Пример миграции существующего кода
def migration_example():
    """
    Пример того, как мигрировать существующий код на StandardizedLogger.
    """
    
    # БЫЛО:
    def old_log_operation(operation_id, action, details, execution_time_ms=None, status="info"):
        pass
    
    # СТАЛО:
    def new_log_with_standardized_logger(session: Session, operation_id: UUID):
        logger = get_standardized_logger(session)
        
        # Вместо общих действий используем специфичные методы
        logger.log_operation_created(
            operation_id=operation_id,
            order_id="12345",
            account_name="Test Account",
            warehouse="Ирина",
            operation_type="deduction"
        )
        
        # Вместо ручного измерения времени используем встроенную поддержку
        logger.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.STOCK_DEDUCTION_STARTED,
            details="Starting stock deduction",
            execution_time_ms=150
        )


# Рекомендации по миграции:
"""
1. Замените все вызовы self._log_operation на соответствующие методы StandardizedLogger
2. Используйте стандартизированные действия из LogAction enum
3. Добавьте логирование переходов статусов с помощью log_status_transition
4. Используйте специализированные методы для конкретных действий
5. Добавьте измерение времени выполнения для критических операций
6. Используйте log_error_with_context для детального логирования ошибок
"""