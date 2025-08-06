# Дополнение: Валидация складских остатков и система уведомлений

## Важные дополнения к архитектуре синхронизации

### 1. Валидация присутствия товара на складе

#### 1.1 Предварительная проверка остатков

Перед любым списанием необходимо проверить наличие товара на складе:

```python
# app/services/stock_validation_service.py
from typing import Dict, List, Optional
from app.services.warehouse.manager import InventoryManager
from app.models.warehouse import Product, Stock
from sqlmodel import Session, select

class StockValidationResult:
    def __init__(self, valid: bool, available_quantity: int = 0, error_message: str = ""):
        self.valid = valid
        self.available_quantity = available_quantity
        self.error_message = error_message

class StockValidationService:
    def __init__(self, session: Session, inventory_manager: InventoryManager):
        self.session = session
        self.inventory_manager = inventory_manager
    
    def validate_stock_availability(
        self, 
        sku: str, 
        required_quantity: int, 
        warehouse: str = "Ирина"
    ) -> StockValidationResult:
        """Проверка наличия товара на складе перед списанием."""
        
        try:
            # Проверяем существование товара в БД
            product = self.session.exec(select(Product).where(Product.sku == sku)).first()
            if not product:
                return StockValidationResult(
                    valid=False, 
                    error_message=f"Товар с SKU {sku} не найден в базе данных"
                )
            
            # Получаем остатки на складе
            stock_by_warehouse = self.inventory_manager.get_stock_by_sku(sku)
            available_quantity = stock_by_warehouse.get(warehouse, 0)
            
            if available_quantity < required_quantity:
                return StockValidationResult(
                    valid=False,
                    available_quantity=available_quantity,
                    error_message=f"Недостаточно товара {sku} на складе {warehouse}. "
                                f"Требуется: {required_quantity}, доступно: {available_quantity}"
                )
            
            return StockValidationResult(valid=True, available_quantity=available_quantity)
            
        except Exception as e:
            return StockValidationResult(
                valid=False,
                error_message=f"Ошибка при проверке остатков: {str(e)}"
            )
    
    def validate_order_items_availability(
        self, 
        order_items: List[Dict[str, any]], 
        warehouse: str = "Ирина"
    ) -> Dict[str, StockValidationResult]:
        """Валидация всех позиций заказа."""
        
        results = {}
        
        for item in order_items:
            sku = item.get("sku") or item.get("external_id")
            quantity = item.get("quantity", 1)
            
            if not sku:
                results[f"item_{item.get('id', 'unknown')}"] = StockValidationResult(
                    valid=False,
                    error_message="SKU не указан в позиции заказа"
                )
                continue
            
            results[sku] = self.validate_stock_availability(sku, quantity, warehouse)
        
        return results
```

#### 1.2 Интеграция валидации в сервис синхронизации

