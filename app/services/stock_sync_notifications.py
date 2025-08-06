import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from uuid import UUID

from app.services.tg_client import TelegramManager
from app.core.stock_sync_config import stock_sync_config
from app.schemas.stock_synchronization import (
    SyncResult, 
    ProcessingResult, 
    ReconciliationResult,
    StockValidationResult
)


class StockSyncNotificationService:
    """
    Сервис для отправки Telegram уведомлений о событиях синхронизации складских остатков.
    Поддерживает персонализированные уведомления по аккаунтам и приоритизацию сообщений.
    """
    
    def __init__(self):
        self.logger = logging.getLogger("stock.notifications")
        self.config = stock_sync_config
        
        # Инициализируем Telegram менеджеры для разных типов уведомлений
        self._managers = {}
        self._init_telegram_managers()
    
    def _init_telegram_managers(self):
        """Инициализация Telegram менеджеров для разных групп."""
        try:
            # Главная группа уведомлений
            if self.config.telegram_main_chat_id:
                self._managers['main'] = TelegramManager(
                    chat_id=self.config.telegram_main_chat_id
                )
            
            # Группа критических уведомлений  
            if self.config.telegram_critical_chat_id:
                self._managers['critical'] = TelegramManager(
                    chat_id=self.config.telegram_critical_chat_id
                )
            
            # Группа технических уведомлений
            if self.config.telegram_tech_chat_id:
                self._managers['tech'] = TelegramManager(
                    chat_id=self.config.telegram_tech_chat_id
                )
                
        except Exception as e:
            self.logger.error(f"Ошибка инициализации Telegram менеджеров: {e}")
    
    def _send_message(
        self, 
        message: str, 
        chat_type: str = 'main',
        priority: str = 'normal',
        account_name: Optional[str] = None
    ) -> bool:
        """
        Отправка сообщения в указанный чат.
        
        Args:
            message: Текст сообщения
            chat_type: Тип чата ('main', 'critical', 'tech')
            priority: Приоритет ('low', 'normal', 'high', 'critical')
            account_name: Название аккаунта для персонализации
            
        Returns:
            bool: True если сообщение отправлено успешно
        """
        try:
            # Выбираем менеджер чата
            manager = self._managers.get(chat_type)
            if not manager:
                self.logger.warning(f"Telegram менеджер для чата '{chat_type}' не найден")
                # Fallback на главный чат
                manager = self._managers.get('main')
                if not manager:
                    self.logger.error("Ни один Telegram менеджер не доступен")
                    return False
            
            # Форматируем сообщение с приоритетом и аккаунтом
            formatted_message = self._format_message(message, priority, account_name)
            
            # Отправляем сообщение
            result = manager.send_message(formatted_message)
            
            if result:
                self.logger.info(f"Уведомление отправлено в чат '{chat_type}': {account_name or 'общее'}")
                return True
            else:
                self.logger.error(f"Не удалось отправить уведомление в чат '{chat_type}'")
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка отправки уведомления: {e}")
            return False
    
    def _format_message(
        self, 
        message: str, 
        priority: str, 
        account_name: Optional[str]
    ) -> str:
        """Форматирование сообщения с эмодзи и структурой."""
        # Эмодзи для приоритетов
        priority_emoji = {
            'low': 'ℹ️',
            'normal': '📊', 
            'high': '⚠️',
            'critical': '🚨'
        }
        
        emoji = priority_emoji.get(priority, '📊')
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        
        # Заголовок сообщения
        header = f"{emoji} <b>Синхронизация складов</b>"
        
        # Добавляем информацию об аккаунте
        if account_name:
            header += f" | <code>{account_name}</code>"
        
        # Собираем итоговое сообщение
        formatted = f"{header}\n\n{message}\n\n<i>🕒 {timestamp} UTC</i>"
        
        return formatted
    
    def notify_sync_failure(
        self, 
        result: SyncResult, 
        account_name: str,
        retry_count: int = 0
    ):
        """
        Уведомление о неудачной синхронизации.
        
        Args:
            result: Результат синхронизации
            account_name: Название аккаунта
            retry_count: Количество попыток
        """
        operation_id = str(result.operation_id) if result.operation_id else "unknown"
        
        message = (
            f"❌ <b>Ошибка синхронизации</b>\n"
            f"Аккаунт: <code>{account_name}</code>\n"
            f"ID операции: <code>{operation_id}</code>\n"
            f"Попытка: {retry_count + 1}\n"
            f"Ошибка: <i>{result.error}</i>"
        )
        
        # Определяем приоритет по количеству попыток
        if retry_count >= self.config.retry_max_attempts - 1:
            priority = 'critical'
            chat_type = 'critical'
        elif retry_count >= 3:
            priority = 'high' 
            chat_type = 'main'
        else:
            priority = 'normal'
            chat_type = 'main'
        
        self._send_message(message, chat_type, priority, account_name)
    
    def notify_max_retries_reached(
        self, 
        operation_id: UUID,
        account_name: str,
        error_details: str
    ):
        """
        Уведомление о превышении лимита попыток.
        
        Args:
            operation_id: ID операции
            account_name: Название аккаунта  
            error_details: Детали последней ошибки
        """
        message = (
            f"🚨 <b>КРИТИЧНО: Превышен лимит попыток</b>\n"
            f"Аккаунт: <code>{account_name}</code>\n"
            f"ID операции: <code>{str(operation_id)}</code>\n"
            f"Максимум попыток: {self.config.retry_max_attempts}\n"
            f"Последняя ошибка: <i>{error_details}</i>\n\n"
            f"⚡ <b>Требуется ручное вмешательство!</b>"
        )
        
        self._send_message(message, 'critical', 'critical', account_name)
    
    def notify_stock_validation_failure(
        self, 
        validation_result: StockValidationResult,
        account_name: str,
        order_id: Optional[str] = None
    ):
        """
        Уведомление о провале валидации остатков.
        
        Args:
            validation_result: Результат валидации
            account_name: Название аккаунта
            order_id: ID заказа (если применимо)
        """
        shortage = validation_result.shortage_quantity
        
        message = (
            f"⚠️ <b>Недостаток товара</b>\n"
            f"Аккаунт: <code>{account_name}</code>\n"
            f"SKU: <code>{validation_result.sku}</code>\n"
            f"Склад: <code>{validation_result.warehouse}</code>\n"
            f"Доступно: {validation_result.available_quantity}\n"
            f"Требуется: {validation_result.required_quantity}\n"
            f"Недостает: <b>{shortage}</b>"
        )
        
        if order_id:
            message += f"\nЗаказ: <code>{order_id}</code>"
        
        # Определяем приоритет по критичности недостачи
        shortage_percent = validation_result.shortage_percentage
        if shortage_percent >= 100:  # Товар отсутствует полностью
            priority = 'critical'
            chat_type = 'critical'
        elif shortage_percent >= 50:  # Недостает больше половины
            priority = 'high'
            chat_type = 'main'
        else:
            priority = 'normal'
            chat_type = 'main'
        
        self._send_message(message, chat_type, priority, account_name)
    
    def notify_reconciliation_discrepancies(
        self, 
        result: ReconciliationResult,
        account_names: List[str]
    ):
        """
        Уведомление о найденных расхождениях при сверке.
        
        Args:
            result: Результат сверки
            account_names: Список проверенных аккаунтов
        """
        accounts_str = ", ".join(account_names) if len(account_names) <= 3 else f"{len(account_names)} аккаунтов"
        
        message = (
            f"🔍 <b>Результат сверки состояний</b>\n"
            f"Аккаунты: <code>{accounts_str}</code>\n"
            f"Проверено: {result.total_checked}\n"
            f"Расхождений: <b>{result.discrepancies_found}</b>\n"
            f"Исправлено автоматически: {result.auto_fixed}\n"
            f"Требует ручной проверки: <b>{result.requires_manual_review}</b>"
        )
        
        if result.discrepancies_found > 0:
            priority = 'high' if result.requires_manual_review > 0 else 'normal'
        else:
            priority = 'low'
        
        self._send_message(message, 'tech', priority)
    
    def notify_processing_summary(
        self, 
        result: ProcessingResult
    ):
        """
        Уведомление о результатах обработки очереди операций.
        
        Args:
            result: Результат обработки
        """
        if result.processed == 0:
            return  # Не отправляем уведомление если нечего было обрабатывать
        
        message = (
            f"📈 <b>Обработка очереди завершена</b>\n"
            f"Обработано операций: {result.processed}\n"
            f"Успешно: <b>{result.succeeded}</b>\n"
            f"Неудачно: {result.failed}\n"
            f"Достигли лимита попыток: <b>{result.max_retries_reached}</b>"
        )
        
        # Определяем приоритет по проценту успеха
        if result.processed > 0:
            success_rate = (result.succeeded / result.processed) * 100
            if success_rate >= 90:
                priority = 'low'
            elif success_rate >= 70:
                priority = 'normal' 
            else:
                priority = 'high'
        else:
            priority = 'normal'
        
        self._send_message(message, 'tech', priority)
    
    def notify_system_health(
        self, 
        health_data: Dict[str, Any]
    ):
        """
        Уведомление о состоянии системы синхронизации.
        
        Args:
            health_data: Данные о состоянии системы
        """
        status = health_data.get('health_status', 'unknown')
        pending = health_data.get('pending_operations', 0)
        failed = health_data.get('failed_operations', 0)
        stale = health_data.get('stale_operations', 0)
        
        # Эмодзи для статуса
        status_emoji = {
            'healthy': '✅',
            'warning': '⚠️',
            'error': '🚨',
            'unknown': '❓'
        }
        
        emoji = status_emoji.get(status, '❓')
        
        message = (
            f"{emoji} <b>Состояние системы синхронизации</b>\n"
            f"Статус: <b>{status.upper()}</b>\n"
            f"Ожидающих операций: {pending}\n"
            f"Провальных операций: {failed}\n"
            f"Застрявших операций: {stale}"
        )
        
        # Определяем приоритет и чат по состоянию
        if status == 'error' or stale > 0:
            priority = 'critical'
            chat_type = 'critical'
        elif status == 'warning' or failed > 10:
            priority = 'high'
            chat_type = 'main'
        else:
            priority = 'low'
            chat_type = 'tech'
        
        self._send_message(message, chat_type, priority)
    
    def notify_daily_summary(
        self, 
        summary_data: Dict[str, Any]
    ):
        """
        Ежедневная сводка по синхронизации.
        
        Args:
            summary_data: Сводные данные за день
        """
        completed = summary_data.get('completed_today', 0)
        failed = summary_data.get('failed_operations', 0) 
        accounts_count = summary_data.get('active_accounts', 0)
        
        message = (
            f"📊 <b>Ежедневная сводка синхронизации</b>\n"
            f"Дата: <code>{datetime.utcnow().strftime('%Y-%m-%d')}</code>\n\n"
            f"✅ Успешных операций: <b>{completed}</b>\n"
            f"❌ Провальных операций: {failed}\n"
            f"👥 Активных аккаунтов: {accounts_count}\n\n"
            f"📈 Общий успех: <b>{(completed/(completed+failed)*100):.1f}%</b>" 
            if (completed + failed) > 0 else "📈 Операций не было"
        )
        
        self._send_message(message, 'tech', 'low')
    
    def notify_custom_alert(
        self, 
        title: str,
        details: str,
        priority: str = 'normal',
        account_name: Optional[str] = None
    ):
        """
        Отправка произвольного уведомления.
        
        Args:
            title: Заголовок уведомления
            details: Детали сообщения
            priority: Приоритет ('low', 'normal', 'high', 'critical')
            account_name: Название аккаунта (опционально)
        """
        message = f"<b>{title}</b>\n\n{details}"
        
        # Выбираем чат по приоритету
        if priority == 'critical':
            chat_type = 'critical'
        elif priority in ('high', 'normal'):
            chat_type = 'main'
        else:
            chat_type = 'tech'
        
        self._send_message(message, chat_type, priority, account_name)


# Создаем глобальный экземпляр сервиса
stock_sync_notifications = StockSyncNotificationService()