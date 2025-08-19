#!/usr/bin/env python3
"""
 * @file: scripts/rename_warehouse.py
 * @description: Скрипт для переименования складов во всех связанных таблицах
 * @dependencies: SQLModel, models.warehouse, models.operations, models.stock_synchronization
 * @created: 2025-01-13
"""

import sys
import os
from pathlib import Path

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

def rename_warehouse_in_table(session: Session, table_name: str, old_name: str, new_name: str) -> int:
    """
    Переименовывает склад в указанной таблице.
    
    Args:
        session: Сессия базы данных
        table_name: Название таблицы
        old_name: Старое название склада
        new_name: Новое название склада
        
    Returns:
        int: Количество обновленных записей
    """
    try:
        # Используем raw SQL для безопасного обновления
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
        elif table_name == 'pending_stock_operation':
            result = session.exec(
                text("UPDATE pending_stock_operation SET warehouse = :new_name WHERE warehouse = :old_name").bindparams(old_name=old_name, new_name=new_name)
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

def update_warehouse_enum(old_name: str, new_name: str) -> None:
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

def rename_warehouse(old_name: str, new_name: str) -> None:
    """
    Основная функция для переименования склада.
    
    Args:
        old_name: Старое название склада
        new_name: Новое название склада
    """
    logger.info(f"Начинаю переименование склада '{old_name}' в '{new_name}'")
    
    # Список таблиц для обновления
    tables = [
        'stock',
        'sale', 
        'transfer',
        'operation',
        'pending_stock_operation'
    ]
    
    total_updated = 0
    
    try:
        with SessionLocal() as session:
            # Обновляем каждую таблицу
            for table in tables:
                updated_count = rename_warehouse_in_table(session, table, old_name, new_name)
                total_updated += updated_count
            
            logger.info(f"Всего обновлено записей: {total_updated}")
            
        # Обновляем перечисление в коде
        update_warehouse_enum(old_name, new_name)
        
        logger.info(f"Склад '{old_name}' успешно переименован в '{new_name}'")
        
    except Exception as e:
        logger.error(f"Ошибка при переименовании склада: {e}")
        sys.exit(1)

def main():
    """Главная функция скрипта."""
    if len(sys.argv) != 3:
        print("Использование: python scripts/rename_warehouse.py <старое_название> <новое_название>")
        print("Пример: python scripts/rename_warehouse.py 'Основной' 'Новый'")
        sys.exit(1)
    
    old_name = sys.argv[1]
    new_name = sys.argv[2]
    
    print(f"ВНИМАНИЕ: Вы собираетесь переименовать склад '{old_name}' в '{new_name}'")
    print("Это действие затронет все связанные таблицы и не может быть отменено автоматически.")
    
    confirm = input("Продолжить? (y/N): ")
    if confirm.lower() != 'y':
        print("Операция отменена.")
        sys.exit(0)
    
    rename_warehouse(old_name, new_name)
    print("Переименование завершено успешно!")

if __name__ == "__main__":
    main()