```python
# Обновленный StockSynchronizationService с валидацией
class StockSynchronizationService:
    def __init__(
        self, 
        session: Session, 
        orders_client: OrdersClient,
        inventory_manager: InventoryManager
    ):
        self.session = session
        self.orders_client = orders_client
        self.inventory_manager = inventory_manager
        self.validation_service = StockValidationService(session, inventory_manager)
        self.logger = logging.getLogger("stock.sync")
        self.config = stock_sync_config
    
    def _get_account_name_by_token_id(self, token_id: str) -> str:
        """Получение имени аккаунта по token_id."""
        try:
            from app.models.allegro_token import AllegroToken
            token = self.session.exec(
                select(AllegroToken).where(AllegroToken.id_ == token_id)
            ).first()
            return token.account_name if token else f"Unknown({token_id})"
        except Exception:
            return f"Unknown({token_id})"
    
    async def sync_stock_deduction_with_validation(
        self,
        token_id: str,
        order_id: str,
        sku: str,
        quantity: int,
        warehouse: str = "Ирина"
    ) -> SyncResult:
        """Синхронное списание с предварительной валидацией остатков."""
        
        account_name = self._get_account_name_by_token_id(token_id)
        
        # 1. ВАЛИДАЦИЯ ОСТАТКОВ
        validation_result = self.validation_service.validate_stock_availability(
            sku, quantity, warehouse
        )
        
        if not validation_result.valid:
            self.logger.error(f"Stock validation failed for order {order_id}: {validation_result.error_message}")
            
            # Создаем операцию со статусом FAILED для логирования
            operation = PendingStockOperation(
                order_id=order_id,
                operation_type=OperationType.DEDUCTION,
                sku=sku,
                quantity=quantity,
                warehouse=warehouse,
                token_id=token_id,
                status=OperationStatus.FAILED,
                error_message=validation_result.error_message,
                next_retry_at=datetime.utcnow()  # Не будет retry при валидационных ошибках
            )
            self.session.add(operation)
            self.session.commit()
            
            self._log_operation(operation.id, "validation_failed", validation_result.error_message)
            
            # Отправляем алерт о недостатке товара
            await self._send_stock_shortage_alert(
                account_name, order_id, sku, quantity, validation_result.available_quantity, warehouse
            )
            
            return SyncResult(False, operation.id, validation_result.error_message)
        
        # 2. СПИСАНИЕ ЛОКАЛЬНО (только если валидация прошла успешно)
        try:
            self.inventory_manager.remove_as_sale(sku, warehouse, quantity)
            self.logger.info(f"Local stock deduction successful: {sku} x{quantity} from {warehouse}")
        except Exception as e:
            self.logger.error(f"Local stock deduction failed: {e}")
            
            # Отправляем алерт об ошибке списания
            await self._send_stock_deduction_error_alert(account_name, order_id, sku, quantity, warehouse, str(e))
            
            return SyncResult(False, None, f"Local deduction failed: {str(e)}")
        
        # 3. СИНХРОНИЗАЦИЯ С МИКРОСЕРВИСОМ
        return await self.sync_stock_deduction(token_id, order_id, sku, quantity, warehouse)
    
    async def _send_stock_shortage_alert(
        self, 
        account_name: str,
        order_id: str, 
        sku: str, 
        required: int, 
        available: int, 
        warehouse: str
    ):
        """Отправка алерта о недостатке товара на складе."""
        
        message = (
            f"❌ НЕДОСТАТОК ТОВАРА НА СКЛАДЕ\n"
            f"👤 Аккаунт: **{account_name}**\n"
            f"📦 SKU: {sku}\n"
            f"📋 Заказ: {order_id}\n"
            f"🏪 Склад: {warehouse}\n"
            f"📊 Требуется: {required} шт.\n"
            f"📊 Доступно: {available} шт.\n"
            f"⚠️ Недостает: {required - available} шт.\n"
            f"🕐 Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"\n💡 Требуется пополнение склада!"
        )
        
        await self._send_telegram_alert(message, priority="critical")
    
    async def _send_stock_deduction_error_alert(
        self, 
        account_name: str,
        order_id: str, 
        sku: str, 
        quantity: int, 
        warehouse: str, 
        error: str
    ):
        """Отправка алерта об ошибке списания со склада."""
        
        message = (
            f"🚨 ОШИБКА СПИСАНИЯ СО СКЛАДА\n"
            f"👤 Аккаунт: **{account_name}**\n"
            f"📦 SKU: {sku}\n"
            f"📋 Заказ: {order_id}\n"
            f"🏪 Склад: {warehouse}\n"
            f"📊 Количество: {quantity} шт.\n"
            f"❌ Ошибка: {error}\n"
            f"🕐 Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"\n🔧 Требуется проверка системы складского учета!"
        )
        
        await self._send_telegram_alert(message, priority="critical")
```

### 2. Система уведомлений в Telegram

#### 2.1 Интеграция с существующим TelegramManager

