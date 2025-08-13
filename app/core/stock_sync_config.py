try:
    from pydantic_settings import BaseSettings
except ImportError:
    # Fallback для старых версий pydantic
    from pydantic import BaseSettings
from typing import Dict, Any


class StockSyncConfig(BaseSettings):
    """
    Конфигурация системы синхронизации складских операций.
    
    Настройки можно переопределить через переменные окружения с префиксом STOCK_SYNC_
    """
    TELEGRAM_MAIN_CHAT_ID: int = None
    TELEGRAM_CRITICAL_CHAT_ID: int = None
    TELEGRAM_TECHNICAL_CHAT_ID: int = None

    # Настройки retry механизма
    retry_max_attempts: int = 5
    retry_initial_delay: int = 60  # секунды
    retry_max_delay: int = 3600   # секунды (1 час)
    retry_exponential_base: float = 2.0
    retry_jitter: bool = True
    
    # Настройки reconciliation (сверки состояний)
    reconciliation_interval_minutes: int = 30
    reconciliation_batch_size: int = 100
    reconciliation_auto_fix_threshold_hours: int = 24
    reconciliation_enabled: bool = True
    
    # Настройки мониторинга и алертов
    monitoring_alert_on_failed_retries: bool = True
    monitoring_max_pending_operations: int = 1000
    monitoring_stale_operation_hours: int = 6
    monitoring_health_check_interval_minutes: int = 30
    
    # Настройки уведомлений
    alerts_enabled: bool = True
    alerts_critical_shortage: bool = True
    alerts_sync_failures: bool = True
    alerts_system_health: bool = True
    alerts_daily_reports: bool = True
    
    # Настройки обработки операций
    processing_batch_size: int = 50
    processing_timeout_seconds: int = 30
    processing_concurrent_workers: int = 3
    
    # Настройки очистки данных
    cleanup_completed_operations_days: int = 30
    cleanup_failed_operations_days: int = 90
    cleanup_logs_days: int = 60
    
    validation_low_stock_threshold: int = 5

    model_config = {
        "env_prefix": "STOCK_SYNC_",
        "env_file": ".env.docker",
        "extra": "ignore"  # Игнорировать дополнительные поля из .env
    }


# Глобальный экземпляр конфигурации
stock_sync_config = StockSyncConfig()


# Константы для типов алертов
class AlertTypes:
    """Типы алертов системы синхронизации."""
    CRITICAL = "critical"
    WARNING = "warning" 
    INFO = "info"
    NORMAL = "normal"


class AlertPriorities:
    """Приоритеты алертов для определения срочности."""
    HIGH = "high"       # Требует немедленного внимания
    MEDIUM = "medium"   # Требует внимания в течение часа
    LOW = "low"         # Информационный алерт


# Шаблоны сообщений для уведомлений
ALERT_TEMPLATES = {
    "stock_shortage": {
        "title": "❌ НЕДОСТАТОК ТОВАРА НА СКЛАДЕ",
        "priority": AlertPriorities.HIGH,
        "template": """
👤 Аккаунт: **{account_name}**
📦 SKU: {sku}
📋 Заказ: {order_id}
🏪 Склад: {warehouse}
📊 Требуется: {required} шт.
📊 Доступно: {available} шт.
⚠️ Недостает: {shortage} шт.
🕐 Время: {timestamp}

💡 Требуется пополнение склада!
        """
    },
    "sync_failure": {
        "title": "🔄 СБОЙ СИНХРОНИЗАЦИИ",
        "priority": AlertPriorities.MEDIUM,
        "template": """
👤 Аккаунт: **{account_name}**
🏷️ SKU: {sku}
📋 Заказ: {order_id}
🆔 Операция: {operation_id}
🔁 Попытка: {retry_count}
❌ Ошибка: {error_message}
🕐 {timestamp}

🔧 Действия:
• Проверить микросервис Allegro
• Проверить сетевое соединение
• При необходимости - ручная синхронизация
        """
    },
    "system_health": {
        "title": "📊 СТАТУС СИНХРОНИЗАЦИИ",
        "priority": AlertPriorities.LOW,
        "template": """
⏳ В очереди: **{pending_operations}** операций
❌ Неудачных: **{failed_operations}** операций
🐌 Застрявших: **{stale_operations}** операций
🕐 {timestamp}
        """
    },
    "reconciliation_discrepancy": {
        "title": "⚖️ РАСХОЖДЕНИЯ В ДАННЫХ",
        "priority": AlertPriorities.HIGH,
        "template": """
📊 Проверено заказов: {total_orders_checked}
❌ Найдено расхождений: **{discrepancies_count}**
🏢 Аккаунтов затронуто: **{accounts_affected}**
🕐 {timestamp}

🔧 **Требуется ручная проверка!**
        """
    }
}

# Настройки для различных сред выполнения
ENVIRONMENT_CONFIGS = {
    "development": {
        "retry_max_attempts": 3,
        "retry_initial_delay": 30,
        "monitoring_max_pending_operations": 100,
        "alerts_enabled": True,
        "reconciliation_interval_minutes": 60
    },
    "staging": {
        "retry_max_attempts": 4,
        "retry_initial_delay": 45,
        "monitoring_max_pending_operations": 500,
        "alerts_enabled": True,
        "reconciliation_interval_minutes": 45
    },
    "production": {
        "retry_max_attempts": 5,
        "retry_initial_delay": 60,
        "monitoring_max_pending_operations": 1000,
        "alerts_enabled": True,
        "reconciliation_interval_minutes": 30
    }
}


def get_environment_config(env: str = "production") -> Dict[str, Any]:
    """
    Получает конфигурацию для указанной среды выполнения.
    
    Args:
        env: Имя среды (development, staging, production)
        
    Returns:
        Dict с настройками для указанной среды
    """
    return ENVIRONMENT_CONFIGS.get(env, ENVIRONMENT_CONFIGS["production"])


def update_config_for_environment(env: str = "production") -> None:
    """
    Обновляет глобальную конфигурацию для указанной среды.
    
    Args:
        env: Имя среды выполнения
    """
    env_config = get_environment_config(env)
    
    for key, value in env_config.items():
        if hasattr(stock_sync_config, key):
            setattr(stock_sync_config, key, value)