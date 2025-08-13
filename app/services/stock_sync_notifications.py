import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from uuid import UUID
from sqlmodel import Session, select
from collections import deque
import threading
import time
from pydantic import BaseModel, Field

from app.services.tg_client import TelegramManager
from app.core.stock_sync_config import stock_sync_config
from app.core.config import settings
from app.models.stock_synchronization import OrderNotificationTracker
from app.schemas.stock_synchronization import (
    SyncResult,
    ProcessingResult,
    ReconciliationResult,
    StockValidationResult
)


class PendingMessage(BaseModel):
    """Сообщение в очереди отложенной отправки."""
    message: str
    chat_type: str
    priority: str
    account_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    max_retries: int = 10
    
    def should_retry(self) -> bool:
        """Проверяет можно ли повторить отправку."""
        if self.retry_count >= self.max_retries:
            return False
        if self.next_retry_at and datetime.utcnow() < self.next_retry_at:
            return False
        return True
    
    def schedule_retry(self, delay_minutes: Optional[int] = None):
        """Планирует следующую попытку отправки."""
        if delay_minutes is None:
            # Экспоненциальный backoff: 1, 2, 4, 8, 16, ... минут
            delay_minutes = min(2 ** self.retry_count, 60)  # Максимум 60 минут
        
        self.retry_count += 1
        self.next_retry_at = datetime.utcnow() + timedelta(minutes=delay_minutes)


