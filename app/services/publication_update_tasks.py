"""
 * @file: publication_update_tasks.py
 * @description: Celery задачи для автоматического обновления данных о публикации офферт Allegro
 * @dependencies: publication_update_service, celery_shared
 * @created: 2024-12-19
"""

import logging
from typing import List, Dict, Any
from app.services.publication_update_service import PublicationUpdateService
from app.celery_shared import celery

logger = logging.getLogger(__name__)


@celery.task(name="update_all_publication_dates")
def update_all_publication_dates_task():
    """Еженедельная задача для обновления данных о публикации всех товаров"""
    logger.info("Запуск еженедельной задачи обновления данных о публикации")
    
    try:
        # Создаем сервис
        service = PublicationUpdateService()
        
        # Запускаем обновление (теперь синхронно)
        result = service.update_all_products_publication_dates()
        
        logger.info(f"Еженедельная задача завершена успешно: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка в еженедельной задаче обновления данных о публикации: {e}")
        # Отправляем уведомление об ошибке
        # TODO: Добавить отправку уведомления в Telegram
        raise


@celery.task(name="update_specific_publication_dates") 
def update_specific_publication_dates_task(skus: List[str]):
    """Задача для обновления данных о публикации конкретных товаров"""
    logger.info(f"Запуск задачи обновления данных о публикации для {len(skus)} товаров")
    
    try:
        # Создаем сервис
        service = PublicationUpdateService()
        
        # Запускаем обновление для указанных SKU
        result = service.update_specific_products_publication_dates(skus)
        
        logger.info(f"Задача обновления конкретных товаров завершена: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка в задаче обновления конкретных товаров: {e}")
        # Отправляем уведомление об ошибке
        # TODO: Добавить отправку уведомления в Telegram
        raise


@celery.task(name="update_publication_dates_batch")
def update_publication_dates_batch_task(skus: List[str], batch_size: int = 100):
    """Задача для обновления данных о публикации батчами"""
    logger.info(f"Запуск задачи обновления данных о публикации батчами для {len(skus)} товаров")
    
    try:
        # Создаем сервис
        service = PublicationUpdateService()
        
        # Устанавливаем размер батча
        service.batch_size = batch_size
        
        # Запускаем обновление
        result = service.update_specific_products_publication_dates(skus)
        
        logger.info(f"Задача обновления батчами завершена: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка в задаче обновления батчами: {e}")
        raise
