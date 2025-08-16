"""
Сервис отмены операций синхронизации складских остатков.

Этот модуль предоставляет функциональность для отмены операций синхронизации
на различных этапах их выполнения с соответствующим откатом изменений.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from sqlmodel import Session

from app.models.stock_synchronization import (
    PendingStockOperation,
    OperationStatus,
    LogAction
)
from app.schemas.stock_synchronization import SyncResult
from app.services.standardized_logger import get_standardized_logger
from app.services.warehouse.manager import InventoryManager, get_manager
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.operations_service import get_operations_service
from app.core.security import create_access_token
from app.core.config import settings


jwt_token = create_access_token(user_id=settings.PROJECT_NAME)


class OperationCancellationService:
    """
    Сервис для отмены операций синхронизации складских остатков.
    
    Обеспечивает корректную отмену операций на различных этапах выполнения
    с соответствующим откатом изменений в складской системе и микросервисе.
    """
    
    def __init__(
        self,
        session: Session,
        inventory_manager: Optional[InventoryManager] = None,
        orders_client: Optional[OrdersClient] = None
    ):
        """
        Инициализация сервиса отмены операций.
        
        Args:
            session: Сессия базы данных
            inventory_manager: Менеджер складских операций
            orders_client: Клиент для работы с микросервисом заказов
        """
        self.session = session
        self.inventory_manager = inventory_manager or get_manager()
        self.orders_client = orders_client or OrdersClient(jwt_token=jwt_token)
        self.standardized_logger = get_standardized_logger(session)
        self.operations_service = get_operations_service()
    
    def cancel_operation(
        self,
        operation_id: UUID,
        cancelled_by: str,
        cancellation_reason: str
    ) -> SyncResult:
        """
        Отмена операции синхронизации с соответствующим откатом изменений.
        
        Args:
            operation_id: ID операции для отмены
            cancelled_by: Кто отменил операцию (пользователь/система)
            cancellation_reason: Причина отмены
            
        Returns:
            SyncResult с результатом отмены
        """
        try:
            # Получаем операцию
            operation = self.session.get(PendingStockOperation, operation_id)
            if not operation:
                return SyncResult(
                    success=False,
                    operation_id=operation_id,
                    error="Operation not found"
                )
            
            # Проверяем, можно ли отменить операцию
            if operation.status == OperationStatus.CANCELLED:
                return SyncResult(
                    success=True,
                    operation_id=operation_id,
                    details={
                        "message": "Operation already cancelled",
                        "cancelled_by": operation.cancelled_by,
                        "cancellation_reason": operation.cancellation_reason
                    }
                )
            
            # Логируем начало отмены
            self.standardized_logger.log_action_with_timing(
                operation_id=operation_id,
                action=LogAction.CANCELLATION_REQUESTED,
                details=f"Запрошена отмена операции: {cancellation_reason}",
                additional_context={
                    "cancelled_by": cancelled_by,
                    "cancellation_reason": cancellation_reason,
                    "current_status": operation.status.value
                }
            )
            
            old_status = operation.status
            rollback_operations = []
            
            # Выполняем отмену в зависимости от текущего статуса
            if operation.status == OperationStatus.PENDING:
                # PENDING: только изменение статуса
                result = self._cancel_pending_operation(operation, cancelled_by, cancellation_reason)
                
            elif operation.status == OperationStatus.PROCESSING:
                # PROCESSING: только изменение статуса (line_items загружены, но списание не выполнено)
                result = self._cancel_processing_operation(operation, cancelled_by, cancellation_reason)
                
            elif operation.status == OperationStatus.STOCK_DEDUCTED:
                # STOCK_DEDUCTED: восстановление остатков
                result = self._cancel_stock_deducted_operation(
                    operation, cancelled_by, cancellation_reason, rollback_operations
                )
                
            elif operation.status == OperationStatus.COMPLETED:
                # COMPLETED: полный откат (остатки + микросервис)
                result = self._cancel_completed_operation(
                    operation, cancelled_by, cancellation_reason, rollback_operations
                )
                
            else:
                return SyncResult(
                    success=False,
                    operation_id=operation_id,
                    error=f"Cannot cancel operation in status {operation.status.value}"
                )
            
            if result.success:
                # Обновляем поля отмены
                operation.cancelled_by = cancelled_by
                operation.cancellation_reason = cancellation_reason
                operation.rollback_operations = rollback_operations if rollback_operations else None
                operation.updated_at = datetime.utcnow()
                
                # Логируем успешную отмену
                self.standardized_logger.log_status_transition(
                    operation_id=operation_id,
                    from_status=old_status,
                    to_status=OperationStatus.CANCELLED,
                    reason=f"Операция отменена: {cancellation_reason}",
                    additional_context={
                        "cancelled_by": cancelled_by,
                        "rollback_operations_count": len(rollback_operations)
                    }
                )
                
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation_id,
                    action=LogAction.CANCELLATION_COMPLETED,
                    details=f"Отмена операции завершена успешно",
                    additional_context={
                        "cancelled_by": cancelled_by,
                        "rollback_operations": rollback_operations
                    }
                )
                
                self.session.commit()
            
            return result
            
        except Exception as e:
            self.session.rollback()
            self.standardized_logger.log_error_with_context(
                operation_id=operation_id,
                error=e,
                context={
                    "method": "cancel_operation",
                    "cancelled_by": cancelled_by,
                    "cancellation_reason": cancellation_reason
                }
            )
            
            return SyncResult(
                success=False,
                operation_id=operation_id,
                error=str(e)
            )
    
    def _cancel_pending_operation(
        self,
        operation: PendingStockOperation,
        cancelled_by: str,
        cancellation_reason: str
    ) -> SyncResult:
        """
        Отмена операции в статусе PENDING.
        
        Требует только изменения статуса, так как никаких изменений еще не было сделано.
        """
        operation.status = OperationStatus.CANCELLED
        
        return SyncResult(
            success=True,
            operation_id=operation.id,
            details={
                "message": "PENDING operation cancelled - no rollback needed",
                "cancelled_by": cancelled_by,
                "cancellation_reason": cancellation_reason
            }
        )
    
    def _cancel_processing_operation(
        self,
        operation: PendingStockOperation,
        cancelled_by: str,
        cancellation_reason: str
    ) -> SyncResult:
        """
        Отмена операции в статусе PROCESSING.
        
        Требует только изменения статуса, так как line_items загружены,
        но списание остатков еще не выполнено.
        """
        operation.status = OperationStatus.CANCELLED
        
        return SyncResult(
            success=True,
            operation_id=operation.id,
            details={
                "message": "PROCESSING operation cancelled - no rollback needed",
                "cancelled_by": cancelled_by,
                "cancellation_reason": cancellation_reason,
                "line_items_count": len(operation.line_items) if operation.line_items else 0
            }
        )
    
    def _cancel_stock_deducted_operation(
        self,
        operation: PendingStockOperation,
        cancelled_by: str,
        cancellation_reason: str,
        rollback_operations: List[UUID]
    ) -> SyncResult:
        """
        Отмена операции в статусе STOCK_DEDUCTED.
        
        Требует восстановления остатков на складе, так как списание уже выполнено,
        но синхронизация с микросервисом еще не произошла.
        """
        try:
            # Восстанавливаем остатки на складе
            rollback_result = self._rollback_stock_changes(operation, rollback_operations)
            if not rollback_result.success:
                return rollback_result
            
            operation.status = OperationStatus.CANCELLED
            
            return SyncResult(
                success=True,
                operation_id=operation.id,
                details={
                    "message": "STOCK_DEDUCTED operation cancelled - stock restored",
                    "cancelled_by": cancelled_by,
                    "cancellation_reason": cancellation_reason,
                    "rollback_operations": rollback_operations
                }
            )
            
        except Exception as e:
            self.standardized_logger.log_error_with_context(
                operation_id=operation.id,
                error=e,
                context={
                    "method": "_cancel_stock_deducted_operation",
                    "cancelled_by": cancelled_by
                }
            )
            
            return SyncResult(
                success=False,
                operation_id=operation.id,
                error=f"Failed to rollback stock changes: {str(e)}"
            )
    
    def _cancel_completed_operation(
        self,
        operation: PendingStockOperation,
        cancelled_by: str,
        cancellation_reason: str,
        rollback_operations: List[UUID]
    ) -> SyncResult:
        """
        Отмена операции в статусе COMPLETED.
        
        Требует полного отката: восстановления остатков на складе
        и отката статуса в микросервисе.
        """
        try:
            # Восстанавливаем остатки на складе
            stock_rollback_result = self._rollback_stock_changes(operation, rollback_operations)
            if not stock_rollback_result.success:
                return stock_rollback_result
            
            # Откатываем статус в микросервисе
            microservice_rollback_result = self._rollback_microservice_status(operation)
            if not microservice_rollback_result.success:
                # Если откат микросервиса не удался, логируем предупреждение, но не прерываем процесс
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation.id,
                    action=LogAction.MICROSERVICE_ROLLBACK_STARTED,
                    details=f"Предупреждение: не удалось откатить статус в микросервисе: {microservice_rollback_result.error}",
                    status="warning",
                    additional_context={
                        "microservice_error": microservice_rollback_result.error
                    }
                )
            
            operation.status = OperationStatus.CANCELLED
            
            return SyncResult(
                success=True,
                operation_id=operation.id,
                details={
                    "message": "COMPLETED operation cancelled - full rollback performed",
                    "cancelled_by": cancelled_by,
                    "cancellation_reason": cancellation_reason,
                    "rollback_operations": rollback_operations,
                    "microservice_rollback_success": microservice_rollback_result.success,
                    "microservice_rollback_error": microservice_rollback_result.error if not microservice_rollback_result.success else None
                }
            )
            
        except Exception as e:
            self.standardized_logger.log_error_with_context(
                operation_id=operation.id,
                error=e,
                context={
                    "method": "_cancel_completed_operation",
                    "cancelled_by": cancelled_by
                }
            )
            
            return SyncResult(
                success=False,
                operation_id=operation.id,
                error=f"Failed to perform full rollback: {str(e)}"
            )
    
    def _rollback_stock_changes(
        self,
        operation: PendingStockOperation,
        rollback_operations: List[UUID]
    ) -> SyncResult:
        """
        Восстановление остатков на складе.
        
        Создает операции корректировки для восстановления списанных остатков.
        
        Args:
            operation: Операция для отката
            rollback_operations: Список ID операций отката (будет заполнен)
            
        Returns:
            SyncResult с результатом отката
        """
        try:
            if not operation.line_items:
                return SyncResult(
                    success=False,
                    operation_id=operation.id,
                    error="No line items to rollback"
                )
            
            self.standardized_logger.log_action_with_timing(
                operation_id=operation.id,
                action=LogAction.STOCK_ROLLBACK_STARTED,
                details=f"Начат откат остатков для {len(operation.line_items)} позиций"
            )
            
            products_data = []
            
            # Подготавливаем данные для восстановления остатков
            for item in operation.line_items:
                offer = item.get('offer', {})
                external = offer.get('external', {})
                sku = external.get('id')
                quantity = item.get('quantity', 0)
                offer_name = offer.get('name', '')
                
                if not sku or quantity <= 0:
                    continue
                
                # Восстанавливаем остатки (добавляем обратно)
                self.inventory_manager.add_stock(
                    sku,
                    operation.warehouse,
                    quantity
                )
                
                products_data.append({
                    'sku': sku,
                    'quantity': quantity,
                    'name': offer_name
                })
            
            # Создаем операцию корректировки для отслеживания
            if products_data:
                adjustment_operation = self._create_adjustment_operation(
                    operation, products_data, "rollback"
                )
                if adjustment_operation:
                    rollback_operations.append(adjustment_operation.id)
            
            self.standardized_logger.log_action_with_timing(
                operation_id=operation.id,
                action=LogAction.STOCK_ROLLBACK_COMPLETED,
                details=f"Откат остатков завершен для {len(products_data)} позиций",
                additional_context={
                    "warehouse": operation.warehouse,
                    "products_count": len(products_data)
                }
            )
            
            return SyncResult(
                success=True,
                operation_id=operation.id,
                details={
                    "message": "Stock rollback completed",
                    "products_count": len(products_data),
                    "warehouse": operation.warehouse
                }
            )
            
        except Exception as e:
            self.standardized_logger.log_error_with_context(
                operation_id=operation.id,
                error=e,
                context={
                    "method": "_rollback_stock_changes",
                    "warehouse": operation.warehouse
                }
            )
            
            return SyncResult(
                success=False,
                operation_id=operation.id,
                error=f"Stock rollback failed: {str(e)}"
            )
    
    def _rollback_microservice_status(self, operation: PendingStockOperation) -> SyncResult:
        """
        Откат статуса в микросервисе.
        
        Устанавливает is_stock_updated = False для заказа в микросервисе.
        
        Args:
            operation: Операция для отката
            
        Returns:
            SyncResult с результатом отката
        """
        try:
            self.standardized_logger.log_action_with_timing(
                operation_id=operation.id,
                action=LogAction.MICROSERVICE_ROLLBACK_STARTED,
                details=f"Начат откат статуса в микросервисе для заказа {operation.order_id}"
            )
            
            start_time = datetime.utcnow()
            
            # Вызываем API микросервиса для отката статуса
            result = self.orders_client.update_stock_status(
                token_id=UUID(operation.token_id),
                order_id=operation.order_id,
                is_stock_updated=False
            )
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if result and hasattr(result, 'success') and result.success:
                self.standardized_logger.log_action_with_timing(
                    operation_id=operation.id,
                    action=LogAction.MICROSERVICE_ROLLBACK_COMPLETED,
                    details=f"Откат статуса в микросервисе успешен для заказа {operation.order_id}",
                    execution_time_ms=execution_time
                )
                
                return SyncResult(
                    success=True,
                    operation_id=operation.id,
                    details={
                        "message": "Microservice status rollback completed",
                        "order_id": operation.order_id,
                        "execution_time_ms": execution_time
                    }
                )
            else:
                error_msg = getattr(result, 'error', 'Unknown error') if result else 'No response'
                
                self.standardized_logger.log_error_with_context(
                    operation_id=operation.id,
                    error=Exception(error_msg),
                    context={
                        "method": "_rollback_microservice_status",
                        "order_id": operation.order_id,
                        "execution_time_ms": execution_time
                    }
                )
                
                return SyncResult(
                    success=False,
                    operation_id=operation.id,
                    error=f"Microservice rollback failed: {error_msg}"
                )
                
        except Exception as e:
            self.standardized_logger.log_error_with_context(
                operation_id=operation.id,
                error=e,
                context={
                    "method": "_rollback_microservice_status",
                    "order_id": operation.order_id
                }
            )
            
            return SyncResult(
                success=False,
                operation_id=operation.id,
                error=f"Microservice rollback failed: {str(e)}"
            )
    
    def _create_adjustment_operation(
        self,
        original_operation: PendingStockOperation,
        products_data: List[Dict[str, Any]],
        operation_type: str
    ) -> Optional[Any]:
        """
        Создание операции корректировки для отслеживания отката.
        
        Args:
            original_operation: Исходная операция
            products_data: Данные о товарах для корректировки
            operation_type: Тип операции (rollback, adjustment)
            
        Returns:
            Созданная операция корректировки или None при ошибке
        """
        try:
            # Создаем операцию корректировки через operations_service
            adjustment_operation = self.operations_service.create_adjustment_operation(
                warehouse_id=original_operation.warehouse,
                products_data=products_data,
                comment=f"Откат операции синхронизации {original_operation.id} ({operation_type})",
                user_email="system@cancellation_service",
                session=self.session
            )
            
            self.standardized_logger.log_action_with_timing(
                operation_id=original_operation.id,
                action=LogAction.STOCK_ROLLBACK_COMPLETED,
                details=f"Создана операция корректировки ID: {adjustment_operation.id}",
                additional_context={
                    "adjustment_operation_id": str(adjustment_operation.id),
                    "operation_type": operation_type,
                    "products_count": len(products_data)
                }
            )
            
            return adjustment_operation
            
        except Exception as e:
            self.standardized_logger.log_error_with_context(
                operation_id=original_operation.id,
                error=e,
                context={
                    "method": "_create_adjustment_operation",
                    "operation_type": operation_type,
                    "products_count": len(products_data)
                }
            )
            
            return None


def get_operation_cancellation_service(session: Session) -> OperationCancellationService:
    """
    Фабричная функция для создания экземпляра OperationCancellationService.
    
    Args:
        session: Сессия базы данных
        
    Returns:
        OperationCancellationService: Настроенный экземпляр сервиса
    """
    return OperationCancellationService(session)