```python
# app/services/stock_sync_telegram_service.py
from app.services.tg_client import TelegramManager
from typing import Optional
import logging

class StockSyncTelegramService:
    def __init__(self):
        self.telegram_manager = TelegramManager()
        self.logger = logging.getLogger("stock.sync.telegram")
    
    async def send_alert(self, message: str, priority: str = "normal"):
        """Отправка алерта в Telegram."""
        try:
            # Добавляем префикс приоритета
            if priority == "critical":
                message = f"🚨🚨🚨 КРИТИЧЕСКИЙ АЛЕРТ\n{message}"
            elif priority == "warning":  
                message = f"⚠️ ПРЕДУПРЕЖДЕНИЕ\n{message}"
            
            self.telegram_manager.send_message(message)
            self.logger.info("Telegram alert sent successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to send Telegram alert: {e}")
    
    async def send_stock_shortage_alert(
        self, 
        account_name: str,
        order_id: str, 
        sku: str, 
        required: int, 
        available: int, 
        warehouse: str
    ):
        """Специализированный алерт о недостатке товара."""
        
        shortage = required - available
        shortage_percentage = (shortage / required) * 100 if required > 0 else 0
        
        message = (
            f"📦 НЕДОСТАТОК ТОВАРА\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Аккаунт: **{account_name}**\n"
            f"🏷️ SKU: `{sku}`\n"
            f"📋 Заказ: `{order_id}`\n"
            f"🏪 Склад: {warehouse}\n"
            f"📊 Требуется: **{required}** шт.\n"
            f"📊 Доступно: **{available}** шт.\n"
            f"❌ Недостает: **{shortage}** шт. ({shortage_percentage:.1f}%)\n"
            f"🕐 {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💡 **Действия:**\n"
            f"• Проверить поставки\n"
            f"• Пополнить склад\n"
            f"• Связаться с поставщиком"
        )
        
        await self.send_alert(message, priority="critical")
    
    async def send_sync_failure_alert(
        self, 
        account_name: str,
        order_id: str, 
        sku: str, 
        operation_id: str,
        error_message: str,
        retry_count: int
    ):
        """Алерт о неудачной синхронизации с микросервисом."""
        
        message = (
            f"🔄 СБОЙ СИНХРОНИЗАЦИИ\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Аккаунт: **{account_name}**\n"
            f"🏷️ SKU: `{sku}`\n"
            f"📋 Заказ: `{order_id}`\n"
            f"🆔 Операция: `{operation_id}`\n"
            f"🔁 Попытка: {retry_count}\n"
            f"❌ Ошибка: {error_message}\n"
            f"🕐 {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 **Действия:**\n"
            f"• Проверить микросервис Allegro\n"
            f"• Проверить сетевое соединение\n"
            f"• При необходимости - ручная синхронизация"
        )
        
        priority = "critical" if retry_count >= 3 else "warning"
        await self.send_alert(message, priority=priority)
    
    async def send_reconciliation_discrepancy_alert(
        self, 
        discrepancies: List[Dict],
        total_orders_checked: int
    ):
        """Алерт о найденных расхождениях при сверке."""
        
        if not discrepancies:
            return
        
        # Группируем расхождения по аккаунтам
        by_account = {}
        for disc in discrepancies:
            account = disc.get('account_name', 'Unknown')
            if account not in by_account:
                by_account[account] = []
            by_account[account].append(disc)
        
        discrepancy_summary = []
        total_shown = 0
        
        for account_name, account_discrepancies in by_account.items():
            discrepancy_summary.append(f"\n**{account_name}:**")
            
            for disc in account_discrepancies[:3]:  # Максимум 3 на аккаунт
                discrepancy_summary.append(
                    f"  • `{disc['order_id']}` ({disc['sku']}): "
                    f"локально {'списан' if disc['local_deducted'] else 'не списан'}, "
                    f"удаленно {'списан' if disc['remote_updated'] else 'не списан'}"
                )
                total_shown += 1
            
            if len(account_discrepancies) > 3:
                discrepancy_summary.append(f"  ... и еще {len(account_discrepancies) - 3} для {account_name}")
        
        if len(discrepancies) > total_shown:
            discrepancy_summary.append(f"\n... всего {len(discrepancies)} расхождений")
        
        message = (
            f"⚖️ РАСХОЖДЕНИЯ В ДАННЫХ\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Проверено заказов: {total_orders_checked}\n"
            f"❌ Найдено расхождений: **{len(discrepancies)}**\n"
            f"🏢 Аккаунтов затронуто: **{len(by_account)}**\n"
            f"🕐 {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **Расхождения по аккаунтам:**"
            f"{''.join(discrepancy_summary)}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔧 **Требуется ручная проверка!**"
        )
        
        await self.send_alert(message, priority="critical")
    
    async def send_system_health_alert(
        self, 
        pending_operations: int,
        failed_operations: int,
        stale_operations: int,
        by_account_stats: Optional[Dict] = None
    ):
        """Алерт о состоянии системы синхронизации."""
        
        status_emoji = "🔴" if (pending_operations > 100 or stale_operations > 0) else "🟡" if pending_operations > 50 else "🟢"
        
        message = (
            f"{status_emoji} СТАТУС СИНХРОНИЗАЦИИ\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ В очереди: **{pending_operations}** операций\n"
            f"❌ Неудачных: **{failed_operations}** операций\n"
            f"🐌 Застрявших: **{stale_operations}** операций\n"
            f"🕐 {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n"
        )
        
        # Добавляем статистику по аккаунтам если доступна
        if by_account_stats:
            message += f"━━━━━━━━━━━━━━━━━━━\n📊 **По аккаунтам:**\n"
            for account, stats in by_account_stats.items():
                message += f"• **{account}**: {stats['pending']} в очереди, {stats['failed']} неудач\n"
        
        message += f"━━━━━━━━━━━━━━━━━━━"
        
        if stale_operations > 0 or pending_operations > 100:
            message += f"\n⚠️ **Требуется внимание администратора!**"
            priority = "warning"
        else:
            priority = "normal"
        
        await self.send_alert(message, priority=priority)
```

