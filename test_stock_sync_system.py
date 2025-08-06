#!/usr/bin/env python3
"""
Скрипт для тестирования системы синхронизации складских остатков.
Запуск: python test_stock_sync_system.py
"""

import sys
import os
import uuid
from datetime import datetime
from typing import Dict, Any

# Добавляем путь к приложению
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.database import SessionLocal, engine
    from app.services.stock_synchronization_service import StockSynchronizationService
    from app.services.stock_validation_service import StockValidationService
    from app.services.warehouse.manager import get_manager
    from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
    from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
    from app.core.security import create_access_token
    from app.core.config import settings
    from app.models.stock_synchronization import PendingStockOperation, StockSynchronizationLog
    from sqlmodel import select
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("Убедитесь что вы запускаете скрипт из корневой директории проекта")
    sys.exit(1)


class StockSyncSystemTester:
    """Класс для тестирования системы синхронизации."""
    
    def __init__(self):
        self.session = None
        self.sync_service = None
        self.validation_service = None
        self.test_results = []
    
    def setup(self):
        """Инициализация тестовой среды."""
        print("🔧 Инициализация тестовой среды...")
        
        try:
            # Создаем сессию БД
            self.session = SessionLocal()
            
            # Проверяем подключение к БД
            self.session.exec(text("SELECT 1")).first()
            print("✅ Подключение к базе данных установлено")
            
            # Инициализируем клиенты
            jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
            
            orders_client = OrdersClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            
            tokens_client = AllegroTokenMicroserviceClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            
            inventory_manager = get_manager()
            
            # Создаем сервисы
            self.sync_service = StockSynchronizationService(
                session=self.session,
                orders_client=orders_client,
                tokens_client=tokens_client,
                inventory_manager=inventory_manager
            )
            
            self.validation_service = StockValidationService(
                session=self.session,
                inventory_manager=inventory_manager
            )
            
            print("✅ Сервисы инициализированы")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка инициализации: {e}")
            return False
    
    def test_database_tables(self):
        """Проверка существования таблиц в базе данных."""
        print("\n📊 Тестирование таблиц базы данных...")
        
        try:
            # Проверка таблицы операций
            operations_count = self.session.exec(
                select(PendingStockOperation)
            ).all()
            print(f"✅ Таблица pendingstockoperation: {len(operations_count)} записей")
            
            # Проверка таблицы логов
            logs_count = self.session.exec(
                select(StockSynchronizationLog)
            ).all()
            print(f"✅ Таблица stocksynchronizationlog: {len(logs_count)} записей")
            
            self.test_results.append(("Database Tables", True, "Таблицы существуют и доступны"))
            return True
            
        except Exception as e:
            error_msg = f"Ошибка проверки таблиц: {e}"
            print(f"❌ {error_msg}")
            self.test_results.append(("Database Tables", False, error_msg))
            return False
    
    def test_sync_service_creation(self):
        """Тестирование создания операции синхронизации."""
        print("\n🔄 Тестирование создания операции синхронизации...")
        
        try:
            test_token_id = str(uuid.uuid4())
            test_order_id = f"TEST_ORDER_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            test_sku = "TEST_SKU_001"
            
            result = self.sync_service.sync_stock_deduction(
                token_id=test_token_id,
                order_id=test_order_id,
                sku=test_sku,
                quantity=1,
                warehouse="Ирина"
            )
            
            if result.operation_id:
                print(f"✅ Операция создана: {result.operation_id}")
                print(f"   - Успешность: {result.success}")
                print(f"   - Детали: {result.details}")
                
                self.test_results.append(("Sync Operation Creation", True, f"Операция {result.operation_id}"))
                return True
            else:
                error_msg = f"Операция не создана: {result.error}"
                print(f"❌ {error_msg}")
                self.test_results.append(("Sync Operation Creation", False, error_msg))
                return False
                
        except Exception as e:
            error_msg = f"Ошибка создания операции: {e}"
            print(f"❌ {error_msg}")
            self.test_results.append(("Sync Operation Creation", False, error_msg))
            return False
    
    def test_validation_service(self):
        """Тестирование сервиса валидации."""
        print("\n✅ Тестирование сервиса валидации...")
        
        try:
            # Тестируем валидацию существующего товара (если есть)
            validation_result = self.validation_service.validate_stock_deduction(
                sku="TEST_NONEXISTENT_SKU",
                warehouse="Ирина",
                required_quantity=1
            )
            
            print(f"✅ Валидация выполнена:")
            print(f"   - Валидность: {validation_result.valid}")
            print(f"   - SKU: {validation_result.sku}")
            print(f"   - Доступно: {validation_result.available_quantity}")
            print(f"   - Требуется: {validation_result.required_quantity}")
            if validation_result.error_message:
                print(f"   - Ошибка: {validation_result.error_message}")
            
            self.test_results.append(("Validation Service", True, "Валидация работает"))
            return True
            
        except Exception as e:
            error_msg = f"Ошибка валидации: {e}"
            print(f"❌ {error_msg}")
            self.test_results.append(("Validation Service", False, error_msg))
            return False
    
    def test_processing_operations(self):
        """Тестирование обработки операций из очереди."""
        print("\n⚙️ Тестирование обработки очереди операций...")
        
        try:
            result = self.sync_service.process_pending_operations(limit=10)
            
            print(f"✅ Обработка очереди завершена:")
            print(f"   - Обработано: {result.processed}")
            print(f"   - Успешно: {result.succeeded}")
            print(f"   - Неудачно: {result.failed}")
            print(f"   - Достигли лимита попыток: {result.max_retries_reached}")
            
            self.test_results.append(("Queue Processing", True, f"Обработано {result.processed} операций"))
            return True
            
        except Exception as e:
            error_msg = f"Ошибка обработки очереди: {e}"
            print(f"❌ {error_msg}")
            self.test_results.append(("Queue Processing", False, error_msg))
            return False
    
    def test_system_statistics(self):
        """Тестирование получения статистики системы."""
        print("\n📈 Тестирование системной статистики...")
        
        try:
            stats = self.sync_service.get_sync_statistics()
            
            print(f"✅ Статистика получена:")
            print(f"   - Ожидающих операций: {stats.get('pending_operations', 0)}")
            print(f"   - Провальных операций: {stats.get('failed_operations', 0)}")
            print(f"   - Завершенных сегодня: {stats.get('completed_today', 0)}")
            print(f"   - Застрявших операций: {stats.get('stale_operations', 0)}")
            print(f"   - Статус системы: {stats.get('health_status', 'unknown')}")
            
            self.test_results.append(("System Statistics", True, f"Статус: {stats.get('health_status')}"))
            return True
            
        except Exception as e:
            error_msg = f"Ошибка получения статистики: {e}"
            print(f"❌ {error_msg}")
            self.test_results.append(("System Statistics", False, error_msg))
            return False
    
    def cleanup(self):
        """Очистка ресурсов после тестирования."""
        if self.session:
            self.session.close()
            print("✅ Сессия базы данных закрыта")
    
    def run_all_tests(self):
        """Запуск всех тестов."""
        print("🚀 Запуск тестирования системы синхронизации складских остатков")
        print("=" * 70)
        
        if not self.setup():
            print("❌ Не удалось инициализировать тестовую среду")
            return False
        
        tests = [
            self.test_database_tables,
            self.test_validation_service,
            self.test_sync_service_creation,
            self.test_processing_operations,
            self.test_system_statistics,
        ]
        
        for test in tests:
            try:
                test()
            except Exception as e:
                print(f"❌ Критическая ошибка в тесте {test.__name__}: {e}")
                self.test_results.append((test.__name__, False, str(e)))
        
        self.print_summary()
        self.cleanup()
    
    def print_summary(self):
        """Печать итогов тестирования."""
        print("\n" + "=" * 70)
        print("📋 ИТОГИ ТЕСТИРОВАНИЯ")
        print("=" * 70)
        
        passed = 0
        failed = 0
        
        for test_name, success, details in self.test_results:
            status = "✅ ПРОЙДЕН" if success else "❌ ПРОВАЛЕН"
            print(f"{status:<12} | {test_name:<25} | {details}")
            
            if success:
                passed += 1
            else:
                failed += 1
        
        print("\n" + "-" * 70)
        print(f"Общий результат: {passed} пройдено, {failed} провалено")
        
        if failed == 0:
            print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
            print("Система синхронизации складских остатков готова к работе.")
        else:
            print("⚠️  ОБНАРУЖЕНЫ ПРОБЛЕМЫ!")
            print("Проверьте конфигурацию и исправьте ошибки перед запуском.")
        
        print("=" * 70)


def main():
    """Главная функция."""
    tester = StockSyncSystemTester()
    tester.run_all_tests()


if __name__ == "__main__":
    main()