"""
 * @file: logging_config.py
 * @description: Конфигурация логирования для всего проекта с фильтрацией технических логов
 * @dependencies: logging, os, RotatingFileHandler
 * @created: 2024-12-20
 * @updated: 2025-07-30
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

# Создаём директорию для логов, если её нет
LOG_PATH = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_PATH, exist_ok=True)

# Переменные окружения для управления логированием
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENABLE_SQL_LOGS = os.getenv("ENABLE_SQL_LOGS", "false").lower() == "true"
ENABLE_DEBUG_LOGS = os.getenv("ENABLE_DEBUG_LOGS", "false").lower() == "true"

class BusinessLogicFilter(logging.Filter):
    """
    Фильтр для отображения только бизнес-логики, исключая технические детали
    """
    def filter(self, record):
        # Исключаем SQL запросы и технические детали
        if record.name.startswith('sqlalchemy.engine'):
            return False
        if record.name.startswith('sqlalchemy.pool'):
            return False
        if record.name.startswith('sqlalchemy.dialects'):
            return False
        if record.name.startswith('sqlalchemy.orm'):
            return False
        if record.name.startswith('urllib3'):
            return False
        if record.name.startswith('httpx'):
            return False
        if record.name.startswith('asyncio'):
            return False
        if record.name.startswith('uvicorn'):
            return False
        if record.name.startswith('gunicorn'):
            return False
        if record.name.startswith('celery.worker'):
            return False
        if record.name.startswith('celery.beat'):
            return False
        if record.name.startswith('celery.app'):
            return False
        if record.name.startswith('kombu'):
            return False
        if record.name.startswith('redis'):
            return False
        if record.name.startswith('aioredis'):
            return False
        if record.name.startswith('asyncpg'):
            return False
        if record.name.startswith('psycopg'):
            return False
        
        # Исключаем сообщения с SQL запросами
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            if 'SELECT' in record.msg and 'FROM' in record.msg:
                return False
            if 'INSERT' in record.msg and 'INTO' in record.msg:
                return False
            if 'UPDATE' in record.msg and 'SET' in record.msg:
                return False
            if 'DELETE' in record.msg and 'FROM' in record.msg:
                return False
            if 'BEGIN' in record.msg or 'COMMIT' in record.msg or 'ROLLBACK' in record.msg:
                return False
        
        return True

class ColoredFormatter(logging.Formatter):
    """
    Форматтер с цветным выводом для консоли
    """
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        # Добавляем цвет только для консоли
        if hasattr(record, 'use_color') and record.use_color:
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset = self.COLORS['RESET']
            record.levelname = f"{color}{record.levelname}{reset}"
            record.name = f"{color}{record.name}{reset}"
        
        return super().format(record)

def setup_project_logging(log_level: str = None, enable_sql_logs: bool = None):
    """
    Настраивает логирование для всего проекта.
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        enable_sql_logs: Включить логи SQL запросов (для отладки)
    """
    # Используем значения по умолчанию, если не переданы
    if log_level is None:
        log_level = LOG_LEVEL
    if enable_sql_logs is None:
        enable_sql_logs = ENABLE_SQL_LOGS
    
    # Определяем уровень логирования
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Очищаем все существующие хендлеры
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Форматтеры
    console_formatter = ColoredFormatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Хендлер для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(numeric_level)
    
    # Добавляем фильтр для консоли
    if not enable_sql_logs:
        console_handler.addFilter(BusinessLogicFilter())
    
    # Хендлер для записи в файл с ротацией
    file_handler = RotatingFileHandler(
        os.path.join(LOG_PATH, "app.log"),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)  # В файл записываем все
    
    # Хендлер для ошибок
    error_handler = RotatingFileHandler(
        os.path.join(LOG_PATH, "errors.log"),
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setFormatter(file_formatter)
    error_handler.setLevel(logging.ERROR)
    
    # Настраиваем корневой логгер
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    
    # Настройка технических логгеров
    technical_loggers = [
        "sqlalchemy.engine",
        "sqlalchemy.pool", 
        "sqlalchemy.dialects",
        "sqlalchemy.orm",
        "urllib3",
        "httpx",
        "asyncio",
        "uvicorn",
        "gunicorn",
        "celery.worker",
        "celery.beat", 
        "celery.app",
        "kombu",
        "redis",
        "aioredis",
        "asyncpg",
        "psycopg"
    ]
    
    for logger_name in technical_loggers:
        module_logger = logging.getLogger(logger_name)
        if enable_sql_logs:
            module_logger.setLevel(logging.WARNING)
        else:
            module_logger.setLevel(logging.ERROR)
        module_logger.propagate = False
    
    # Настраиваем логгер для нашего приложения
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False
    
    # Добавляем хендлеры для app логгера
    app_logger.addHandler(console_handler)
    app_logger.addHandler(file_handler)
    app_logger.addHandler(error_handler)
    
    # Настраиваем специальные логгеры для бизнес-логики
    business_loggers = [
        "allegro.sync",
        "allegro.api", 
        "wix.api",
        "baselinker",
        "warehouse",
        "operations",
        "prices",
        "stock"
    ]
    
    for logger_name in business_loggers:
        business_logger = logging.getLogger(logger_name)
        business_logger.setLevel(logging.DEBUG)
        business_logger.propagate = False
        business_logger.addHandler(console_handler)
        business_logger.addHandler(file_handler)
        business_logger.addHandler(error_handler)
    
    return app_logger

def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер с правильным именем для бизнес-логики
    
    Args:
        name: Имя логгера
        
    Returns:
        logging.Logger: Настроенный логгер
    """
    return logging.getLogger(name)

def enable_debug_logging():
    """
    Включает отладочное логирование для диагностики проблем
    """
    setup_project_logging(log_level="DEBUG", enable_sql_logs=True)
    logger = get_logger("debug")
    logger.info("Включено отладочное логирование с SQL запросами")

def disable_sql_logs():
    """
    Отключает логи SQL запросов
    """
    setup_project_logging(log_level=LOG_LEVEL, enable_sql_logs=False)
    logger = get_logger("config")
    logger.info("Отключены логи SQL запросов")

def log_business_event(event_type: str, message: str, **kwargs):
    """
    Логирует бизнес-событие в удобном формате
    
    Args:
        event_type: Тип события (order_created, sync_started, etc.)
        message: Сообщение о событии
        **kwargs: Дополнительные параметры для логирования
    """
    logger = get_logger("business")
    extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
    if extra_info:
        logger.info(f"[{event_type.upper()}] {message} | {extra_info}")
    else:
        logger.info(f"[{event_type.upper()}] {message}")

def log_error_with_context(error: Exception, context: str = "", **kwargs):
    """
    Логирует ошибку с контекстом
    
    Args:
        error: Исключение
        context: Контекст ошибки
        **kwargs: Дополнительные параметры
    """
    logger = get_logger("errors")
    extra_info = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
    if context:
        logger.error(f"[ERROR] {context}: {str(error)} | {extra_info}")
    else:
        logger.error(f"[ERROR] {str(error)} | {extra_info}")

# Создаем глобальный логгер
logger = setup_project_logging() 