class MessageQueue:
    """Потокобезопасная очередь для отложенных сообщений."""
    
    def __init__(self, max_size: int = 1000):
        self._queue = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._logger = logging.getLogger("notifications.queue")
    
    def add(self, message: PendingMessage):
        """Добавляет сообщение в очередь."""
        with self._lock:
            self._queue.append(message)
            self._logger.info(f"Message queued: {message.chat_type} priority={message.priority}")
    
    def get_ready_messages(self) -> List[PendingMessage]:
        """Возвращает сообщения готовые к отправке."""
        ready = []
        now = datetime.utcnow()
        
        with self._lock:
            # Фильтруем готовые к отправке сообщения
            remaining = deque()
            
            while self._queue:
                msg = self._queue.popleft()
                
                if msg.should_retry() and (msg.next_retry_at is None or msg.next_retry_at <= now):
                    ready.append(msg)
                elif msg.retry_count < msg.max_retries:
                    remaining.append(msg)
                else:
                    self._logger.error(f"Message dropped after {msg.max_retries} retries: {msg.message[:100]}...")
            
            # Возвращаем неготовые сообщения в очередь
            self._queue.extend(remaining)
        
        return ready
    
    def size(self) -> int:
        """Возвращает размер очереди."""
        with self._lock:
            return len(self._queue)
    
    def clear_old_messages(self, max_age_hours: int = 24):
        """Удаляет старые сообщения."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        with self._lock:
            remaining = deque()
            removed_count = 0
            
            while self._queue:
                msg = self._queue.popleft()
                if msg.created_at >= cutoff:
                    remaining.append(msg)
                else:
                    removed_count += 1
            
            self._queue.extend(remaining)
            
            if removed_count > 0:
                self._logger.info(f"Removed {removed_count} old messages from queue")


class StockSyncNotificationService:
    """
    Сервис для отправки Telegram уведомлений о событиях синхронизации складских остатков.
    Поддерживает персонализированные уведомления по аккаунтам, приоритизацию сообщений,
    и автоматическую обработку 429 ошибок с очередью отложенной отправки.
    """
    
    def __init__(self, session: Optional[Session] = None):
        self.session = session
        self.logger = logging.getLogger("stock.notifications")
        self.config = stock_sync_config
        self.base_url = settings.BASE_URL
        
        # Инициализируем Telegram менеджеры для разных типов уведомлений
        self._managers = {}
        self._init_telegram_managers()
        
        # Очередь для отложенных сообщений
        self._message_queue = MessageQueue(max_size=getattr(self.config, 'MAX_PENDING_MESSAGES', 1000))
        
        # Статистика отправки
        self._stats = {
            'sent_success': 0,
            'sent_failed': 0,
            'queued_messages': 0,
            'retry_success': 0,
            'dropped_messages': 0
        }

    def _get_operation_url(self, operation_id: str) -> Optional[str]:
        """Генерирует URL для просмотра деталей операции."""
        if not self.base_url:
            return None
        return f"{self.base_url}/stock-sync/monitor/operation/{operation_id}"
    
    def _get_monitoring_url(self, params: str = "") -> Optional[str]:
        """Генерирует URL для страницы мониторинга."""
        if not self.base_url:
            return None
        url = f"{self.base_url}/stock-sync/monitor"
        if params:
            url += f"?{params}"
        return url
    
    def _init_telegram_managers(self):
        """Инициализация Telegram менеджеров для разных групп."""
        try:
            # Главная группа уведомлений
            if self.config.TELEGRAM_MAIN_CHAT_ID:
                self._managers['main'] = TelegramManager(
                    chat_id=self.config.TELEGRAM_MAIN_CHAT_ID
                )
            
            # Группа критических уведомлений  
            if self.config.TELEGRAM_CRITICAL_CHAT_ID:
                self._managers['critical'] = TelegramManager(
                    chat_id=self.config.TELEGRAM_CRITICAL_CHAT_ID
                )
            
            # Группа технических уведомлений
            if self.config.TELEGRAM_TECHNICAL_CHAT_ID:
                self._managers['tech'] = TelegramManager(
                    chat_id=self.config.TELEGRAM_TECHNICAL_CHAT_ID
                )
                
        except Exception as e:
            self.logger.error(f"Ошибка инициализации Telegram менеджеров: {e}")
    
    def _send_message(
        self,
        message: str,
        chat_type: str = 'main',
        priority: str = 'normal',
        account_name: Optional[str] = None,
        allow_queue: bool = True
    ) -> bool:
        """
        Отправка сообщения в указанный чат с поддержкой очереди отложенных сообщений.
        
        Args:
            message: Текст сообщения
            chat_type: Тип чата ('main', 'critical', 'tech')
            priority: Приоритет ('low', 'normal', 'high', 'critical')
            account_name: Название аккаунта для персонализации
            allow_queue: Разрешить постановку в очередь при провале
            
        Returns:
            bool: True если сообщение отправлено успешно или поставлено в очередь
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
                    if allow_queue:
                        self._queue_message(message, chat_type, priority, account_name)
                        return True
                    return False
            
            # Форматируем сообщение с приоритетом и аккаунтом
            formatted_message = self._format_message(message, priority, account_name)
            
            # Отправляем сообщение
            result = manager.send_message(formatted_message)
            
            if result is not None:
                self.logger.info(f"Уведомление отправлено в чат '{chat_type}': {account_name or 'общее'}")
                self._stats['sent_success'] += 1
                return True
            else:
                self.logger.warning(f"Не удалось отправить уведомление в чат '{chat_type}', добавляю в очередь")
                self._stats['sent_failed'] += 1
                
                if allow_queue:
                    self._queue_message(message, chat_type, priority, account_name)
                    return True
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка отправки уведомления: {e}")
            self._stats['sent_failed'] += 1
            
            if allow_queue:
                self._queue_message(message, chat_type, priority, account_name)
                return True
            return False
    
    def _queue_message(
        self,
        message: str,
        chat_type: str,
        priority: str,
        account_name: Optional[str]
    ):
        """Добавляет сообщение в очередь отложенной отправки."""
        pending_msg = PendingMessage(
            message=message,
            chat_type=chat_type,
            priority=priority,
            account_name=account_name
        )
        
        self._message_queue.add(pending_msg)
        self._stats['queued_messages'] += 1
        self.logger.info(f"Сообщение добавлено в очередь: {chat_type} priority={priority}")
    
    def process_message_queue(self, max_messages: int = 50) -> Dict[str, int]:
        """
        Обрабатывает очередь отложенных сообщений.
        
        Args:
            max_messages: Максимальное количество сообщений для обработки за раз
            
        Returns:
            Статистика обработки: {'processed': int, 'success': int, 'requeued': int, 'dropped': int}
        """
        stats = {'processed': 0, 'success': 0, 'requeued': 0, 'dropped': 0}
        
        # Очищаем старые сообщения
        self._message_queue.clear_old_messages()
        
        # Получаем готовые к отправке сообщения
        ready_messages = self._message_queue.get_ready_messages()
        
        if not ready_messages:
            return stats
        
        # Ограничиваем количество обрабатываемых сообщений
        messages_to_process = ready_messages[:max_messages]
        
        self.logger.info(f"Обработка {len(messages_to_process)} сообщений из очереди")
        
        for msg in messages_to_process:
            stats['processed'] += 1
            
            # Пытаемся отправить без добавления в очередь
            success = self._send_message(
                msg.message,
                msg.chat_type,
                msg.priority,
                msg.account_name,
                allow_queue=False
            )
            
            if success:
                stats['success'] += 1
                self._stats['retry_success'] += 1
                self.logger.debug(f"Сообщение из очереди отправлено успешно после {msg.retry_count} попыток")
            else:
                # Планируем повторную попытку
                if msg.retry_count < msg.max_retries:
                    msg.schedule_retry()
                    self._message_queue.add(msg)
                    stats['requeued'] += 1
                    self.logger.debug(f"Сообщение возвращено в очередь, попытка {msg.retry_count}/{msg.max_retries}")
                else:
                    stats['dropped'] += 1
                    self._stats['dropped_messages'] += 1
                    self.logger.error(f"Сообщение отброшено после {msg.max_retries} попыток: {msg.message[:100]}...")
        
        if stats['processed'] > 0:
            self.logger.info(f"Очередь обработана: {stats}")
        
        return stats
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Возвращает статус очереди сообщений и общую статистику."""
        return {
            'queue_size': self._message_queue.size(),
            'stats': self._stats.copy(),
            'total_attempts': self._stats['sent_success'] + self._stats['sent_failed'],
            'success_rate': (
                self._stats['sent_success'] / (self._stats['sent_success'] + self._stats['sent_failed']) * 100
                if (self._stats['sent_success'] + self._stats['sent_failed']) > 0 else 0
            )
        }
    
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
        
        # Добавляем ссылку на детали операции, если доступен базовый URL
        operation_url = self._get_operation_url(operation_id)
        if operation_url:
            message += f"\n<a href=\"{operation_url}\">📋 Подробности</a>"
        
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
        
        # Проверяем можно ли отправить уведомление о максимальных попытках
        if self.session and not self._can_send_order_notification(
            str(operation_id), account_name, 'max_retries'
        ):
            self.logger.info(f"Max retries notification suppressed for operation {operation_id}")
            return
        
        self._send_message(message, 'critical', 'critical', account_name)
        
        # Записываем факт отправки уведомления
        if self.session:
            self._record_order_notification(
                str(operation_id), account_name, 'max_retries', suppress_for_hours=24
            )
    
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
            f"Недостает: <b>{shortage}</b>\n"
            + (f"Заказ: <code>{order_id}</code>\n" if order_id else "")
        )
        
        # Добавляем ссылку на мониторинг, если доступен базовый URL
        monitoring_url = self._get_monitoring_url("status=failed&days=7")
        if monitoring_url:
            message += f"\n<a href=\"{monitoring_url}\">📋 Мониторинг</a>"
        
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
        
        # Проверяем можно ли отправить уведомление о валидации (только для заказов)
        if self.session and order_id and not self._can_send_order_notification(
            order_id, account_name, 'validation_failure'
        ):
            self.logger.info(f"Validation failure notification suppressed for order {order_id}")
            return
        
        self._send_message(message, chat_type, priority, account_name)
        
        # Записываем факт отправки уведомления о валидации
        if self.session and order_id:
            self._record_order_notification(
                order_id, account_name, 'validation_failure', suppress_for_hours=6
            )
    
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

    def _can_send_order_notification(
        self,
        order_key: str,  # Может быть order_id или operation_id
        account_name: str,
        notification_type: str,
        min_interval_minutes: int = 30
    ) -> bool:
        """
        Проверяет можно ли отправить уведомление для заказа.
        
        Args:
            order_key: ID заказа или операции
            account_name: Название аккаунта
            notification_type: Тип уведомления
            min_interval_minutes: Минимальный интервал между уведомлениями
            
        Returns:
            bool: True если можно отправить уведомление
        """
        try:
            # Пытаемся найти существующий tracker
            # Для operation_id нужно получить order info, пока используем упрощенную логику
            stmt = select(OrderNotificationTracker).where(
                OrderNotificationTracker.order_id.contains(order_key) |
                OrderNotificationTracker.account_name == account_name
            ).order_by(OrderNotificationTracker.created_at.desc()).limit(1)
            
            tracker = self.session.exec(stmt).first()
            
            if tracker:
                return tracker.can_send_notification(notification_type, min_interval_minutes)
            else:
                # Если tracker не найден, можно отправлять
                return True
                
        except Exception as e:
            self.logger.error(f"Error checking notification permission: {e}")
            # В случае ошибки разрешаем отправку
            return True

    def _record_order_notification(
        self,
        order_key: str,
        account_name: str,
        notification_type: str,
        suppress_for_hours: int = 0
    ):
        """
        Записывает факт отправки уведомления для заказа.
        
        Args:
            order_key: ID заказа или операции
            account_name: Название аккаунта
            notification_type: Тип уведомления
            suppress_for_hours: Подавить уведомления на указанное время
        """
        try:
            # Для упрощения создаем новый tracker каждый раз
            # В реальности нужно найти существующий или создать новый
            tracker = OrderNotificationTracker(
                token_id="unknown",  # Пока не можем извлечь из order_key
                order_id=order_key,
                account_name=account_name
            )
            
            tracker.record_notification(notification_type, suppress_for_hours)
            
            self.session.add(tracker)
            self.session.commit()
            
        except Exception as e:
            self.logger.error(f"Error recording notification: {e}")

    def notify_order_validation_failure(
        self,
        token_id: str,
        order_id: str,
        account_name: str,
        validation_errors: List[str],
        order_details: Optional[Dict[str, Any]] = None,
        operation_id: Optional[str] = None
    ):
        """
        Уведомление о провале валидации заказа с контролем спама.
        
        Args:
            token_id: ID токена
            order_id: ID заказа
            account_name: Название аккаунта
            validation_errors: Список ошибок валидации
            order_details: Дополнительная информация о заказе
            operation_id: ID операции для ссылки на детали (опционально)
        """
        # Создаем или обновляем tracker
        order_key = f"{token_id}:{order_id}"
        
        # Проверяем можно ли отправить уведомление
        if self.session:
            tracker = self.session.exec(
                select(OrderNotificationTracker).where(
                    OrderNotificationTracker.token_id == token_id,
                    OrderNotificationTracker.order_id == order_id
                )
            ).first()
            
            if tracker and not tracker.can_send_notification('validation_failure'):
                self.logger.info(f"Validation failure notification suppressed for order {order_key}")
                return
            
            if not tracker:
                tracker = OrderNotificationTracker(
                    token_id=token_id,
                    order_id=order_id,
                    account_name=account_name,
                    order_details=order_details
                )
                self.session.add(tracker)
        
        # Формируем красиво отформатированные ошибки
        formatted_errors = self._format_validation_errors(validation_errors, order_details)
        
        message = (
            f"⚠️ <b>Провал валидации складских остатков</b>\n"
            f"Аккаунт: <code>{account_name}</code>\n"
            f"Заказ: <code>{order_id}</code>\n\n"
            f"{formatted_errors}\n\n"
            f"💡 <i>Проверьте остатки товаров и повторите списание</i>"
        )
        
        # Добавляем ссылку на детали операции, если доступен operation_id
        if operation_id:
            operation_url = self._get_operation_url(operation_id)
            if operation_url:
                message += f"\n📋 Подробности операции: {operation_url}"
        else:
            # Fallback на мониторинг, если operation_id не передан
            monitoring_url = self._get_monitoring_url(f"order_id={order_id}&account={account_name}")
            if monitoring_url:
                message += f"\n📋 Подробности: {monitoring_url}"
        
        self._send_message(message, 'main', 'high', account_name)
        
        # Записываем факт отправки
        if self.session and tracker:
            tracker.record_notification('validation_failure', suppress_for_hours=1)
            self.session.commit()

    def _format_validation_errors(self, validation_errors: List[str], order_details: Optional[Dict[str, Any]] = None) -> str:
        """
        Форматирует ошибки валидации для красивого отображения в Telegram.
        
        Args:
            validation_errors: Список ошибок валидации
            order_details: Детали заказа с информацией о товарах
            
        Returns:
            Красиво отформатированная строка с ошибками
        """
        if not validation_errors:
            return "<b>❓ Неизвестные ошибки валидации</b>"
        
        # Группируем ошибки по типам
        sku_errors = {}
        general_errors = []
        
        for error in validation_errors:
            if "Товар '" in error and "':" in error:
                # Извлекаем SKU и сообщение об ошибке
                try:
                    parts = error.split("':")
                    sku_part = parts[0].replace("Товар '", "")
                    error_msg = parts[1].strip() if len(parts) > 1 else "Неизвестная ошибка"
                    sku_errors[sku_part] = error_msg
                except Exception:
                    general_errors.append(error)
            else:
                general_errors.append(error)
        
        formatted_parts = []
        
        # Общие ошибки
        if general_errors:
            formatted_parts.append("<b>🚫 Общие ошибки:</b>")
            for error in general_errors[:3]:  # Ограничиваем 3 общими ошибками
                formatted_parts.append(f"• {error}")
            if len(general_errors) > 3:
                formatted_parts.append(f"• ... и еще {len(general_errors) - 3} ошибок")
        
        # Ошибки по товарам
        if sku_errors:
            formatted_parts.append("<b>📦 Проблемы с товарами:</b>")
            
            # Пытаемся получить дополнительную информацию о товарах из order_details
            items_info = {}
            if order_details and "lineItems" in order_details:
                for item in order_details["lineItems"]:
                    sku = item.get("offer", {}).get("external", {}).get("id")
                    if sku:
                        items_info[sku] = {
                            "name": item.get("offer", {}).get("name", "Неизвестный товар"),
                            "quantity": item.get("quantity", 1)
                        }
            
            # Форматируем ошибки по товарам (ограничиваем 5 товарами)
            count = 0
            for sku, error_msg in list(sku_errors.items())[:5]:
                count += 1
                
                # Получаем дополнительную информацию о товаре
                item_info = items_info.get(sku, {})
                product_name = item_info.get("name", "")
                quantity = item_info.get("quantity", "")
                
                # Форматируем строку товара
                sku_line = f"<code>{sku}</code>"
                
                if product_name:
                    # Обрезаем длинные названия
                    if len(product_name) > 30:
                        product_name = product_name[:27] + "..."
                    sku_line += f" ({product_name})"
                
                if quantity:
                    sku_line += f" x{quantity}"
                
                # Добавляем кнопку копирования SKU
                
                formatted_parts.append(f"• {sku_line}")
                formatted_parts.append(f"  └─ ❌ {error_msg}")
            
            if len(sku_errors) > 5:
                formatted_parts.append(f"• ... и еще {len(sku_errors) - 5} товаров")
        
        return "\n".join(formatted_parts)


class NotificationServiceManager:
    """Менеджер для управления фоновой обработкой очереди уведомлений."""
    
    def __init__(self):
        self._services = {}  # session_id -> service instance
        self._background_thread = None
        self._stop_event = threading.Event()
        self._processing_interval = 300  # 5 минут
        self.logger = logging.getLogger("notifications.manager")
    
    def get_service(self, session: Optional[Session] = None) -> StockSyncNotificationService:
        """Получает экземпляр сервиса для указанной сессии."""
        session_id = id(session) if session else "global"
        
        if session_id not in self._services:
            self._services[session_id] = StockSyncNotificationService(session=session)
        
        return self._services[session_id]
    
    def start_background_processing(self, interval_seconds: int = 300):
        """Запускает фоновую обработку очереди сообщений."""
        if self._background_thread and self._background_thread.is_alive():
            self.logger.warning("Background processing already running")
            return
        
        self._processing_interval = interval_seconds
        self._stop_event.clear()
        
        self._background_thread = threading.Thread(
            target=self._background_worker,
            name="notifications-queue-processor",
            daemon=True
        )
        self._background_thread.start()
        self.logger.info(f"Started background queue processing with {interval_seconds}s interval")
    
    def stop_background_processing(self):
        """Останавливает фоновую обработку."""
        if not self._background_thread or not self._background_thread.is_alive():
            return
        
        self._stop_event.set()
        self._background_thread.join(timeout=10)
        
        if self._background_thread.is_alive():
            self.logger.warning("Background thread did not stop gracefully")
        else:
            self.logger.info("Background processing stopped")
    
    def _background_worker(self):
        """Фоновый обработчик очереди сообщений."""
        self.logger.info("Background queue processor started")
        
        while not self._stop_event.is_set():
            try:
                # Обрабатываем очереди всех активных сервисов
                total_processed = 0
                
                for service in self._services.values():
                    stats = service.process_message_queue(max_messages=20)
                    total_processed += stats['processed']
                
                if total_processed > 0:
                    self.logger.info(f"Background processing: {total_processed} messages processed")
                
            except Exception as e:
                self.logger.error(f"Error in background queue processing: {e}")
            
            # Ждем до следующего цикла
            self._stop_event.wait(timeout=self._processing_interval)
        
        self.logger.info("Background queue processor finished")
    
    def get_all_services_status(self) -> Dict[str, Any]:
        """Возвращает статус всех активных сервисов."""
        status = {}
        
        for session_id, service in self._services.items():
            status[f"service_{session_id}"] = service.get_queue_status()
        
        status['background_processing'] = {
            'enabled': self._background_thread and self._background_thread.is_alive(),
            'interval_seconds': self._processing_interval
        }
        
        return status


# Глобальный менеджер сервисов
_notification_manager = NotificationServiceManager()

# Функция для создания сервиса с сессией
def get_notification_service(session: Optional[Session] = None) -> StockSyncNotificationService:
    """Получает экземпляр сервиса уведомлений."""
    return _notification_manager.get_service(session)

# Глобальный экземпляр без сессии (для обратной совместимости)
stock_sync_notifications = _notification_manager.get_service(None)

# Функции управления фоновой обработкой
def start_notification_queue_processing(interval_seconds: int = 300):
    """Запускает фоновую обработку очереди уведомлений."""
    _notification_manager.start_background_processing(interval_seconds)

def stop_notification_queue_processing():
    """Останавливает фоновую обработку очереди уведомлений."""
    _notification_manager.stop_background_processing()

def get_notification_services_status() -> Dict[str, Any]:
    """Возвращает статус всех сервисов уведомлений."""
    return _notification_manager.get_all_services_status()