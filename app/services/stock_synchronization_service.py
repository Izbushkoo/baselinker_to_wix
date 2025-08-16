import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select
from uuid import UUID

from app.models.stock_synchronization import (
    PendingStockOperation,
    StockSynchronizationLog,
    OperationType,
    OperationStatus,
    LogAction
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
from app.services.operations_service import get_operations_service
from app.services.standardized_logger import get_standardized_logger, ValidationResult
from app.models.operations import OperationType as RegularOperationType
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
        self.standardized_logger = get_standardized_logger(session)
    
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
    
    def _check_order_status_in_microservice(self, token_id: str, order_id: str) -> Dict[str, Any]:
        """
        Проверяет текущее состояние заказа в микросервисе.
        
        Args:
            token_id: ID токена Allegro
            order_id: ID заказа
            
        Returns:
            Dict с информацией о заказе или None при ошибке
        """
        try:
            # Получаем актуальную информацию о заказе из микросервиса
            order_response = self.orders_client.get_order_by_id(
                token_id=UUID(token_id),
                order_id=order_id
            )
            
            if not order_response or not order_response.orders:
                self.logger.warning(f"Заказ {order_id} не найден в микросервисе для токена {token_id}")
                return None
            
            # Берем первый заказ (должен быть только один)
            order_data = order_response.orders[0]
            
            # Извлекаем технические флаги
            technical_flags = order_data.get("technical_flags", {})
            is_stock_updated = technical_flags.get("is_stock_updated", False)
            status = order_data.get("status")
            fulfillment = order_data.get("fulfillment", {})
            
            return {
                "order_id": order_id,
                "status": status,
                "is_stock_updated": is_stock_updated,
                "fulfillment_status": fulfillment.get("status"),
                "technical_flags": technical_flags,
                "raw_data": order_data
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке состояния заказа {order_id} в микросервисе: {e}")
            return None
    
    def _check_existing_operation(self, token_id: str, order_id: str) -> Optional[PendingStockOperation]:
        """
        Проверяет существование операции для данного заказа.
        
        Args:
            token_id: ID токена Allegro
            order_id: ID заказа
            
        Returns:
            PendingStockOperation если операция существует, None если нет
        """
        try:
            existing_operation = self.session.exec(
                select(PendingStockOperation).where(
                    PendingStockOperation.token_id == token_id,
                    PendingStockOperation.order_id == order_id
                )
            ).first()
            
            if existing_operation:
                self.logger.warning(
                    f"Операция для заказа {order_id} (токен {token_id}) уже существует "
                    f"со статусом {existing_operation.status} (ID: {existing_operation.id})"
                )
            
            return existing_operation
        except Exception as e:
            self.logger.error(f"Ошибка при проверке существующей операции: {e}")
            return None
    
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
        
        # Проверяем существование операции для данного заказа
        existing_operation = self._check_existing_operation(token_id, order_id)
        if existing_operation:
            return SyncResult(
                success=True,
                operation_id=existing_operation.id,
                details={
                    "account_name": account_name, 
                    "already_exists": True,
                    "status": existing_operation.status.value,
                    "message": f"Операция для заказа {order_id} уже существует"
                }
            )
        
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
            
            self.standardized_logger.log_operation_created(
                operation_id=operation.id,
                order_id=order_id,
                account_name=account_name,
                warehouse=warehouse,
                operation_type=OperationType.DEDUCTION.value
            )
            
            return SyncResult(
                success=True,
                operation_id=operation_id,
                details={"account_name": account_name, "queued_for_processing": True}
            )
                
        except Exception as e:
            self.logger.error(f"Error creating order processing operation for account {account_name}: {e}")
            if operation_id:
                self.standardized_logger.log_error_with_context(
                    operation_id=operation_id,
                    error=e,
                    context={
                        "method": "create_order_processing_operation",
                        "order_id": order_id,
                        "account_name": account_name,
                        "warehouse": warehouse
                    }
                )
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
                
                self.standardized_logger.log_account_name_updated(
                    operation_id=operation.id,
                    account_name=account_name
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
        
        # Проверяем существование операции для данного заказа
        existing_operation = self._check_existing_operation(token_id, order_id)
        if existing_operation:
            return SyncResult(
                success=True,
                operation_id=existing_operation.id,
                details={
                    "account_name": account_name, 
                    "already_exists": True,
                    "status": existing_operation.status.value,
                    "message": f"Операция для заказа {order_id} уже существует"
                }
            )
        
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
            
            self.standardized_logger.log_operation_created(
                operation_id=operation.id,
                order_id=order_id,
                account_name=account_name,
                warehouse=warehouse,
                operation_type=OperationType.DEDUCTION.value
            )
            
            return SyncResult(
                success=True,
                operation_id=operation_id,
                details={"account_name": account_name, "queued_for_processing": True}
            )
                
        except Exception as e:
            self.logger.error(f"Error creating stock deduction operation for account {account_name}: {e}")
            if operation_id:
                self.standardized_logger.log_error_with_context(
                    operation_id=operation_id,
                    error=e,
                    context={
                        "method": "create_stock_deduction_operation",
                        "order_id": order_id,
                        "account_name": account_name,
                        "sku": sku,
                        "quantity": quantity,
                        "warehouse": warehouse
                    }
                )
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
        
        # Проверяем существование операции для данного заказа
        existing_operation = self._check_existing_operation(token_id, order_id)
        if existing_operation:
            return SyncResult(
                success=True,
                operation_id=existing_operation.id,
                details={
                    "account_name": account_name, 
                    "already_exists": True,
                    "status": existing_operation.status.value,
                    "message": f"Операция для заказа {order_id} уже существует"
                }
            )
        
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
            
            self.standardized_logger.log_operation_created(
                operation_id=operation.id,
                order_id=order_id,
                account_name=account_name,
                warehouse=warehouse,
                operation_type=OperationType.DEDUCTION.value
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
                self.standardized_logger.log_error_with_context(
                    operation_id=operation_id,
                    error=e,
                    context={
                        "method": "sync_stock_deduction",
                        "order_id": order_id,
                        "account_name": account_name,
                        "sku": sku,
                        "quantity": quantity,
                        "warehouse": warehouse
                    }
                )
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
            
            self.standardized_logger.log_microservice_sync_started(
                operation_id=operation.id,
                order_id=operation.order_id
            )
            
            # Вызываем API микросервиса для обновления статуса
            result = self.orders_client.update_stock_status(
                token_id=UUID(operation.token_id),
                order_id=operation.order_id,
                is_stock_updated=True
            )
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if result and hasattr(result, 'success') and result.success:
                self.standardized_logger.log_microservice_sync_success(
                    operation_id=operation.id,
                    order_id=operation.order_id,
                    execution_time_ms=execution_time
                )
                return True
            else:
                error_msg = getattr(result, 'error', 'Unknown error') if result else 'No response'
                self.standardized_logger.log_microservice_sync_failed(
                    operation_id=operation.id,
                    order_id=operation.order_id,
                    error_message=error_msg,
                    execution_time_ms=execution_time
                )
                # Обновляем сообщение об ошибке в операции
                operation.error_message = error_msg
                self.session.commit()
                return False
                
        except Exception as e:
            self.logger.error(f"Exception during microservice sync: {e}")
            self.standardized_logger.log_error_with_context(
                operation_id=operation.id,
                error=e,
                context={
                    "method": "_try_sync_with_microservice",
                    "order_id": operation.order_id,
                    "token_id": operation.token_id
                },
                action=LogAction.MICROSERVICE_SYNC_FAILED
            )
            # Обновляем сообщение об ошибке в операции
            operation.error_message = str(e)
            self.session.commit()
            return False
    

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
        
        self.standardized_logger.log_line_items_loading(
            operation_id=operation.id,
            order_id=operation.order_id,
            account_name=account_name
        )
        
        # Получаем line_items от микросервиса
        line_items = self._get_order_line_items(operation.token_id, operation.order_id)
        
        if not line_items:
            error_msg = "Не удалось загрузить позиции заказа из микросервиса"
            operation.error_message = error_msg
            self.standardized_logger.log_line_items_load_failed(
                operation_id=operation.id,
                order_id=operation.order_id,
                error_message=error_msg
            )
            return False
        
        # Сохраняем line_items в операцию
        operation.line_items = line_items
        operation.updated_at = datetime.utcnow()
        self.session.commit()
        
        self.standardized_logger.log_line_items_loaded(
            operation_id=operation.id,
            order_id=operation.order_id,
            items_count=len(line_items)
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
        
        # Логируем начало валидации
        self.standardized_logger.log_stock_validation_started(
            operation_id=operation.id,
            warehouse=operation.warehouse,
            items_count=len(operation.line_items)
        )
        
        # Валидация наличия всех позиций
        validation_result = self.validation_service.validate_order_stock_availability(
            order_data, operation.warehouse
        )
        
        if not validation_result.valid:
            # Создаем ValidationResult для стандартизированного логирования
            validation_result_obj = ValidationResult(
                valid=validation_result.valid,
                total_items=validation_result.total_items,
                valid_items=validation_result.valid_items,
                invalid_items=validation_result.invalid_items,
                error_summary=validation_result.error_summary,
                validation_details=validation_result.validation_details
            )
            
            # Логируем провал валидации через стандартизированный логгер
            self.standardized_logger.log_validation_failure(
                operation_id=operation.id,
                validation_result=validation_result_obj
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
        self.standardized_logger.log_stock_validation_passed(
            operation_id=operation.id,
            items_count=validation_result.total_items
        )
        
        self.standardized_logger.log_stock_deduction_started(
            operation_id=operation.id,
            warehouse=operation.warehouse,
            items_count=len(operation.line_items)
        )
        
        try:
            products_data = []
            
            for item in operation.line_items:
                offer = item.get('offer', {})
                external = offer.get('external', {})
                sku = external.get('id')
                quantity = item.get('quantity', 0)
                offer_name = offer.get('name', '')
                
                if not sku or quantity <= 0:
                    continue
                
                # Выполняем списание для данной позиции
                self.inventory_manager.remove_as_sale(
                    sku,
                    operation.warehouse,
                    quantity
                )
                
                # Собираем данные для создания операции продажи
                products_data.append({
                    'sku': sku,
                    'quantity': quantity,
                    'name': offer_name
                })
                
                self.standardized_logger.log_stock_deduction_completed(
                    operation_id=operation.id,
                    sku=sku,
                    quantity=quantity,
                    warehouse=operation.warehouse
                )
            
            # Создаем операцию продажи по заказу через operations_service
            if products_data:
                try:
                    operations_service = get_operations_service()
                    sales_operation = operations_service.create_order_operation(
                        warehouse_id=operation.warehouse,
                        order_id=operation.order_id,
                        products_data=products_data,
                        comment=f"Списание по заказу Allegro {operation.order_id} (аккаунт: {account_name})",
                        user_email="system@stock_sync",
                        session=self.session
                    )
                    
                    self.standardized_logger.log_action_with_timing(
                        operation_id=operation.id,
                        action=LogAction.STOCK_DEDUCTION_COMPLETED,
                        details=f"Создана операция продажи ID: {sales_operation.id} для заказа {operation.order_id}",
                        additional_context={
                            "sales_operation_id": str(sales_operation.id),
                            "order_id": operation.order_id
                        }
                    )
                    
                except Exception as e:
                    # Логируем ошибку создания операции, но не прерываем процесс
                    error_msg = f"Ошибка создания операции продажи: {str(e)}"
                    self.logger.warning(f"Failed to create sales operation for order {operation.order_id}: {error_msg}")
                    self.standardized_logger.log_error_with_context(
                        operation_id=operation.id,
                        error=e,
                        context={
                            "method": "_validate_and_deduct_stock",
                            "action": "create_sales_operation",
                            "order_id": operation.order_id,
                            "products_count": len(products_data)
                        }
                    )
            
            return True
            
        except Exception as e:
            error_msg = f"Failed to deduct stock: {str(e)}"
            self.logger.error(f"Stock deduction failed for order {operation.order_id} (account {account_name}): {error_msg}")
            operation.error_message = error_msg
            self.standardized_logger.log_stock_deduction_failed(
                operation_id=operation.id,
                error_message=error_msg
            )
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
                PendingStockOperation.status.in_([OperationStatus.PENDING, OperationStatus.PROCESSING, OperationStatus.FAILED, OperationStatus.STOCK_DEDUCTED]),
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
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation.id,
                    action=LogAction.STOCK_DEDUCTION_STARTED,
                    details=f"Попытка обработки #{operation.retry_count} для аккаунта {account_name} - проверка состояния заказа и выполнение списания",
                    additional_context={
                        "retry_count": operation.retry_count,
                        "account_name": account_name
                    }
                )
                
                # Проверяем текущее состояние заказа в микросервисе
                order_status = self._check_order_status_in_microservice(operation.token_id, operation.order_id)
                
                if order_status is None:
                    # Не удалось получить статус заказа - планируем повторную попытку
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                    result.failed += 1
                    
                    self.standardized_logger.log_retry_scheduled(
                        operation_id=operation.id,
                        retry_count=operation.retry_count,
                        next_retry_at=operation.next_retry_at,
                        reason=f"Не удалось проверить состояние заказа в микросервисе, повторная попытка через {delay}с"
                    )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о неудачной проверке статуса
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": False,
                        "error_type": "order_status_check_failed",
                        "error_message": "Failed to check order status in microservice"
                    })
                    continue
                
                # Проверяем, не был ли заказ уже списан вручную
                if order_status.get("is_stock_updated", False):
                    # Заказ уже списан - помечаем операцию как завершенную
                    operation.status = OperationStatus.COMPLETED
                    operation.completed_at = datetime.utcnow()
                    result.succeeded += 1
                    
                    self.standardized_logger.log_status_transition(
                        operation_id=operation.id,
                        from_status=OperationStatus.PENDING,
                        to_status=OperationStatus.COMPLETED,
                        reason=f"Заказ {operation.order_id} уже был списан вручную в микросервисе",
                        additional_context={
                            "order_status": order_status,
                            "completion_reason": "already_processed_in_microservice"
                        }
                    )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о завершенной операции
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": True,
                        "completion_reason": "already_processed_in_microservice",
                        "order_status": order_status
                    })
                    continue
                
                # Проверяем статус заказа - должен быть READY_FOR_PROCESSING
                if order_status.get("status") != "READY_FOR_PROCESSING":
                    # Заказ не готов к обработке - планируем повторную попытку
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                    result.failed += 1
                    
                    self.standardized_logger.log_retry_scheduled(
                        operation_id=operation.id,
                        retry_count=operation.retry_count,
                        next_retry_at=operation.next_retry_at,
                        reason=f"Заказ {operation.order_id} не готов к обработке (статус: {order_status.get('status')})"
                    )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о неготовности заказа
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": False,
                        "error_type": "order_not_ready",
                        "error_message": f"Order status is {order_status.get('status')}, expected READY_FOR_PROCESSING",
                        "order_status": order_status
                    })
                    continue
                
                # Проверяем, не отменен ли заказ
                if order_status.get("fulfillment_status") == "CANCELLED":
                    # Заказ отменен - помечаем операцию как завершенную
                    operation.status = OperationStatus.COMPLETED
                    operation.completed_at = datetime.utcnow()
                    result.succeeded += 1
                    
                    self.standardized_logger.log_status_transition(
                        operation_id=operation.id,
                        from_status=OperationStatus.PENDING,
                        to_status=OperationStatus.COMPLETED,
                        reason=f"Заказ {operation.order_id} отменен",
                        additional_context={
                            "order_status": order_status,
                            "completion_reason": "order_cancelled"
                        }
                    )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о завершенной операции
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": True,
                        "completion_reason": "order_cancelled",
                        "order_status": order_status
                    })
                    continue
                
                # Загружаем line_items если их еще нет
                if not self._ensure_line_items_loaded(operation):
                    # Если не удалось загрузить line_items, переходим к обработке ошибки
                    if False:  # removed max_retries limit for infinite retries
                        operation.status = OperationStatus.FAILED
                        result.max_retries_reached += 1
                        
                        self.standardized_logger.log_max_retries_reached(
                            operation_id=operation.id,
                            max_retries=self.config.max_retries,
                            final_error="Не удалось загрузить позиции заказа"
                        )
                    else:
                        # Exponential backoff для следующей попытки
                        delay = min(
                            self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                            self.config.retry_max_delay
                        )
                        operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                        result.failed += 1
                        
                        self.standardized_logger.log_retry_scheduled(
                            operation_id=operation.id,
                            retry_count=operation.retry_count,
                            next_retry_at=operation.next_retry_at,
                            reason="Не удалось загрузить позиции заказа"
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
                
                # Переводим в PROCESSING после загрузки line_items
                old_status = operation.status
                operation.status = OperationStatus.PROCESSING
                operation.line_items_loaded_at = datetime.utcnow()
                operation.updated_at = datetime.utcnow()
                
                self.standardized_logger.log_status_transition(
                    operation_id=operation.id,
                    from_status=old_status,
                    to_status=OperationStatus.PROCESSING,
                    reason=f"Позиции заказа загружены для заказа {operation.order_id}",
                    additional_context={
                        "items_count": len(operation.line_items) if operation.line_items else 0
                    }
                )
                
                # Коммитим переход в PROCESSING
                self.session.commit()
                
                # Валидируем и выполняем списание
                if self._validate_and_deduct_stock(operation):
                    # Переводим в STOCK_DEDUCTED после успешного списания
                    old_status = operation.status
                    operation.status = OperationStatus.STOCK_DEDUCTED
                    operation.stock_deducted_at = datetime.utcnow()
                    operation.updated_at = datetime.utcnow()
                    
                    self.standardized_logger.log_status_transition(
                        operation_id=operation.id,
                        from_status=old_status,
                        to_status=OperationStatus.STOCK_DEDUCTED,
                        reason=f"Списание выполнено для заказа {operation.order_id}",
                        additional_context={
                            "items_count": len(operation.line_items) if operation.line_items else 0
                        }
                    )
                else:
                    # Списание не удалось - остаемся в PROCESSING (line_items уже загружены)
                    # Exponential backoff для следующей попытки
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                    result.failed += 1
                    
                    self.standardized_logger.log_retry_scheduled(
                        operation_id=operation.id,
                        retry_count=operation.retry_count,
                        next_retry_at=operation.next_retry_at,
                        reason=f"Списание провалено: {operation.error_message}, остаемся в PROCESSING"
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
            elif operation.status == OperationStatus.PROCESSING:
                # Операция в PROCESSING - line_items загружены, нужно выполнить списание
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation.id,
                    action=LogAction.STOCK_DEDUCTION_STARTED,
                    details=f"Повторная попытка списания #{operation.retry_count} для аккаунта {account_name}",
                    additional_context={
                        "retry_count": operation.retry_count,
                        "account_name": account_name
                    }
                )
                
                # Валидируем и выполняем списание
                if self._validate_and_deduct_stock(operation):
                    # Переводим в STOCK_DEDUCTED после успешного списания
                    old_status = operation.status
                    operation.status = OperationStatus.STOCK_DEDUCTED
                    operation.stock_deducted_at = datetime.utcnow()
                    operation.updated_at = datetime.utcnow()
                    
                    self.standardized_logger.log_status_transition(
                        operation_id=operation.id,
                        from_status=old_status,
                        to_status=OperationStatus.STOCK_DEDUCTED,
                        reason=f"Списание выполнено для заказа {operation.order_id}",
                        additional_context={
                            "items_count": len(operation.line_items) if operation.line_items else 0
                        }
                    )
                else:
                    # Списание не удалось - остаемся в PROCESSING (line_items уже загружены)
                    # Exponential backoff для следующей попытки
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                    result.failed += 1
                    
                    self.standardized_logger.log_retry_scheduled(
                        operation_id=operation.id,
                        retry_count=operation.retry_count,
                        next_retry_at=operation.next_retry_at,
                        reason=f"Списание провалено: {operation.error_message}, остаемся в PROCESSING"
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
                    
            elif operation.status == OperationStatus.STOCK_DEDUCTED:
                # Операция в STOCK_DEDUCTED - остатки списаны, нужна синхронизация с микросервисом
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation.id,
                    action=LogAction.MICROSERVICE_SYNC_STARTED,
                    details=f"Попытка синхронизации #{operation.retry_count} для аккаунта {account_name} - остатки уже списаны",
                    additional_context={
                        "retry_count": operation.retry_count,
                        "account_name": account_name
                    }
                )
                
                # Проверяем, не был ли заказ уже обработан в микросервисе
                order_status = self._check_order_status_in_microservice(operation.token_id, operation.order_id)
                
                if order_status and order_status.get("is_stock_updated", False):
                    # Заказ уже обработан в микросервисе - помечаем операцию как завершенную
                    operation.status = OperationStatus.COMPLETED
                    operation.completed_at = datetime.utcnow()
                    operation.microservice_synced_at = datetime.utcnow()
                    result.succeeded += 1
                    
                    self.standardized_logger.log_status_transition(
                        operation_id=operation.id,
                        from_status=OperationStatus.STOCK_DEDUCTED,
                        to_status=OperationStatus.COMPLETED,
                        reason=f"Заказ {operation.order_id} уже обработан в микросервисе",
                        additional_context={
                            "order_status": order_status,
                            "completion_reason": "already_synced_in_microservice"
                        }
                    )
                    
                    operation.updated_at = datetime.utcnow()
                    self.session.commit()
                    
                    # Добавляем детали о завершенной операции
                    result.details.append({
                        "operation_id": str(operation.id),
                        "account_name": account_name,
                        "order_id": operation.order_id,
                        "retry_count": operation.retry_count,
                        "status": operation.status,
                        "success": True,
                        "completion_reason": "already_synced_in_microservice",
                        "order_status": order_status
                    })
                    continue
                    
            else:
                # Операция в FAILED или другом статусе - пропускаем
                continue
            
            # Попытка синхронизации с микросервисом (только для STOCK_DEDUCTED операций)
            if operation.status == OperationStatus.STOCK_DEDUCTED:
                sync_success = self._try_sync_with_microservice(operation)
                
                if sync_success:
                    old_status = operation.status
                    operation.status = OperationStatus.COMPLETED
                    operation.completed_at = datetime.utcnow()
                    operation.microservice_synced_at = datetime.utcnow()
                    result.succeeded += 1
                    
                    self.standardized_logger.log_status_transition(
                        operation_id=operation.id,
                        from_status=old_status,
                        to_status=OperationStatus.COMPLETED,
                        reason=f"Синхронизация с микросервисом успешна для аккаунта {account_name}",
                        additional_context={
                            "retry_count": operation.retry_count,
                            "account_name": account_name
                        }
                    )
                else:
                    # Синхронизация не удалась - остаемся в STOCK_DEDUCTED для повтора
                    delay = min(
                        self.config.retry_initial_delay * (self.config.retry_exponential_base ** (operation.retry_count - 1)),
                        self.config.retry_max_delay
                    )
                    operation.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                    result.failed += 1
                    
                    self.standardized_logger.log_retry_scheduled(
                        operation_id=operation.id,
                        retry_count=operation.retry_count,
                        next_retry_at=operation.next_retry_at,
                        reason=f"Синхронизация с микросервисом провалена для аккаунта {account_name}"
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
            else:
                # Операция не в STOCK_DEDUCTED - просто коммитим изменения
                operation.updated_at = datetime.utcnow()
                self.session.commit()
        
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
            old_status = operation.status
            operation.status = OperationStatus.CANCELLED
            operation.updated_at = datetime.utcnow()
            self.session.commit()
            
            self.standardized_logger.log_status_transition(
                operation_id=operation_id,
                from_status=old_status,
                to_status=OperationStatus.CANCELLED,
                reason="Операция отменена вручную"
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