#### 2.2 Интеграция уведомлений в основной сервис

```python
# Обновляем StockSynchronizationService
class StockSynchronizationService:
    def __init__(
        self, 
        session: Session, 
        orders_client: OrdersClient,
        inventory_manager: InventoryManager
    ):
        # ... существующий код ...
        self.telegram_service = StockSyncTelegramService()
    
    async def _send_telegram_alert(self, message: str, priority: str = "normal"):
        """Отправка уведомления в Telegram."""
        try:
            await self.telegram_service.send_alert(message, priority)
        except Exception as e:
            self.logger.error(f"Failed to send Telegram alert: {e}")
    
    # Обновленный метод retry с уведомлениями
    async def process_pending_operations(self, limit: int = 50) -> Dict[str, int]:
        """Обработка операций из очереди с уведомлениями о критических сбоях."""
        
        results = await super().process_pending_operations(limit)
        
        # Отправляем уведомления о критических сбоях
        if results["max_retries_reached"] > 0:
            # Получаем детали неудачных операций с информацией об аккаунтах
            failed_operations_query = (
                select(PendingStockOperation, AllegroToken.account_name)
                .join(AllegroToken, PendingStockOperation.token_id == AllegroToken.id_)
                .where(PendingStockOperation.status == OperationStatus.FAILED)
                .order_by(PendingStockOperation.updated_at.desc())
                .limit(5)
            )
            
            failed_operations = self.session.exec(failed_operations_query).all()
            
            for operation, account_name in failed_operations:
                await self.telegram_service.send_sync_failure_alert(
                    account_name=account_name,
                    order_id=operation.order_id,
                    sku=operation.sku,
                    operation_id=str(operation.id),
                    error_message=operation.error_message or "Unknown error",
                    retry_count=operation.retry_count
                )
        
        return results
    
    async def reconcile_stock_status(self, token_id: UUID, limit: int = 100):
        """Сверка состояний с уведомлениями о расхождениях."""
        
        # ... логика сверки ...
        
        discrepancies = []  # Результат сверки с account_name
        
        if discrepancies:
            await self.telegram_service.send_reconciliation_discrepancy_alert(
                discrepancies=discrepancies,
                total_orders_checked=limit
            )
        
        return {"discrepancies": discrepancies, "total_checked": limit}
```

