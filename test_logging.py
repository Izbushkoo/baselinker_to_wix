#!/usr/bin/env python3
"""
 * @file: test_logging.py
 * @description: Тестовый скрипт для демонстрации новой системы логирования
 * @dependencies: app.utils.logging_config
 * @created: 2025-07-30
"""

import os
import sys

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.utils.logging_config import (
    get_logger, 
    log_business_event, 
    log_error_with_context,
    enable_debug_logging,
    disable_sql_logs
)

def test_basic_logging():
    """Тест базового логирования"""
    print("\n=== ТЕСТ БАЗОВОГО ЛОГИРОВАНИЯ ===")
    
    logger = get_logger("test.basic")
    logger.info("Это информационное сообщение")
    logger.warning("Это предупреждение")
    logger.error("Это ошибка")
    logger.debug("Это отладочное сообщение")

def test_business_events():
    """Тест логирования бизнес-событий"""
    print("\n=== ТЕСТ БИЗНЕС-СОБЫТИЙ ===")
    
    log_business_event(
        "order_created",
        "Новый заказ создан",
        order_id="12345",
        customer="Иван Иванов",
        amount=1500.00
    )
    
    log_business_event(
        "sync_started",
        "Начало синхронизации с Allegro",
        user_id="user123",
        account="allegro_account"
    )

def test_error_logging():
    """Тест логирования ошибок с контекстом"""
    print("\n=== ТЕСТ ЛОГИРОВАНИЯ ОШИБОК ===")
    
    try:
        # Симулируем ошибку
        raise ValueError("Тестовая ошибка для демонстрации")
    except Exception as e:
        log_error_with_context(
            e,
            "Ошибка при обработке заказа",
            order_id="12345",
            user_id="user123"
        )

def test_sql_filtering():
    """Тест фильтрации SQL логов"""
    print("\n=== ТЕСТ ФИЛЬТРАЦИИ SQL ЛОГОВ ===")
    
    # Симулируем SQL логи (они должны быть отфильтрованы в консоли)
    logger = get_logger("sqlalchemy.engine")
    logger.info("SELECT * FROM users WHERE id = 1")
    logger.info("INSERT INTO orders (id, customer) VALUES (1, 'test')")
    
    # Бизнес-логика должна отображаться
    business_logger = get_logger("allegro.sync")
    business_logger.info("Синхронизация заказов завершена")

def test_debug_mode():
    """Тест отладочного режима"""
    print("\n=== ТЕСТ ОТЛАДОЧНОГО РЕЖИМА ===")
    
    print("Включаем отладочный режим...")
    enable_debug_logging()
    
    logger = get_logger("test.debug")
    logger.debug("Отладочное сообщение в DEBUG режиме")
    
    print("Отключаем SQL логи...")
    disable_sql_logs()

def main():
    """Основная функция тестирования"""
    print("🚀 ТЕСТИРОВАНИЕ НОВОЙ СИСТЕМЫ ЛОГИРОВАНИЯ")
    print("=" * 50)
    
    # Тест 1: Базовое логирование
    test_basic_logging()
    
    # Тест 2: Бизнес-события
    test_business_events()
    
    # Тест 3: Ошибки с контекстом
    test_error_logging()
    
    # Тест 4: Фильтрация SQL
    test_sql_filtering()
    
    # Тест 5: Отладочный режим
    test_debug_mode()
    
    print("\n" + "=" * 50)
    print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("\n📋 РЕЗУЛЬТАТЫ:")
    print("- В консоли должны отображаться только бизнес-логи и ошибки")
    print("- SQL запросы должны быть отфильтрованы")
    print("- Цветной вывод для разных уровней логирования")
    print("- Все логи записываются в файлы logs/app.log и logs/errors.log")
    print("\n🔧 УПРАВЛЕНИЕ:")
    print("- LOG_LEVEL=DEBUG - включить отладку")
    print("- ENABLE_SQL_LOGS=true - показать SQL запросы")
    print("- Подробнее см. docs/logging_guide.md")

if __name__ == "__main__":
    main() 