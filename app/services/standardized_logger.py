"""
Стандартизированная система логирования для операций синхронизации складских остатков.

Этот модуль предоставляет централизованные методы логирования для обеспечения
последовательности и структурированности логов во всем сервисе синхронизации.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from sqlmodel import Session

from app.models.stock_synchronization import (
    StockSynchronizationLog,
    OperationStatus,
    LogAction
)


class ValidationResult:
    """Результат валидации для стандартизированного логирования."""
    
    def __init__(
        self,
        valid: bool,
        total_items: int = 0,
        valid_items: int = 0,
        invalid_items: int = 0,
        error_summary: Optional[Dict[str, Any]] = None,
        validation_details: Optional[Dict[str, Any]] = None
    ):
        self.valid = valid
        self.total_items = total_items
        self.valid_items = valid_items
        self.invalid_items = invalid_items
        self.error_summary = error_summary or {}
        self.validation_details = validation_details or {}


class StandardizedLogger:
    """
    Централизованная система логирования для операций синхронизации.
    
    Обеспечивает последовательное и структурированное логирование всех действий
    в процессе синхронизации складских остатков.
    """
    
    def __init__(self, session: Session):
        """
        Инициализация логгера.
        
        Args:
            session: Сессия базы данных для записи логов
        """
        self.session = session
        self.logger = logging.getLogger("stock.sync.standardized")
    
    def log_status_transition(
        self,
        operation_id: UUID,
        from_status: OperationStatus,
        to_status: OperationStatus,
        reason: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Логирование переходов между статусами операций.
        
        Args:
            operation_id: ID операции
            from_status: Исходный статус
            to_status: Целевой статус
            reason: Причина перехода
            additional_context: Дополнительный контекст
        """
        try:
            details = {
                "from_status": from_status.value,
                "to_status": to_status.value,
                "reason": reason,
                "transition": f"{from_status.value} -> {to_status.value}"
            }
            
            if additional_context:
                details.update(additional_context)
            
            # Определяем уровень статуса на основе типа перехода
            status = "info"
            if to_status in [OperationStatus.FAILED, OperationStatus.CANCELLED]:
                status = "warning"
            elif to_status == OperationStatus.COMPLETED:
                status = "info"
            
            log_entry = StockSynchronizationLog(
                operation_id=operation_id,
                action=LogAction.STATUS_TRANSITION.value,
                status=status,
                details=details
            )
            
            self.session.add(log_entry)
            self.session.commit()
            
            # Также логируем в стандартный logger
            self.logger.info(
                f"Status transition for operation {operation_id}: "
                f"{from_status.value} -> {to_status.value} ({reason})"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to log status transition for operation {operation_id}: {e}")
    
    def log_action_with_timing(
        self,
        operation_id: UUID,
        action: LogAction,
        details: str,
        execution_time_ms: Optional[int] = None,
        status: str = "info",
        additional_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Логирование действий с измерением времени выполнения.
        
        Args:
            operation_id: ID операции
            action: Стандартизированное действие из LogAction
            details: Описание действия
            execution_time_ms: Время выполнения в миллисекундах
            status: Уровень статуса (info, warning, error)
            additional_context: Дополнительный контекст
        """
        try:
            log_details = {
                "message": details,
                "action_type": action.value
            }
            
            if execution_time_ms is not None:
                log_details["execution_time_ms"] = execution_time_ms
                log_details["performance_info"] = {
                    "duration_ms": execution_time_ms,
                    "duration_seconds": round(execution_time_ms / 1000, 3)
                }
            
            if additional_context:
                log_details.update(additional_context)
            
            log_entry = StockSynchronizationLog(
                operation_id=operation_id,
                action=action.value,
                status=status,
                details=log_details,
                execution_time_ms=execution_time_ms
            )
            
            self.session.add(log_entry)
            self.session.commit()
            
            # Также логируем в стандартный logger с информацией о времени
            timing_info = f" ({execution_time_ms}ms)" if execution_time_ms else ""
            self.logger.log(
                getattr(logging, status.upper(), logging.INFO),
                f"Operation {operation_id} - {action.value}: {details}{timing_info}"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to log action for operation {operation_id}: {e}")
    
    def log_validation_failure(
        self,
        operation_id: UUID,
        validation_result: ValidationResult
    ) -> None:
        """
        Стандартизированное логирование ошибок валидации.
        
        Args:
            operation_id: ID операции
            validation_result: Результат валидации с детальной информацией
        """
        try:
            validation_details = {
                "validation_status": "failed",
                "total_items": validation_result.total_items,
                "valid_items": validation_result.valid_items,
                "invalid_items": validation_result.invalid_items,
                "success_rate": round(
                    (validation_result.valid_items / validation_result.total_items * 100)
                    if validation_result.total_items > 0 else 0, 2
                ),
                "validation_errors": validation_result.error_summary,
                "items_details": []
            }
            
            # Добавляем детали по каждому товару если доступны
            if validation_result.validation_details:
                for sku, item_validation in validation_result.validation_details.items():
                    if hasattr(item_validation, 'sku'):
                        item_detail = {
                            "sku": item_validation.sku,
                            "warehouse": getattr(item_validation, 'warehouse', None),
                            "required_quantity": getattr(item_validation, 'required_quantity', None),
                            "available_quantity": getattr(item_validation, 'available_quantity', None),
                            "shortage_quantity": getattr(item_validation, 'shortage_quantity', None),
                            "shortage_percentage": getattr(item_validation, 'shortage_percentage', None),
                            "error_message": getattr(item_validation, 'error_message', None),
                            "valid": getattr(item_validation, 'valid', False)
                        }
                        validation_details["items_details"].append(item_detail)
            
            log_entry = StockSynchronizationLog(
                operation_id=operation_id,
                action=LogAction.STOCK_VALIDATION_FAILED.value,
                status="warning",
                details=validation_details
            )
            
            self.session.add(log_entry)
            self.session.commit()
            
            # Также логируем в стандартный logger
            self.logger.warning(
                f"Stock validation failed for operation {operation_id}: "
                f"{validation_result.invalid_items}/{validation_result.total_items} items unavailable"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to log validation failure for operation {operation_id}: {e}")
    
    def log_error_with_context(
        self,
        operation_id: UUID,
        error: Exception,
        context: Dict[str, Any],
        action: Optional[LogAction] = None
    ) -> None:
        """
        Логирование ошибок с контекстной информацией.
        
        Args:
            operation_id: ID операции
            error: Исключение
            context: Контекстная информация
            action: Связанное действие (опционально)
        """
        try:
            error_details = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Добавляем информацию о стеке вызовов если доступна
            if hasattr(error, '__traceback__') and error.__traceback__:
                import traceback
                error_details["traceback"] = traceback.format_exception(
                    type(error), error, error.__traceback__
                )[-5:]  # Последние 5 строк стека
            
            # Используем переданное действие или общее действие ошибки
            log_action = action.value if action else "error_occurred"
            
            log_entry = StockSynchronizationLog(
                operation_id=operation_id,
                action=log_action,
                status="error",
                details=error_details
            )
            
            self.session.add(log_entry)
            self.session.commit()
            
            # Также логируем в стандартный logger
            self.logger.error(
                f"Error in operation {operation_id} ({log_action}): {error}",
                extra={"context": context}
            )
            
        except Exception as e:
            self.logger.error(f"Failed to log error for operation {operation_id}: {e}")
    
    def log_operation_created(
        self,
        operation_id: UUID,
        order_id: str,
        account_name: str,
        warehouse: str,
        operation_type: str
    ) -> None:
        """
        Логирование создания новой операции.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
            account_name: Имя аккаунта
            warehouse: Склад
            operation_type: Тип операции
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.OPERATION_CREATED,
            details=f"Операция создана для заказа {order_id}, аккаунт {account_name}",
            additional_context={
                "order_id": order_id,
                "account_name": account_name,
                "warehouse": warehouse,
                "operation_type": operation_type
            }
        )
    
    def log_retry_scheduled(
        self,
        operation_id: UUID,
        retry_count: int,
        next_retry_at: datetime,
        reason: str
    ) -> None:
        """
        Логирование планирования повторной попытки.
        
        Args:
            operation_id: ID операции
            retry_count: Номер попытки
            next_retry_at: Время следующей попытки
            reason: Причина повтора
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.RETRY_SCHEDULED,
            details=f"Запланирована попытка #{retry_count}: {reason}",
            additional_context={
                "retry_count": retry_count,
                "next_retry_at": next_retry_at.isoformat(),
                "reason": reason
            }
        )
    
    def log_max_retries_reached(
        self,
        operation_id: UUID,
        max_retries: int,
        final_error: Optional[str] = None
    ) -> None:
        """
        Логирование превышения максимального количества попыток.
        
        Args:
            operation_id: ID операции
            max_retries: Максимальное количество попыток
            final_error: Финальная ошибка
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.MAX_RETRIES_REACHED,
            details=f"Превышен лимит попыток ({max_retries})",
            status="error",
            additional_context={
                "max_retries": max_retries,
                "final_error": final_error
            }
        ) 
   
    def log_line_items_loading(
        self,
        operation_id: UUID,
        order_id: str,
        account_name: str
    ) -> None:
        """
        Логирование начала загрузки позиций заказа.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
            account_name: Имя аккаунта
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.LINE_ITEMS_LOADING,
            details=f"Загрузка позиций заказа из микросервиса для заказа {order_id} (аккаунт: {account_name})",
            additional_context={
                "order_id": order_id,
                "account_name": account_name
            }
        )
    
    def log_line_items_loaded(
        self,
        operation_id: UUID,
        order_id: str,
        items_count: int,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование успешной загрузки позиций заказа.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
            items_count: Количество загруженных позиций
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.LINE_ITEMS_LOADED,
            details=f"Загружено {items_count} позиций заказа для заказа {order_id}",
            execution_time_ms=execution_time_ms,
            additional_context={
                "order_id": order_id,
                "items_count": items_count
            }
        )
    
    def log_line_items_load_failed(
        self,
        operation_id: UUID,
        order_id: str,
        error_message: str,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование ошибки загрузки позиций заказа.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
            error_message: Сообщение об ошибке
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.LINE_ITEMS_LOAD_FAILED,
            details=f"Не удалось загрузить позиции заказа: {error_message}",
            execution_time_ms=execution_time_ms,
            status="error",
            additional_context={
                "order_id": order_id,
                "error_message": error_message
            }
        )
    
    def log_stock_validation_started(
        self,
        operation_id: UUID,
        warehouse: str,
        items_count: int
    ) -> None:
        """
        Логирование начала валидации остатков.
        
        Args:
            operation_id: ID операции
            warehouse: Склад
            items_count: Количество позиций для валидации
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.STOCK_VALIDATION_STARTED,
            details=f"Начата валидация остатков для {items_count} позиций на складе {warehouse}",
            additional_context={
                "warehouse": warehouse,
                "items_count": items_count
            }
        )
    
    def log_stock_validation_passed(
        self,
        operation_id: UUID,
        items_count: int,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование успешной валидации остатков.
        
        Args:
            operation_id: ID операции
            items_count: Количество валидированных позиций
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.STOCK_VALIDATION_PASSED,
            details=f"Валидация остатков пройдена для {items_count} позиций",
            execution_time_ms=execution_time_ms,
            additional_context={
                "items_count": items_count
            }
        )
    
    def log_stock_deduction_started(
        self,
        operation_id: UUID,
        warehouse: str,
        items_count: int
    ) -> None:
        """
        Логирование начала списания остатков.
        
        Args:
            operation_id: ID операции
            warehouse: Склад
            items_count: Количество позиций для списания
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.STOCK_DEDUCTION_STARTED,
            details=f"Начато списание остатков для {items_count} позиций со склада {warehouse}",
            additional_context={
                "warehouse": warehouse,
                "items_count": items_count
            }
        )
    
    def log_stock_deduction_completed(
        self,
        operation_id: UUID,
        sku: str,
        quantity: int,
        warehouse: str,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование успешного списания остатков для конкретной позиции.
        
        Args:
            operation_id: ID операции
            sku: SKU товара
            quantity: Количество
            warehouse: Склад
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.STOCK_DEDUCTION_COMPLETED,
            details=f"Успешно списано {quantity} единиц товара {sku} со склада {warehouse}",
            execution_time_ms=execution_time_ms,
            additional_context={
                "sku": sku,
                "quantity": quantity,
                "warehouse": warehouse
            }
        )
    
    def log_stock_deduction_failed(
        self,
        operation_id: UUID,
        error_message: str,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование ошибки списания остатков.
        
        Args:
            operation_id: ID операции
            error_message: Сообщение об ошибке
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.STOCK_DEDUCTION_FAILED,
            details=f"Ошибка списания остатков: {error_message}",
            execution_time_ms=execution_time_ms,
            status="error",
            additional_context={
                "error_message": error_message
            }
        )
    
    def log_microservice_sync_started(
        self,
        operation_id: UUID,
        order_id: str
    ) -> None:
        """
        Логирование начала синхронизации с микросервисом.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.MICROSERVICE_SYNC_STARTED,
            details=f"Начата синхронизация с микросервисом для заказа {order_id}",
            additional_context={
                "order_id": order_id
            }
        )
    
    def log_microservice_sync_success(
        self,
        operation_id: UUID,
        order_id: str,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование успешной синхронизации с микросервисом.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.MICROSERVICE_SYNC_SUCCESS,
            details=f"Синхронизация с микросервисом успешна для заказа {order_id}",
            execution_time_ms=execution_time_ms,
            additional_context={
                "order_id": order_id
            }
        )
    
    def log_microservice_sync_failed(
        self,
        operation_id: UUID,
        order_id: str,
        error_message: str,
        execution_time_ms: Optional[int] = None
    ) -> None:
        """
        Логирование ошибки синхронизации с микросервисом.
        
        Args:
            operation_id: ID операции
            order_id: ID заказа
            error_message: Сообщение об ошибке
            execution_time_ms: Время выполнения
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.MICROSERVICE_SYNC_FAILED,
            details=f"Синхронизация с микросервисом провалена: {error_message}",
            execution_time_ms=execution_time_ms,
            status="error",
            additional_context={
                "order_id": order_id,
                "error_message": error_message
            }
        )
    
    def log_account_name_updated(
        self,
        operation_id: UUID,
        account_name: str
    ) -> None:
        """
        Логирование обновления имени аккаунта.
        
        Args:
            operation_id: ID операции
            account_name: Новое имя аккаунта
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.ACCOUNT_NAME_UPDATED,
            details=f"Имя аккаунта обновлено на: {account_name}",
            additional_context={
                "account_name": account_name
            }
        )
    
    def log_operation_failed(
        self,
        operation_id: UUID,
        final_error: str,
        retry_count: int
    ) -> None:
        """
        Логирование окончательного провала операции.
        
        Args:
            operation_id: ID операции
            final_error: Финальная ошибка
            retry_count: Количество попыток
        """
        self.log_action_with_timing(
            operation_id=operation_id,
            action=LogAction.OPERATION_FAILED,
            details=f"Операция провалена после {retry_count} попыток: {final_error}",
            status="error",
            additional_context={
                "final_error": final_error,
                "retry_count": retry_count
            }
        )


def get_standardized_logger(session: Session) -> StandardizedLogger:
    """
    Фабричная функция для создания экземпляра StandardizedLogger.
    
    Args:
        session: Сессия базы данных
        
    Returns:
        StandardizedLogger: Настроенный экземпляр логгера
    """
    return StandardizedLogger(session)