### 3. Мониторинг состояния системы с учетом аккаунтов

#### 3.1 Celery задача мониторинга с детализацией по аккаунтам

```python
@celery.task
def monitor_sync_health_with_account_details():
    """Мониторинг здоровья системы синхронизации с детализацией по аккаунтам."""
    try:
        with SessionLocal() as session:
            from app.services.stock_sync_telegram_service import StockSyncTelegramService
            telegram_service = StockSyncTelegramService()
            
            # Общая статистика
            pending_count = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(PendingStockOperation.status == OperationStatus.PENDING)
            ).first()
            
            failed_count = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(PendingStockOperation.status == OperationStatus.FAILED)
            ).first()
            
            stale_count = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(
                    PendingStockOperation.status == OperationStatus.PENDING,
                    PendingStockOperation.created_at < datetime.utcnow() - timedelta(hours=6)
                )
            ).first()
            
            # Статистика по аккаунтам
            by_account_query = (
                select(
                    AllegroToken.account_name,
                    func.count().filter(PendingStockOperation.status == OperationStatus.PENDING).label('pending'),
                    func.count().filter(PendingStockOperation.status == OperationStatus.FAILED).label('failed')
                )
                .select_from(PendingStockOperation)
                .join(AllegroToken, PendingStockOperation.token_id == AllegroToken.id_)
                .group_by(AllegroToken.account_name)
                .having(
                    func.count().filter(PendingStockOperation.status == OperationStatus.PENDING) > 0
                    or func.count().filter(PendingStockOperation.status == OperationStatus.FAILED) > 0
                )
            )
            
            account_stats_result = session.exec(by_account_query).all()
            by_account_stats = {
                account_name: {"pending": pending, "failed": failed}
                for account_name, pending, failed in account_stats_result
            }
            
            # Отправляем алерт если есть проблемы
            if pending_count > 100 or failed_count > 10 or stale_count > 0:
                await telegram_service.send_system_health_alert(
                    pending_operations=pending_count,
                    failed_operations=failed_count,
                    stale_operations=stale_count,
                    by_account_stats=by_account_stats
                )
            
            logger.info(f"Health check: pending={pending_count}, failed={failed_count}, stale={stale_count}, accounts_affected={len(by_account_stats)}")
            
    except Exception as e:
        logger.error(f"Error in sync health monitoring: {e}")

# Ежедневный отчет с детализацией по аккаунтам
@celery.task  
def send_daily_sync_report():
    """Ежедневный отчет о работе системы синхронизации с детализацией по аккаунтам."""
    try:
        with SessionLocal() as session:
            from app.services.stock_sync_telegram_service import StockSyncTelegramService
            telegram_service = StockSyncTelegramService()
            
            # Статистика за последние 24 часа
            yesterday = datetime.utcnow() - timedelta(days=1)
            
            # Общая статистика
            completed_today = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(
                    PendingStockOperation.status == OperationStatus.COMPLETED,
                    PendingStockOperation.completed_at >= yesterday
                )
            ).first()
            
            failed_today = session.exec(
                select(func.count()).select_from(PendingStockOperation)
                .where(
                    PendingStockOperation.status == OperationStatus.FAILED,
                    PendingStockOperation.updated_at >= yesterday
                )
            ).first()
            
            # Статистика по аккаунтам за день
            daily_by_account_query = (
                select(
                    AllegroToken.account_name,
                    func.count().filter(PendingStockOperation.status == OperationStatus.COMPLETED).label('completed'),
                    func.count().filter(PendingStockOperation.status == OperationStatus.FAILED).label('failed')
                )
                .select_from(PendingStockOperation)
                .join(AllegroToken, PendingStockOperation.token_id == AllegroToken.id_)
                .where(PendingStockOperation.created_at >= yesterday)
                .group_by(AllegroToken.account_name)
                .having(func.count() > 0)
            )
            
            account_daily_stats = session.exec(daily_by_account_query).all()
            
            total_operations = completed_today + failed_today
            success_rate = (completed_today / total_operations * 100) if total_operations > 0 else 0
            
            message = (
                f"📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ СИНХРОНИЗАЦИИ\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📅 Дата: {datetime.utcnow().strftime('%d.%m.%Y')}\n"
                f"✅ Успешных операций: **{completed_today}**\n"
                f"❌ Неудачных операций: **{failed_today}**\n"
                f"📈 Процент успеха: **{success_rate:.1f}%**\n"
            )
            
            if account_daily_stats:
                message += f"━━━━━━━━━━━━━━━━━━━\n📊 **По аккаунтам:**\n"
                for account_name, completed, failed in account_daily_stats:
                    total_account = completed + failed
                    account_success_rate = (completed / total_account * 100) if total_account > 0 else 0
                    message += f"• **{account_name}**: {completed}✅ {failed}❌ ({account_success_rate:.1f}%)\n"
            
            message += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"{'🟢 Система работает стабильно' if success_rate > 95 else '🟡 Требуется внимание' if success_rate > 85 else '🔴 Критические проблемы'}"
            )
            
            priority = "normal" if success_rate > 95 else "warning" if success_rate > 85 else "critical"
            await telegram_service.send_alert(message, priority=priority)
            
    except Exception as e:
        logger.error(f"Error sending daily report: {e}")

# Обновляем расписание Celery
celery.conf.beat_schedule.update({
    'monitor-sync-health-with-accounts': {
        'task': 'app.services.stock_synchronization_tasks.monitor_sync_health_with_account_details',
        'schedule': 1800.0,  # каждые 30 минут
    },
    'send-daily-sync-report-with-accounts': {
        'task': 'app.services.stock_synchronization_tasks.send_daily_sync_report',
        'schedule': crontab(hour=9, minute=0),  # каждый день в 9:00 UTC
    },
})
```

