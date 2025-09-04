#!/usr/bin/env python3
"""
Скрипт для исправления Unknown значений account_name в pending_stock_operations
"""

import logging
import sys
from uuid import UUID
from sqlmodel import Session, select
from app.database import get_db
from app.models.stock_synchronization import PendingStockOperation
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fix_null_account_names(dry_run: bool = True):
    """
    Исправляет Unknown значения account_name в базе данных
    
    Args:
        dry_run: Если True, только показывает что будет изменено без реального обновления
    """
    
    # Создаем клиент для работы с токенами
    jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
    tokens_client = AllegroTokenMicroserviceClient(
        jwt_token=jwt_token,
        base_url=settings.MICRO_SERVICE_URL
    )
    
    with Session(next(get_db())) as session:
        # Находим все операции с Unknown account_name
        statement = select(PendingStockOperation).where(
            PendingStockOperation.account_name.like('Unknown(%')
        )
        operations = session.exec(statement).all()
        
        logger.info(f"Найдено {len(operations)} операций с Unknown account_name")
        
        if not operations:
            logger.info("Нет операций для обновления")
            return
        
        updated_count = 0
        failed_count = 0
        
        for operation in operations:
            try:
                logger.info(f"Обрабатываем операцию {operation.id} с token_id {operation.token_id}")
                
                # Получаем имя аккаунта из микросервиса
                token_response = tokens_client.get_token(UUID(operation.token_id))
                
                if token_response and hasattr(token_response, 'account_name') and token_response.account_name:
                    account_name = token_response.account_name
                    logger.info(f"Получено имя аккаунта: '{account_name}'")
                else:
                    account_name = f"Unknown({operation.token_id})"
                    logger.warning(f"Не удалось получить имя аккаунта, используем fallback: '{account_name}'")
                
                if dry_run:
                    logger.info(f"[DRY RUN] Операция {operation.id} будет обновлена: account_name = '{account_name}'")
                else:
                    # Обновляем операцию
                    operation.account_name = account_name
                    session.add(operation)
                    logger.info(f"Операция {operation.id} обновлена: account_name = '{account_name}'")
                
                updated_count += 1
                
            except Exception as e:
                failed_count += 1
                logger.error(f"Ошибка обработки операции {operation.id}: {e}")
                
                if not dry_run:
                    # Устанавливаем fallback значение
                    operation.account_name = f"Unknown({operation.token_id})"
                    session.add(operation)
                    logger.info(f"Установлено fallback значение для операции {operation.id}")
        
        if not dry_run:
            session.commit()
            logger.info("Изменения сохранены в базе данных")
        
        logger.info(f"Обработка завершена: {updated_count} успешно, {failed_count} ошибок")


def main():
    """Главная функция скрипта"""
    
    # Проверяем аргументы командной строки
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == "--apply":
        dry_run = False
        logger.info("Режим применения изменений (--apply)")
    else:
        logger.info("Режим предварительного просмотра (добавьте --apply для применения изменений)")
    
    try:
        fix_null_account_names(dry_run=dry_run)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()