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
from app.services.warehouse.manager import InventoryManager
from app.core.stock_sync_config import stock_sync_config


class StockSynchronizationService:
    """
    Основной сервис для синхронизации складских операций между
    локальной системой и микросервисом Allegro.
    """
    
    def __init__(
        self, 
        session: Session, 
        orders_client: OrdersClient,
        tokens_client: AllegroTokenMicroserviceClient,
        inventory_manager: InventoryManager
    ):
        self.session = session
        self.orders_client = orders_client
        self.tokens_client = tokens_client
        self.inventory_manager = inventory_manager
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
            # Создаем запись операции
            operation = PendingStockOperation(
                order_id=order_id,
                operation_type=OperationType.DEDUCTION,
                sku=sku,
                quantity=quantity,
                warehouse=warehouse,
                token_id=token_id,
                next_retry_at=datetime.utcnow() + timedelta(seconds=self.config.retry_initial_delay)
            )
            self.session.add(operation)
            self.session.commit()
            operation_id = operation.id
            
            self._log_operation(
                operation.id,
                "created",
                f"Operation created for order {order_id}, account {account_name}"
            )
            
            # Немедленная попытка синхронизации
            sync_success = self._try_sync_with_microservice(operation)
            
            if sync_success:
                operation.status = OperationStatus.COMPLETED
                operation.completed_at = datetime.utcnow()
                self.session.commit()
                
                self._log_operation(
                    operation.id, 
                    "completed", 
                    f"Immediate sync successful for account {account_name}"
                )
                return SyncResult(
                    success=True, 
                    operation_id=operation_id,
                    details={"account_name": account_name, "immediate_sync": True}
                )
            else:
                # Оставляем в pending для retry
                self._log_operation(
                    operation.id, 
                    "queued", 
                    f"Immediate sync failed for account {account_name}, queued for retry"
                )
                return SyncResult(
                    success=False, 
                    operation_id=operation_id, 
                    error="Immediate sync failed, queued for retry",
                    details={"account_name": account_name, "queued_for_retry": True}
                )
                
        except Exception as e:
            self.logger.error(f"Error in sync_stock_deduction for account {account_name}: {e}")
            if operation_id:
                self._log_operation(operation_id, "error", f"Exception: {str(e)}")
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
                    "Microservice sync successful",
                    execution_time_ms=execution_time
                )
                return True
            else:
                error_msg = getattr(result, 'error', 'Unknown error') if result else 'No response'
                self._log_operation(
                    operation.id, 
                    "sync_failed", 
                    f"Microservice sync failed: {error_msg}",
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
                f"Exception: {str(e)}"
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
        status: str = "info"
    ):
        """
        Логирование операции синхронизации.
        
        Args:
            operation_id: ID операции
            action: Действие (created, retry, completed, failed, etc.)
            details: Детальное описание
            execution_time_ms: Время выполнения в миллисекундах
            status: Статус (info, warning, error)
        """
        try:
            log_entry = StockSynchronizationLog(
                operation_id=operation_id,
                action=action,
                status=status,
                details={"message": details},
                execution_time_ms=execution_time_ms
            )
            self.session.add(log_entry)
            self.session.commit()
        except Exception as e:
            self.logger.error(f"Failed to log operation {operation_id}: {e}")
    
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
        statement = (
            select(PendingStockOperation)
            .where(
                PendingStockOperation.status == OperationStatus.PENDING,
                PendingStockOperation.next_retry_at <= now,
                PendingStockOperation.retry_count < PendingStockOperation.max_retries
            )
            .order_by(PendingStockOperation.created_at)
            .limit(limit)
        )
        
        operations = self.session.exec(statement).all()
        
        for operation in operations:
            result.processed += 1
            account_name = self._get_account_name_by_token_id(operation.token_id)
            
            # Обновляем статус на processing
            operation.status = OperationStatus.PROCESSING
            operation.retry_count += 1
            self.session.commit()
            
            self._log_operation(
                operation.id,
                "retry",
                f"Retry attempt {operation.retry_count} for account {account_name}"
            )
            
            # Попытка синхронизации
            sync_success = self._try_sync_with_microservice(operation)
            
            if sync_success:
                operation.status = OperationStatus.COMPLETED
                operation.completed_at = datetime.utcnow()
                result.succeeded += 1
                self._log_operation(
                    operation.id, 
                    "completed", 
                    f"Retry {operation.retry_count} successful for account {account_name}"
                )
            else:
                if operation.retry_count >= operation.max_retries:
                    operation.status = OperationStatus.FAILED
                    result.max_retries_reached += 1
                    self._log_operation(
                        operation.id, 
                        "max_retries", 
                        f"Max retries reached: {operation.max_retries} for account {account_name}",
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
                        f"Retry {operation.retry_count} failed for account {account_name}, next in {delay}s",
                        status="warning"
                    )
            
            operation.updated_at = datetime.utcnow()
            self.session.commit()
            
            # Добавляем детали обработанной операции
            result.details.append({
                "operation_id": str(operation.id),
                "account_name": account_name,
                "sku": operation.sku,
                "order_id": operation.order_id,
                "retry_count": operation.retry_count,
                "status": operation.status,
                "success": sync_success
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
                        "sku": local_operation.sku if local_operation else "unknown",
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
                
                result = self.sync_stock_deduction(
                    token_id=token_id,
                    order_id=order_id,
                    sku=discrepancy.get('sku', 'unknown'),
                    quantity=1,  # Предполагаем 1 единицу для расхождения
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
                f"Operation rolled back manually"
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