### 4. Обновленный алгоритм обработки заказа с аккаунтами

```python
# Полный алгоритм с валидацией и уведомлениями включая аккаунт
async def process_allegro_order_with_full_validation(
    order_data: Dict, 
    token_id: str, 
    warehouse: str = "Ирина"
):
    """Полная обработка заказа Allegro с валидацией и уведомлениями."""
    
    order_id = order_data["id"]
    line_items = order_data.get("lineItems", [])
    
    # Получаем название аккаунта
    from app.models.allegro_token import AllegroToken
    token = session.exec(select(AllegroToken).where(AllegroToken.id_ == token_id)).first()
    account_name = token.account_name if token else f"Unknown({token_id})"
    
    # 1. ВАЛИДАЦИЯ ВСЕХ ПОЗИЦИЙ ЗАКАЗА
    validation_service = StockValidationService(session, inventory_manager)
    
    order_items_for_validation = [
        {
            "sku": item.get("offer", {}).get("external", {}).get("id"),
            "quantity": item.get("quantity", 1),
            "item_id": item.get("id")
        }
        for item in line_items
    ]
    
    validation_results = validation_service.validate_order_items_availability(
        order_items_for_validation, warehouse
    )
    
    # Проверяем есть ли проблемы с валидацией
    validation_errors = [
        sku for sku, result in validation_results.items() 
        if not result.valid
    ]
    
    if validation_errors:
        telegram_service = StockSyncTelegramService()
        
        for sku in validation_errors:
            result = validation_results[sku]
            item_data = next((item for item in order_items_for_validation if item.get("sku") == sku), {})
            await telegram_service.send_stock_shortage_alert(
                account_name=account_name,
                order_id=order_id,
                sku=sku,
                required=item_data.get("quantity", 1),
                available=result.available_quantity,
                warehouse=warehouse
            )
        
        raise ValueError(f"Stock validation failed for order {order_id} (account: {account_name}): {validation_errors}")
    
    # 2. ОБРАБОТКА КАЖДОЙ ПОЗИЦИИ С СИНХРОНИЗАЦИЕЙ
    sync_service = StockSynchronizationService(session, orders_client, inventory_manager)
    
    processing_results = []
    
    for item in line_items:
        sku = item.get("offer", {}).get("external", {}).get("id")
        quantity = item.get("quantity", 1)
        
        if not sku:
            logger.warning(f"SKU not found for item {item.get('id')} in order {order_id} (account: {account_name})")
            continue
        
        # Списание с валидацией и синхронизацией
        result = await sync_service.sync_stock_deduction_with_validation(
            token_id=token_id,
            order_id=order_id,
            sku=sku,
            quantity=quantity,
            warehouse=warehouse
        )
        
        processing_results.append({
            "sku": sku,
            "success": result.success,
            "error": result.error,
            "operation_id": str(result.operation_id) if result.operation_id else None
        })
    
    # 3. ИТОГОВОЕ ЛОГИРОВАНИЕ И УВЕДОМЛЕНИЯ
    successful_items = [r for r in processing_results if r["success"]]
    failed_items = [r for r in processing_results if not r["success"]]
    
    logger.info(f"Order {order_id} (account: {account_name}) processing completed: {len(successful_items)} successful, {len(failed_items)} failed")
    
    # Уведомление о критических ошибках обработки заказа
    if len(failed_items) > len(successful_items):
        telegram_service = StockSyncTelegramService()
        
        message = (
            f"🚨 КРИТИЧЕСКАЯ ОШИБКА ОБРАБОТКИ ЗАКАЗА\n"
            f"👤 Аккаунт: **{account_name}**\n"
            f"📋 Заказ: `{order_id}`\n"
            f"❌ Неудачно обработано: **{len(failed_items)}** из {len(processing_results)} позиций\n"
            f"🕐 {datetime.utcnow().strftime('%d.%m.%Y %H:%M:%S')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **Неудачные позиции:**\n"
        )
        
        for failed_item in failed_items[:3]:  # Показываем максимум 3 позиции
            message += f"• SKU: `{failed_item['sku']}` - {failed_item['error']}\n"
        
        if len(failed_items) > 3:
            message += f"• ... и еще {len(failed_items) - 3} позиций\n"
        
        message += f"━━━━━━━━━━━━━━━━━━━\n🔧 **Требуется немедленная проверка!**"
        
        await telegram_service.send_alert(message, priority="critical")
    
    return {
        "order_id": order_id,
        "account_name": account_name,
        "total_items": len(processing_results),
        "successful_items": len(successful_items),
        "failed_items": len(failed_items),
        "results": processing_results
    }
```

