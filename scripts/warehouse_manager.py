#!/usr/bin/env python3
"""
 * @file: scripts/warehouse_manager.py
 * @description: Универсальный скрипт для управления складами (переименование, добавление, удаление)
 * @dependencies: SQLModel, models.warehouse, models.operations, models.stock_synchronization
 * @created: 2025-01-13
"""

import sys
import os
import argparse
from pathlib import Path
from typing import List, Dict, Any

# Добавляем корневую директорию проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlmodel import Session, select, text
from app.database import SessionLocal
from app.models.warehouse import Stock, Sale, Transfer
from app.models.operations import Operation
from app.models.stock_synchronization import PendingStockOperation
from app.services.warehouse.manager import Warehouses
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WarehouseManager:
    """Менеджер для управления складами в системе."""
    
    def __init__(self):
        self.tables = [
            'stock',
            'sale', 
            'transfer',
            'operation',
            'pending_stock_operations'
        ]
    
    def get_warehouse_stats(self, warehouse_name: str) -> Dict[str, int]:
        """
        Получает статистику по складу во всех таблицах.
        
        Args:
            warehouse_name: Название склада
            
        Returns:
            Dict[str, int]: Статистика по таблицам
        """
        stats = {}
        
        try:
            with SessionLocal() as session:
                # Статистика по таблице stock
                result = session.exec(text("SELECT COUNT(*) FROM stock WHERE warehouse = :warehouse").bindparams(warehouse=warehouse_name))
                stock_count = result.first()
                stats['stock'] = stock_count[0] if stock_count else 0
                
                # Статистика по таблице sale
                result = session.exec(text("SELECT COUNT(*) FROM sale WHERE warehouse = :warehouse").bindparams(warehouse=warehouse_name))
                sale_count = result.first()
                stats['sale'] = sale_count[0] if sale_count else 0
                
                # Статистика по таблице transfer (source + destination)
                result = session.exec(text("""
                    SELECT COUNT(*) FROM transfer 
                    WHERE source = :warehouse OR destination = :warehouse
                """).bindparams(warehouse=warehouse_name))
                transfer_count = result.first()
                stats['transfer'] = transfer_count[0] if transfer_count else 0
                
                # Статистика по таблице operation
                result = session.exec(text("""
                    SELECT COUNT(*) FROM operation 
                    WHERE warehouse_id = :warehouse OR target_warehouse_id = :warehouse
                """).bindparams(warehouse=warehouse_name))
                operation_count = result.first()
                stats['operation'] = operation_count[0] if operation_count else 0
                
                # Статистика по таблице pending_stock_operations
                result = session.exec(text("SELECT COUNT(*) FROM pending_stock_operations WHERE warehouse = :warehouse").bindparams(warehouse=warehouse_name))
                pending_count = result.first()
                stats['pending_stock_operations'] = pending_count[0] if pending_count else 0
                
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            raise
            
        return stats
    
    def rename_warehouse(self, old_name: str, new_name: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Переименовывает склад во всех связанных таблицах.
        
        Args:
            old_name: Старое название склада
            new_name: Новое название склада
            dry_run: Режим предварительного просмотра (без изменений)
            
        Returns:
            Dict[str, Any]: Результат операции
        """
        logger.info(f"Начинаю переименование склада '{old_name}' в '{new_name}'")
        
        # Получаем статистику по старому складу
        old_stats = self.get_warehouse_stats(old_name)
        total_records = sum(old_stats.values())
        
        if total_records == 0:
            logger.warning(f"Склад '{old_name}' не найден в системе")
            return {
                'success': False,
                'message': f'Склад "{old_name}" не найден в системе',
                'old_stats': old_stats,
                'new_stats': {},
                'updated_records': 0
            }
        
        logger.info(f"Найдено записей для обновления: {total_records}")
        logger.info(f"Детальная статистика: {old_stats}")
        
        if dry_run:
            logger.info("Режим предварительного просмотра - изменения не будут применены")
            return {
                'success': True,
                'message': f'Предварительный просмотр: будет обновлено {total_records} записей',
                'old_stats': old_stats,
                'new_stats': {},
                'updated_records': total_records,
                'dry_run': True
            }
        
        total_updated = 0
        update_results = {}
        
        try:
            with SessionLocal() as session:
                # Обновляем каждую таблицу
                for table in self.tables:
                    updated_count = self._update_warehouse_in_table(
                        session, table, old_name, new_name
                    )
                    update_results[table] = updated_count
                    total_updated += updated_count
                
                logger.info(f"Всего обновлено записей: {total_updated}")
                logger.info(f"Детальные результаты: {update_results}")
                
            # Обновляем перечисление в коде
            self._update_warehouse_enum(old_name, new_name)
            
            # Получаем статистику по новому складу
            new_stats = self.get_warehouse_stats(new_name)
            
            logger.info(f"Склад '{old_name}' успешно переименован в '{new_name}'")
            
            return {
                'success': True,
                'message': f'Склад "{old_name}" успешно переименован в "{new_name}"',
                'old_stats': old_stats,
                'new_stats': new_stats,
                'updated_records': total_updated,
                'update_results': update_results
            }
            
        except Exception as e:
            logger.error(f"Ошибка при переименовании склада: {e}")
            return {
                'success': False,
                'message': f'Ошибка при переименовании: {str(e)}',
                'old_stats': old_stats,
                'new_stats': {},
                'updated_records': 0,
                'error': str(e)
            }
    
    def _update_warehouse_in_table(self, session: Session, table_name: str, old_name: str, new_name: str) -> int:
        """
        Обновляет название склада в указанной таблице.
        
        Args:
            session: Сессия базы данных
            table_name: Название таблицы
            old_name: Старое название склада
            new_name: Новое название склада
            
        Returns:
            int: Количество обновленных записей
        """
        try:
            if table_name == 'stock':
                result = session.exec(
                    text("UPDATE stock SET warehouse = :new_name WHERE warehouse = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                updated_count = result.rowcount
            elif table_name == 'sale':
                result = session.exec(
                    text("UPDATE sale SET warehouse = :new_name WHERE warehouse = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                updated_count = result.rowcount
            elif table_name == 'transfer':
                # Обновляем оба поля: source и destination
                result1 = session.exec(
                    text("UPDATE transfer SET source = :new_name WHERE source = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                result2 = session.exec(
                    text("UPDATE transfer SET destination = :new_name WHERE destination = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                updated_count = result1.rowcount + result2.rowcount
            elif table_name == 'operation':
                # Обновляем оба поля: warehouse_id и target_warehouse_id
                result1 = session.exec(
                    text("UPDATE operation SET warehouse_id = :new_name WHERE warehouse_id = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                result2 = session.exec(
                    text("UPDATE operation SET target_warehouse_id = :new_name WHERE target_warehouse_id = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                updated_count = result1.rowcount + result2.rowcount
            elif table_name == 'pending_stock_operations':
                result = session.exec(
                    text("UPDATE pending_stock_operations SET warehouse = :new_name WHERE warehouse = :old_name").bindparams(old_name=old_name, new_name=new_name)
                )
                updated_count = result.rowcount
            else:
                logger.warning(f"Неизвестная таблица: {table_name}")
                return 0
                
            session.commit()
            logger.info(f"Таблица {table_name}: обновлено {updated_count} записей")
            return updated_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении таблицы {table_name}: {e}")
            raise
    
    def _update_warehouse_enum(self, old_name: str, new_name: str) -> None:
        """
        Обновляет перечисление Warehouses в manager.py.
        
        Args:
            old_name: Старое название склада
            new_name: Новое название склада
        """
        try:
            manager_file = project_root / "app" / "services" / "warehouse" / "manager.py"
            
            with open(manager_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Заменяем старое название на новое
            updated_content = content.replace(f"'{old_name}'", f"'{new_name}'")
            
            with open(manager_file, 'w', encoding='utf-8') as f:
                f.write(updated_content)
                
            logger.info(f"Обновлен файл {manager_file}")
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении файла manager.py: {e}")
            raise
    
    def list_warehouses(self) -> List[str]:
        """
        Получает список всех складов в системе.
        
        Returns:
            List[str]: Список названий складов
        """
        warehouses = set()
        
        try:
            with SessionLocal() as session:
                # Используем прямой SQL запрос для получения всех уникальных складов
                query = text("""
                    SELECT DISTINCT warehouse_name FROM (
                        SELECT warehouse as warehouse_name FROM stock WHERE warehouse IS NOT NULL
                        UNION
                        SELECT warehouse as warehouse_name FROM sale WHERE warehouse IS NOT NULL
                        UNION
                        SELECT source as warehouse_name FROM transfer WHERE source IS NOT NULL
                        UNION
                        SELECT destination as warehouse_name FROM transfer WHERE destination IS NOT NULL
                        UNION
                        SELECT warehouse_id as warehouse_name FROM operation WHERE warehouse_id IS NOT NULL
                        UNION
                        SELECT target_warehouse_id as warehouse_name FROM operation WHERE target_warehouse_id IS NOT NULL
                        UNION
                        SELECT warehouse as warehouse_name FROM pending_stock_operations WHERE warehouse IS NOT NULL
                    ) as all_warehouses
                    ORDER BY warehouse_name
                """)
                
                result = session.exec(query).scalars()
                for warehouse_name in result:
                    if warehouse_name:
                        warehouses.add(str(warehouse_name))
                
        except Exception as e:
            logger.error(f"Ошибка при получении списка складов: {e}")
            raise
            
        return sorted(list(warehouses))
    
    def get_warehouse_info(self, warehouse_name: str) -> Dict[str, Any]:
        """
        Получает подробную информацию о складе.
        
        Args:
            warehouse_name: Название склада
            
        Returns:
            Dict[str, Any]: Информация о складе
        """
        stats = self.get_warehouse_stats(warehouse_name)
        
        info = {
            'name': warehouse_name,
            'stats': stats,
            'total_records': sum(stats.values()),
            'exists': sum(stats.values()) > 0
        }
        
        return info

def main():
    """Главная функция скрипта."""
    parser = argparse.ArgumentParser(
        description='Универсальный менеджер складов для BaseLinker to Wix',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:

  # Переименовать склад "Основной" в "Новый"
  python scripts/warehouse_manager.py rename "Основной" "Новый"
  
  # Предварительный просмотр изменений
  python scripts/warehouse_manager.py rename "Основной" "Новый" --dry-run
  
  # Список всех складов
  python scripts/warehouse_manager.py list
  
  # Информация о конкретном складе
  python scripts/warehouse_manager.py info "Основной"
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')
    
    # Команда rename
    rename_parser = subparsers.add_parser('rename', help='Переименовать склад')
    rename_parser.add_argument('old_name', help='Старое название склада')
    rename_parser.add_argument('new_name', help='Новое название склада')
    rename_parser.add_argument('--dry-run', action='store_true', help='Предварительный просмотр без изменений')
    
    # Команда list
    subparsers.add_parser('list', help='Список всех складов')
    
    # Команда info
    info_parser = subparsers.add_parser('info', help='Информация о складе')
    info_parser.add_argument('warehouse_name', help='Название склада')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = WarehouseManager()
    
    try:
        if args.command == 'rename':
            if not args.old_name or not args.new_name:
                print("Ошибка: необходимо указать старое и новое название склада")
                return
            
            print(f"ВНИМАНИЕ: Вы собираетесь переименовать склад '{args.old_name}' в '{args.new_name}'")
            print("Это действие затронет все связанные таблицы и не может быть отменено автоматически.")
            
            if not args.dry_run:
                confirm = input("Продолжить? (y/N): ")
                if confirm.lower() != 'y':
                    print("Операция отменена.")
                    return
            
            result = manager.rename_warehouse(args.old_name, args.new_name, args.dry_run)
            
            if result['success']:
                print(f"✅ {result['message']}")
                if 'update_results' in result:
                    print(f"📊 Обновлено записей: {result['updated_records']}")
                    for table, count in result['update_results'].items():
                        print(f"   - {table}: {count}")
            else:
                print(f"❌ {result['message']}")
                if 'error' in result:
                    print(f"Ошибка: {result['error']}")
                sys.exit(1)
                
        elif args.command == 'list':
            try:
                warehouses = manager.list_warehouses()
                if warehouses:
                    print("📋 Список складов в системе:")
                    for warehouse in warehouses:
                        print(f"   - {warehouse}")
                else:
                    print("📋 Склады не найдены")
            except Exception as e:
                print(f"❌ Ошибка при получении списка складов: {e}")
                logger.error(f"Ошибка при получении списка складов: {e}")
                sys.exit(1)
                
        elif args.command == 'info':
            info = manager.get_warehouse_info(args.warehouse_name)
            if info['exists']:
                print(f"📊 Информация о складе '{args.warehouse_name}':")
                print(f"   Всего записей: {info['total_records']}")
                for table, count in info['stats'].items():
                    print(f"   - {table}: {count}")
            else:
                print(f"❌ Склад '{args.warehouse_name}' не найден в системе")
                
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        print(f"❌ Произошла ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
