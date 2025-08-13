import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select
from uuid import UUID

from app.models.stock_synchronization import (
    PendingStockOperation,
    StockSynchronizationLog,
    OperationType,
    OperationStatus
)
from app.schemas.stock_synchronization import (
    SyncResult,
    ProcessingResult,
    ReconciliationResult,
    SyncStatistics
)
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.services.warehouse.manager import InventoryManager, get_manager
from app.services.stock_validation_service import StockValidationService
from app.services.stock_sync_notifications import get_notification_service
from app.core.stock_sync_config import stock_sync_config
from app.core.security import create_access_token
from app.core.config import settings


jwt_token = create_access_token(user_id=settings.PROJECT_NAME)


class StockSynchronizationService:
    """
    Основной сервис для синхронизации складских операций между
    локальной системой и микросервисом Allegro.
    """
    
    def __init__(
        self,
        session: Session,
        orders_client: Optional[OrdersClient] = None,
        tokens_client: Optional[AllegroTokenMicroserviceClient] = None,
        inventory_manager: Optional[InventoryManager] = None
    ):
        self.session = session
        self.orders_client = orders_client or OrdersClient(jwt_token=jwt_token)
        self.tokens_client = tokens_client or AllegroTokenMicroserviceClient(jwt_token=jwt_token)
        self.inventory_manager = inventory_manager or get_manager()
        self.validation_service = StockValidationService(session, self.inventory_manager)
        self.notification_service = get_notification_service(session)
        self.logger = logging.getLogger("stock.sync")
        self.config = stock_sync_config
    
    def _get_account_name_by_token_id(self, token_id: str) -> str:
        """Получение имени аккаунта по token_id из микросервиса."""
        try:
            token_response = self.tokens_client.get_token(UUID(token_id))
            if token_response and hasattr(token_response, 'account_name'):
                return token_response.account_name
            return f"Unknown({token_id})"
        except Exception as e:
            self.logger.warning(f"Failed to get account name for token {token_id}: {e}")
            return f"Unknown({token_id})"
    
    def create_order_processing_operation(
        self,
        token_id: str,
        order_id: str,
        warehouse: str = "Ирина"
    ) -> SyncResult:
        """
        Создание операции обработки заказа для последующей обработки системой синхронизации.
        Детали заказа будут получены позже при обработке.
        
        Args:
            token_id: ID токена Allegro из микросервиса
            order_id: ID заказа
            warehouse: Склад для списания
            
        Returns:
            SyncResult с информацией о созданной операции
        """
        operation_id = None
        account_name = self._get_account_name_by_token_id(token_id)
        
        try:
            # Создаем запись операции без данных заказа (будут загружены при обработке)
            operation = PendingStockOperation(
                order_id=order_id,
                operation_type=OperationType.DEDUCTION,
                warehouse=warehouse,
                token_id=token_id,
                account_name=account_name,
                next_retry_at=datetime.utcnow() + timedelta(seconds=self.config.retry_initial_delay)
            )
            self.session.add(operation)
            self.session.commit()
            operation_id = operation.id
            
            self._log_operation(
                operation.id,
                "created",
                f"Операция создана для заказа {order_id}, аккаунт {account_name}"
            )
            
            return SyncResult(
                success=True,
                operation_id=operation_id,
                details={"account_name": account_name, "queued_for_processing": True}
            )
                
        except Exception as e:
            self.logger.error(f"Error creating order processing operation for account {account_name}: {e}")
            if operation_id:
                self._log_operation(operation_id, "error", f"Исключение: {str(e)}")
            return SyncResult(
                success=False,
                operation_id=operation_id,
                error=str(e),
                details={"account_name": account_name}
            )

    def update_operation_account_name(self, operation: PendingStockOperation) -> bool:
        """
        Обновляет поле account_name для существующей операции.
        
        Args:
            operation: Операция для обновления
            
        Returns:
            bool: True если обновление прошло успешно
        """
        try:
            if not operation.account_name:
                account_name = self._get_account_name_by_token_id(operation.token_id)
                operation.account_name = account_name
                operation.updated_at = datetime.utcnow()
                self.session.commit()
                
                self._log_operation(
                    operation.id,
                    "account_name_updated",
                    f"Имя аккаунта обновлено на: {account_name}"
                )
                return True
            return True
        except Exception as e:
            self.logger.error(f"Error updating account name for operation {operation.id}: {e}")
            return False

    def create_stock_deduction_operation(
        self,
        token_id: str,
        order_id: str,
        sku: str,
        quantity: int,
        warehouse: str = "Ирина"
    ) -> SyncResult:
        """
        Создание операции списания для последующей обработки системой синхронизации.
        
        Args:
            token_id: ID токена Allegro из микросервиса
            order_id: ID заказа
            sku: SKU товара
            quantity: Количество для списания
            warehouse: Склад для списания
            
        Returns:
            SyncResult с информацией о созданной операции
        """
        operation_id = None
        account_name = self._get_account_name_by_token_id(token_id)
        
        try:
            # Создаем запись операции со старой логикой (для совместимости)
            operation = PendingStockOperation(
                order_id=order_id,
                operation_type=OperationType.DEDUCTION,
                warehouse=warehouse,
                token_id=token_id,
                account_name=account_name,
                next_retry_at=datetime.utcnow() + timedelta(seconds=self.config.retry_initial_delay),
                line_items=[{
                    "offer": {"external": {"id": sku}},
                    "quantity": quantity
                }]
            )
            self.session.add(operation)
            self.session.commit()
            operation_id = operation.id
            
            self._log_operation(
                operation.id,
                "created",
                f"Операция создана для заказа {order_id}, аккаунт {account_name}"
            )
            
            return SyncResult(
                success=True,
                operation_id=operation_id,
                details={"account_name": account_name, "queued_for_processing": True}
            )
                
        except Exception as e:
            self.logger.error(f"Error creating stock deduction operation for account {account_name}: {e}")
            if operation_id:
                self._log_operation(operation_id, "error", f"Исключение: {str(e)}")
            return SyncResult(
                success=False,
                operation_id=operation_id,
                error=str(e),
                details={"account_name": account_name}
            )

    def sync_stock_deduction(
        self,
        token_id: str,
        order_id: str,
        sku: str,
        quantity: int,
        warehouse: str = "Ирина"
    ) -> SyncResult:
        """
        Синхронное списание с немедленной попыткой обновления микросервиса.
        
        Args:
            token_id: ID токена Allegro из микросервиса
            order_id: ID заказа
            sku: SKU товара
            quantity: Количество для списания
            warehouse: Склад для списания
            
        Returns:
            SyncResult с информацией о результате операции
        """
        operation_id = None
        account_name = self._get_account_name_by_token_id(token_id)
        
        try:
            # Создаем запись операции со старой логикой (для совместимости)
            operation = PendingStockOperation(
                order_id=order_id,
                operation_type=OperationType.DEDUCTION,
                warehouse=warehouse,
                token_id=token_id,
                account_name=account_name,
                next_retry_at=datetime.utcnow() + timedelta(seconds=self.config.retry_initial_delay),
                line_items=[{
                    "offer": {"external": {"id": sku}},
                    "quantity": quantity
                }]
            )
            self.session.add(operation)
            self.session.commit()
            operation_id = operation.id
            
            self._log_operation(
                operation.id,
                "created",
                f"Операция создана для заказа {order_id}, аккаунт {account_name}"
            )
            
            # Операция создана и будет обработана process_pending_operations
            return SyncResult(
                success=True,
                operation_id=operation_id,
                details={"account_name": account_name, "queued_for_processing": True}
            )
                
        except Exception as e:
            self.logger.error(f"Error in sync_stock_deduction for account {account_name}: {e}")
            if operation_id:
                self._log_operation(operation_id, "error", f"Исключение: {str(e)}")
            return SyncResult(
                success=False,
                operation_id=operation_id,
                error=str(e),
                details={"account_name": account_name}
            )
    
    def _try_sync_with_microservice(self, operation: PendingStockOperation) -> bool:
        """
        Попытка синхронизации с микросервисом.
        
        Args:
            operation: Операция для синхронизации
            
        Returns:
            bool: True если синхронизация успешна
        """
        try:
            start_time = datetime.utcnow()
            
            # Вызываем API микросервиса для обновления статуса
            result = self.orders_client.update_stock_status(
                token_id=UUID(operation.token_id),
                order_id=operation.order_id,
                is_stock_updated=True
            )
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if result and hasattr(result, 'success') and result.success:
                self._log_operation(
                    operation.id, 
                    "sync_success", 
                    "Синхронизация с микросервисом успешна",
                    execution_time_ms=execution_time
                )
                return True
            else:
                error_msg = getattr(result, 'error', 'Unknown error') if result else 'No response'
                self._log_operation(
                    operation.id, 
                    "sync_failed", 
                    f"Синхронизация с микросервисом провалена: {error_msg}",
                    execution_time_ms=execution_time
                )
                # Обновляем сообщение об ошибке в операции
                operation.error_message = error_msg
                self.session.commit()
                return False
                
        except Exception as e:
            self.logger.error(f"Exception during microservice sync: {e}")
            self._log_operation(
                operation.id, 
                "sync_error", 
                f"Исключение: {str(e)}"
            )
            # Обновляем сообщение об ошибке в операции
            operation.error_message = str(e)
            self.session.commit()
            return False
    
    def _log_operation(
        self,
        operation_id: UUID,
        action: str,
        details: str,
        execution_time_ms: Optional[int] = None,
        status: str = "info",
        detailed_info: Optional[Dict[str, Any]] = None
    ):
        """
        Логирование операции синхронизации.
        
        Args:
            operation_id: ID операции
            action: Действие (created, retry, completed, failed, etc.)
            details: Детальное описание
            execution_time_ms: Время выполнения в миллисекундах
            status: Статус (info, warning, error)
            detailed_info: Дополнительная детальная информация (например, данные валидации)
        """
        try:
            log_details = {"message": details}
            if detailed_info:
                log_details.update(detailed_info)
            
            log_entry = StockSynchronizationLog(
                operation_id=operation_id,
                action=action,
                status=status,
                details=log_details,
                execution_time_ms=execution_time_ms
            )
            self.session.add(log_entry)
            self.session.commit()
        except Exception as e:
            self.logger.error(f"Failed to log operation {operation_id}: {e}")
    
    def _get_order_line_items(self, token_id: str, order_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Получение lineItems заказа от микросервиса.
        
        Args:
            token_id: ID токена
            order_id: ID заказа
            
        Returns:
            List[Dict] с позициями заказа или None при ошибке
        """
        try:
            token_uuid = UUID(token_id)
            
            # Получаем детали заказа через микросервис
            order_response = self.orders_client.get_order_by_id(token_uuid, order_id)
            
            if order_response and order_response.orders:
                order_data = order_response.orders[0]
                line_items = order_data.get('lineItems', [])
                return line_items if line_items else None
            else:
                self.logger.warning(f"Order {order_id} not found in microservice for token {token_id}")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to get order line items from microservice for order {order_id}: {e}")
            return None

    def _ensure_line_items_loaded(self, operation: PendingStockOperation) -> bool:
        """
        Проверяет и загружает line_items если они еще не загружены.
        Также обновляет account_name если он не заполнен.
        
        Args:
            operation: Операция синхронизации
            
        Returns:
            bool: True если line_items доступны, False при ошибке
        """
        # Обновляем account_name если он не заполнен
        self.update_operation_account_name(operation)
        
        # Если line_items уже загружены, возвращаем True
        if operation.line_items:
            return True
        
        account_name = operation.account_name or self._get_account_name_by_token_id(operation.token_id)
        
        self._log_operation(
            operation.id,
            "loading_line_items",
            f"Загрузка позиций заказа из микросервиса для заказа {operation.order_id} (аккаунт: {account_name})"
        )
        
        # Получаем line_items от микросервиса
        line_items = self._get_order_line_items(operation.token_id, operation.order_id)
        
        if not line_items:
            error_msg = "Не удалось загрузить позиции заказа из микросервиса"
            operation.error_message = error_msg
            self._log_operation(
                operation.id,
                "line_items_load_failed",
                error_msg,
                status="error"
            )
            return False
        
        # Сохраняем line_items в операцию
        operation.line_items = line_items
        operation.updated_at = datetime.utcnow()
        self.session.commit()
        
        self._log_operation(
            operation.id,
            "line_items_loaded",
            f"Загружено {len(line_items)} позиций заказа для заказа {operation.order_id}"
        )
        
        return True

    def _validate_and_deduct_stock(self, operation: PendingStockOperation) -> bool:
        """
        Валидирует наличие всех позиций заказа и выполняет списание.
        
        Args:
            operation: Операция синхронизации с загруженными line_items
            
        Returns:
            bool: True если все списания выполнены успешно, False при ошибке
        """
        if not operation.line_items:
            operation.error_message = "No line items available for stock deduction"
            return False
        
        account_name = self._get_account_name_by_token_id(operation.token_id)
        
        # Создаем поддельный order_data для валидации
        order_data = {"lineItems": operation.line_items}
        
        # Валидация наличия всех позиций
        validation_result = self.validation_service.validate_order_stock_availability(
            order_data, operation.warehouse
        )
        
        if not validation_result.valid:
            # Подготавливаем детальную информацию для логирования
            validation_details = {
                "total_items": validation_result.total_items,
                "valid_items": validation_result.valid_items,
                "invalid_items": validation_result.invalid_items,
                "validation_errors": validation_result.error_summary,
                "items_details": []
            }
            
            # Добавляем детали по каждому товару
            for sku, item_validation in validation_result.validation_details.items():
                item_detail = {
                    "sku": item_validation.sku,
                    "warehouse": item_validation.warehouse,
                    "required_quantity": item_validation.required_quantity,
                    "available_quantity": item_validation.available_quantity,
                    "shortage_quantity": item_validation.shortage_quantity,
                    "shortage_percentage": item_validation.shortage_percentage,
                    "error_message": item_validation.error_message,
                    "valid": item_validation.valid
                }
                validation_details["items_details"].append(item_detail)
            
            # Отправляем уведомление о недоступности товаров с детальным логированием
            self._log_operation(
                operation.id,
                "stock_validation_failed",
                f"Провал валидации остатков: {validation_result.invalid_items} из {validation_result.total_items} позиций недоступно",
                execution_time_ms=None,
                status="warning",
                detailed_info=validation_details
            )
            
            # Отправляем уведомление в главный чат о провале валидации заказа
            self.notification_service.notify_order_validation_failure(
                token_id=operation.token_id,
                order_id=operation.order_id,
                account_name=account_name,
                validation_errors=validation_result.error_summary,
                order_details={"lineItems": operation.line_items} if operation.line_items else None,
                operation_id=str(operation.id)
            )
            
            operation.error_message = f"Stock validation failed: {validation_result.invalid_items} of {validation_result.total_items} items unavailable"
            return False
        
        # Все позиции доступны - выполняем списание
        try:
            for item in operation.line_items:
                offer = item.get('offer', {})
                external = offer.get('external', {})
                sku = external.get('id')
                quantity = item.get('quantity', 0)
                
                if not sku or quantity <= 0:
                    continue
                
                # Выполняем списание для данной позиции
                self.inventory_manager.remove_as_sale(
                    sku,
                    operation.warehouse,
                    quantity
                )
                
                self._log_operation(
                    operation.id,
                    "stock_deducted",
                    f"Успешно списано {quantity} единиц товара {sku} со склада {operation.warehouse}"
                )
            
            return True
            
        except Exception as e:
            error_msg = f"Failed to deduct stock: {str(e)}"
            self.logger.error(f"Stock deduction failed for order {operation.order_id} (account {account_name}): {error_msg}")
            operation.error_message = error_msg
            return False

    def process_pending_operations(self, limit: int = 50) -> ProcessingResult:
        """
        Обработка операций из очереди с retry логикой.
        
        Args:
            limit: Максимальное количество операций для обработки
            
        Returns:
            ProcessingResult с статистикой обработки
        """
        result = ProcessingResult()
        
        # Получаем операции готовые для retry
        now = datetime.utcnow()
        # Получаем операции готовые для обработки:
        # - PENDING (нужно списание + синхронизация)
        # - PROCESSING (только синхронизация, списание уже выполнено)
        statement = (
            select(PendingStockOperation)
            .where(
                PendingStockOperation.status.in_([OperationStatus.PENDING, OperationStatus.PROCESSING, OperationStatus.FAILED]),
                PendingStockOperation.next_retry_at <= now
            )
            .order_by(PendingStockOperation.created_at)
            .limit(limit)
        )
        
        operations = self.session.exec(statement).all()
        
        for operation in operations:
            result.processed += 1
            account_name = self._get_account_name_by_token_id(operation.token_id)
            
            # Увеличиваем счетчик попыток
            operation.retry_count += 1
            
            # Если операция в PENDING - нужно выполнить списание
            if operation.status == OperationStatus.PENDING:
                self._log_operation(
                    operation.id,
                    "processing_started",
                    f"Попытка обработки #{operation.retry_count} для аккаунта {account_name} - загрузка данных заказа и выполнение списания"
                )
                
                # Загружаем line_items если их еще нет
                if not self._ensure_line_items_loaded(operation):
                    # Если не удалось загрузить line_items, переходим к обработке ошибки
                    if False:  # removed max_retries limit for infinite retries
                        operation.status = OperationStatus.FAILED
                        result.max_retries_reached += 1
                        
                        self._log_operation(
                            operation.id,
                            "line_items_max_retries",
                            f"Достигнуто максимальное количество попыток загрузки позиций заказа",
                            status="error"
                        )
                    else:
                        # Exponential backoff для следующей попытки
                        delay = min(
                            self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                            self.config.retry_max_delay
                        )
                        operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                        result.failed += 1
                        
                        self._log_operation(
                            operation.id,
                            "line_items_retry_scheduled",
                            f"Не удалось загрузить позиции заказа, повторная попытка через {delay}с",
                            status="warning"
                        )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о неудачной загрузке
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": False,
                        "error_type": "line_items_load_failed",
                        "error_message": operation.error_message or "Failed to load line items"
                    })
                    continue
                
                # Валидируем и выполняем списание
                if self._validate_and_deduct_stock(operation):
                    # Переводим в PROCESSING после успешного списания
                    operation.status = OperationStatus.PROCESSING
                    self._log_operation(
                        operation.id,
                        "stock_deduction_completed",
                        f"Списание выполнено для заказа {operation.order_id}"
                    )
                else:
                    # Списание не удалось
                    if False:  # removed max_retries limit for infinite retries
                        operation.status = OperationStatus.FAILED
                        result.max_retries_reached += 1
                        
                        self._log_operation(
                            operation.id,
                            "stock_deduction_max_retries",
                            f"Достигнуто максимальное количество попыток списания: {operation.error_message}",
                            status="error"
                        )
                    else:
                        # Возвращаем в PENDING для повторной попытки
                        operation.status = OperationStatus.PENDING
                        
                        # Exponential backoff для следующей попытки
                        delay = min(
                            self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                            self.config.retry_max_delay
                        )
                        operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                        result.failed += 1
                        
                        self._log_operation(
                            operation.id,
                            "stock_deduction_retry_scheduled",
                            f"Списание провалено, повторная попытка через {delay}с: {operation.error_message}",
                            status="warning"
                        )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о неудачном списании
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": False,
                        "error_type": "stock_deduction_failed",
                        "error_message": operation.error_message or "Stock deduction failed"
                    })
                    continue
            else:
                # Операция уже в PROCESSING - списание выполнено, только синхронизация
                self._log_operation(
                    operation.id,
                    "sync_retry",
                    f"Повторная попытка синхронизации #{operation.retry_count} для аккаунта {account_name} - остатки уже списаны"
                )
            
            self.session.commit()
            
            # Попытка синхронизации с микросервисом
            sync_success = self._try_sync_with_microservice(operation)
            
            if sync_success:
                operation.status = OperationStatus.COMPLETED
                operation.completed_at = datetime.utcnow()
                result.succeeded += 1
                self._log_operation(
                    operation.id, 
                    "completed", 
                    f"Попытка #{operation.retry_count} успешна для аккаунта {account_name}"
                )
            else:
                if False:  # removed max_retries limit for infinite retries
                    operation.status = OperationStatus.FAILED
                    result.max_retries_reached += 1
                    self._log_operation(
                        operation.id, 
                        "max_retries", 
                        f"Достигнуто максимальное количество попыток: {operation.max_retries} для аккаунта {account_name}",
                        status="error"
                    )
                else:
                    operation.status = OperationStatus.PENDING
                    # Exponential backoff
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = now + timedelta(seconds=delay)
                    result.failed += 1
                    self._log_operation(
                        operation.id, 
                        "retry_failed", 
                        f"Попытка #{operation.retry_count} провалена для аккаунта {account_name}, следующая через {delay}с",
                        status="warning"
                    )
            
            operation.updated_at = datetime.utcnow()
            self.session.commit()
            
            # Добавляем детали обработанной операции
            result.details.append({
                "operation_id": str(operation.id),
                "account_name": account_name,
                "order_id": operation.order_id,
                "retry_count": operation.retry_count,
                "status": operation.status,
                "success": sync_success,
                "line_items_count": len(operation.line_items) if operation.line_items else 0
            })
        
        self.logger.info(f"Processed {result.processed} operations: {result.succeeded} succeeded, {result.failed} failed, {result.max_retries_reached} max retries reached")
        return result
    
    def reconcile_stock_status(
        self, 
        token_id: Optional[UUID] = None, 
        limit: int = 100
    ) -> ReconciliationResult:
        """
        Сверка состояний между локальной системой и микросервисом.
        
        Args:
            token_id: ID токена для проверки (если None, проверяются все токены)
            limit: Максимальное количество заказов для проверки
            
        Returns:
            ReconciliationResult с информацией о найденных расхождениях
        """
        result = ReconciliationResult()
        
        try:
            # Получаем токены из микросервиса
            if token_id:
                # Проверяем один конкретный токен
                try:
                    token_response = self.tokens_client.get_token(token_id)
                    tokens_to_check = [token_response] if token_response else []
                except Exception as e:
                    self.logger.error(f"Failed to get token {token_id}: {e}")
                    tokens_to_check = []
            else:
                # Получаем все активные токены
                try:
                    tokens_response = self.tokens_client.get_tokens(
                        page=1, 
                        per_page=100,
                        active_only=True
                    )
                    tokens_to_check = tokens_response.items if tokens_response else []
                except Exception as e:
                    self.logger.error(f"Failed to get tokens list: {e}")
                    tokens_to_check = []
            
            for token_data in tokens_to_check:
                token_uuid = UUID(token_data.id) if hasattr(token_data, 'id') else UUID(token_data.get('id'))
                account_name = token_data.account_name if hasattr(token_data, 'account_name') else token_data.get('account_name', 'Unknown')
                
                account_discrepancies = self._reconcile_single_account(
                    token_uuid, 
                    account_name,
                    limit // len(tokens_to_check) if len(tokens_to_check) > 1 else limit
                )
                result.discrepancies.extend(account_discrepancies)
                result.total_checked += len(account_discrepancies)
            
            result.discrepancies_found = len(result.discrepancies)
            
            # Попытка автоматического исправления простых расхождений
            if self.config.reconciliation_enabled:
                auto_fixed = self._auto_fix_discrepancies(result.discrepancies)
                result.auto_fixed = auto_fixed
                result.requires_manual_review = result.discrepancies_found - auto_fixed
            
            self.logger.info(f"Reconciliation completed: {result.total_checked} checked, {result.discrepancies_found} discrepancies, {result.auto_fixed} auto-fixed")
            
        except Exception as e:
            self.logger.error(f"Error during reconciliation: {e}")
            result.discrepancies.append({
                "error": str(e),
                "type": "reconciliation_error"
            })
        
        return result
    
    def _reconcile_single_account(
        self, 
        token_id: UUID, 
        account_name: str, 
        limit: int
    ) -> List[Dict[str, Any]]:
        """Сверка для одного аккаунта."""
        discrepancies = []
        
        try:
            # Получаем недавние заказы из микросервиса
            orders_response = self.orders_client.get_orders(
                token_id=token_id,
                limit=limit,
                stock_updated=None  # Получаем все заказы
            )
            
            if not orders_response or not hasattr(orders_response, 'orders'):
                return discrepancies
            
            for order_data in orders_response.orders:
                order_id = order_data.get('id')
                remote_stock_updated = order_data.get('is_stock_updated', False)
                
                # Проверяем локальное состояние
                local_operation = self.session.exec(
                    select(PendingStockOperation)
                    .where(
                        PendingStockOperation.order_id == order_id,
                        PendingStockOperation.token_id == str(token_id)
                    )
                ).first()
                
                local_stock_updated = (
                    local_operation and local_operation.status == OperationStatus.COMPLETED
                ) if local_operation else False
                
                # Проверяем расхождения
                if local_stock_updated != remote_stock_updated:
                    discrepancies.append({
                        "order_id": order_id,
                        "account_name": account_name,
                        "token_id": str(token_id),
                        "local_deducted": local_stock_updated,
                        "remote_updated": remote_stock_updated,
                        "line_items": local_operation.line_items if local_operation else [],
                        "discrepancy_type": "stock_status_mismatch",
                        "can_auto_fix": self._can_auto_fix_discrepancy(local_stock_updated, remote_stock_updated),
                        "timestamp": datetime.utcnow().isoformat()
                    })
        
        except Exception as e:
            self.logger.error(f"Error reconciling account {account_name}: {e}")
            discrepancies.append({
                "account_name": account_name,
                "error": str(e),
                "type": "account_reconciliation_error"
            })
        
        return discrepancies
    
    def _can_auto_fix_discrepancy(self, local_updated: bool, remote_updated: bool) -> bool:
        """Определяет, может ли расхождение быть исправлено автоматически."""
        # Автоматически исправляем только если локально списано, но удаленно не обновлено
        return local_updated and not remote_updated
    
    def _auto_fix_discrepancies(self, discrepancies: List[Dict[str, Any]]) -> int:
        """Автоматическое исправление простых расхождений."""
        auto_fixed = 0
        
        for discrepancy in discrepancies:
            if not discrepancy.get('can_auto_fix', False):
                continue
            
            try:
                # Создаем операцию для принудительной синхронизации
                token_id = discrepancy['token_id']
                order_id = discrepancy['order_id']
                
                # Для автоисправления создаем простую операцию заказа
                result = self.create_order_processing_operation(
                    token_id=token_id,
                    order_id=order_id,
                    warehouse="Ирина"
                )
                
                if result.success:
                    auto_fixed += 1
                    self.logger.info(f"Auto-fixed discrepancy for order {order_id}")
                
            except Exception as e:
                self.logger.error(f"Failed to auto-fix discrepancy for order {discrepancy['order_id']}: {e}")
        
        return auto_fixed
    
    def rollback_operation(self, operation_id: UUID) -> SyncResult:
        """
        Откат операции синхронизации.
        
        Args:
            operation_id: ID операции для отката
            
        Returns:
            SyncResult с результатом отката
        """
        try:
            operation = self.session.get(PendingStockOperation, operation_id)
            if not operation:
                return SyncResult(
                    success=False, 
                    error="Operation not found",
                    operation_id=operation_id
                )
            
            # Отменяем операцию
            operation.status = OperationStatus.CANCELLED
            operation.updated_at = datetime.utcnow()
            self.session.commit()
            
            self._log_operation(
                operation_id, 
                "rolled_back", 
                f"Операция отменена вручную"
            )
            
            # TODO: Здесь можно добавить логику для отката изменений в микросервисе
            # if operation.status == OperationStatus.COMPLETED:
            #     # Откат в микросервисе через update_stock_status(is_stock_updated=False)
            #     pass
            
            account_name = self._get_account_name_by_token_id(operation.token_id)
            return SyncResult(
                success=True,
                operation_id=operation_id,
                details={"account_name": account_name, "rolled_back": True}
            )
            
        except Exception as e:
            self.logger.error(f"Error rolling back operation {operation_id}: {e}")
            return SyncResult(
                success=False,
                operation_id=operation_id,
                error=str(e)
            )
    
    def get_sync_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики системы синхронизации.
        
        Returns:
            Dict с различной статистикой
        """
        try:
            now = datetime.utcnow()
            yesterday = now - timedelta(days=1)
            
            # Общая статистика операций
            total_pending = self.session.exec(
                select(PendingStockOperation)
                .where(PendingStockOperation.status == OperationStatus.PENDING)
            ).all()
            
            total_failed = self.session.exec(
                select(PendingStockOperation)
                .where(PendingStockOperation.status == OperationStatus.FAILED)
            ).all()
            
            completed_today = self.session.exec(
                select(PendingStockOperation)
                .where(
                    PendingStockOperation.status == OperationStatus.COMPLETED,
                    PendingStockOperation.completed_at >= yesterday
                )
            ).all()
            
            # Застрявшие операции
            stale_operations = self.session.exec(
                select(PendingStockOperation)
                .where(
                    PendingStockOperation.status == OperationStatus.PENDING,
                    PendingStockOperation.created_at < now - timedelta(hours=self.config.monitoring_stale_operation_hours)
                )
            ).all()
            
            return {
                "pending_operations": len(total_pending),
                "failed_operations": len(total_failed),
                "completed_today": len(completed_today),
                "stale_operations": len(stale_operations),
                "health_status": "healthy" if len(total_pending) < self.config.monitoring_max_pending_operations and len(stale_operations) == 0 else "warning",
                "last_updated": now.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting sync statistics: {e}")
            return {
                "error": str(e),
                "health_status": "error",
                "last_updated": datetime.utcnow().isoformat()
            }