## Итоговые дополнения к архитектуре

### Ключевые принципы с учетом аккаунтов

✅ **Валидация перед действием** - обязательная проверка остатков перед любым списанием
✅ **Идентификация аккаунта** - во всех уведомлениях указывается название аккаунта Allegro
✅ **Немедленные уведомления** - алерты о критических ситуациях в реальном времени  
✅ **Детализированная диагностика** - полная информация в уведомлениях для быстрого реагирования
✅ **Градация приоритетов** - разные уровни алертов для разных типов проблем
✅ **Регулярная отчетность** - ежедневные сводки с группировкой по аккаунтам

### Типы уведомлений с указанием аккаунта

1. **🚨 Критические** - недостаток товара, критические сбои (с указанием аккаунта)
2. **⚠️ Предупреждения** - превышение лимитов retry, застрявшие операции (с группировкой по аккаунтам)
3. **📊 Информационные** - ежедневные отчеты со статистикой по каждому аккаунту

### Структура уведомлений

Каждое уведомление теперь содержит:
- **👤 Аккаунт**: Название аккаунта Allegro
- **📋 Заказ**: ID заказа
- **📦 SKU**: Артикул товара
- **🏪 Склад**: Название склада
- **📊 Данные**: Количества, статистика
- **🕐 Время**: Точное время события
- **🔧 Действия**: Рекомендации для устранения проблемы

Эти дополнения обеспечивают полную интеграцию с существующей системой уведомлений, включают обязательную валидацию всех складских операций и предоставляют детальную информацию для быстрого реагирования на проблемы с указанием конкретного аккаунта Allegro.