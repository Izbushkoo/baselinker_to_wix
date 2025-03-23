import requests
import csv
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker

from celery import Celery, chord, group, chain

from app.services import baselinker as BL
from app.services.process_funcs import transform_product
from app.schemas.wix_models import WixImportFileModel
from app.schemas.wix_models import generate_handle_id
from loggers import ToLog
from app.utils.logging_config import setup_logging

import logging
import os

from app.services.allegro.order_service import SyncAllegroOrderService
from app.database import engine

import time
from app.models.allegro_token import AllegroToken
from app.services.allegro.tokens import check_token_sync
from app.services.allegro.data_access import get_token_by_id_sync
from app.utils.date_utils import parse_date

# Настраиваем логирование
logger = setup_logging('celery_worker', 'celery_worker.log')

# Настройки брокера (Redis)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

celery = Celery(
    "baselinker_to_wix",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL
)

celery.conf.result_backend = "redis://redis:6379/1"

# Настройка Celery
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_hijack_root_logger=False,  # Отключаем перехват root логгера
    worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'
)

# Настройка периодических задач
celery.conf.beat_schedule = {}

def chunks(lst, n):
    """Возвращает генератор чанков размера n из списка lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


@celery.task(name="tasks.example_task")
def example_task(x, y):
    return {"result": x + y}


# Задача для обработки одного товара
@celery.task(bind=True, acks_late=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3})
def process_product_chunk(self, baselinker_api_key, inventory_id, products_chunk):
    # Здесь вызываем API Baselinker для получения данных по товару
    api_client = BL.BaseLinkerAPI(api_token=baselinker_api_key)
    result = api_client.send_request_sync(BL.BaseLinkerMethod.get_inventory_product_data,
                                          BL.GetInventoryProductsData(inventory_id=inventory_id,
                                                                      products=products_chunk))
    logging.info(f"{result}")

    if result["status"] == "SUCCESS":
    # Обработка данных (ваша логика)
        products = result.get("products", {})
        processed_data = [transform_product(products.get(product_id)).model_dump() for product_id in products_chunk]
        return processed_data
    else:
        raise Exception(f"API вернул неуспешный статус: {result['status']}")


@celery.task
def write_csv(results, chat_id):
    # Flatten: объединяем списки из всех чанков в один список
    all_products = [
        WixImportFileModel(handleId=generate_handle_id(), **item).model_dump() for chunk in results for item in chunk]
    ToLog.write_basic(f"{all_products}")
    if all_products:
        with open(f'/app/logs/{chat_id}.csv', "w", newline="", encoding="utf-8") as csvfile:
            # Инициализируем DictWriter, передавая ключи словаря как заголовки столбцов.
            writer = csv.DictWriter(csvfile, fieldnames=all_products[0].keys(), delimiter=",")

            # Записываем строку с заголовками
            writer.writeheader()

            # Записываем строку с данными

            for row in all_products:
                writer.writerow(row)
        return 'CSV успешно записан'
    else:
        return "Каталог пуст"


@celery.task
def send_telegram_document(_unused, chat_id: int):
    """Отправляет файл в Telegram через HTTP API."""
    url = f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendDocument"

    with open(f'/app/logs/{chat_id}.csv', "rb") as f:
        files = {"document": f}
        data = {"chat_id": chat_id, "caption": "Ваш CSV файл с данными"}
        response = requests.post(url, data=data, files=files)
    return response.json()


def launch_processing(decrypted_api_key, inventory_id, all_product_ids, telegram_chat_id, chunk_size=100):
    # Разбиваем товары на чанки
    tasks_group = group(
        process_product_chunk.s(decrypted_api_key, inventory_id, chunk)
        for chunk in chunks(all_product_ids, chunk_size)
    )

    # Создаем цепочку: сначала объединение результатов и запись CSV, затем отправка файла в Telegram.
    final_chain = chain(
        write_csv.s(telegram_chat_id),  # запишет CSV и вернет, например, "output.csv"
        send_telegram_document.s(telegram_chat_id)
    )

    # Chord: обработка всех чанков -> выполнение финальной цепочки
    result = chord(tasks_group)(final_chain)
    return result  # result.id можно вернуть для отслеживания


class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window  # в секундах
        self.requests = []
        
    def wait_if_needed(self):
        now = time.time()
        
        # Удаляем старые запросы
        self.requests = [req_time for req_time in self.requests 
                        if now - req_time < self.time_window]
        
        # Если достигли лимита, ждем
        if len(self.requests) >= self.max_requests:
            sleep_time = self.requests[0] + self.time_window - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            self.requests = self.requests[1:]
        
        # Добавляем текущий запрос
        self.requests.append(now)

# Создаем глобальный rate limiter (6000 запросов в минуту)
allegro_rate_limiter = RateLimiter(max_requests=6000, time_window=60)

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

def get_allegro_token(session: Session, token_id: str) -> AllegroToken:
    """
    Получает и проверяет токен Allegro из базы данных.
    
    Args:
        session: Сессия SQLModel
        token_id: ID токена
        
    Returns:
        AllegroToken: Проверенный и обновленный токен
        
    Raises:
        ValueError: Если токен не найден или не удалось его проверить/обновить
    """
    # Получаем токен из базы
    token = get_token_by_id_sync(session, token_id)
    if not token:
        raise ValueError(f"Токен Allegro с ID {token_id} не найден в базе данных")
    
    # Проверяем и при необходимости обновляем токен
    result = check_token_sync(token_id)
    if not result:
        raise ValueError(f"Не удалось проверить/обновить токен с ID {token_id}")
        
    # Обновляем токен в сессии если он был обновлен
    if result.get('access_token') != token.access_token:
        token.access_token = result['access_token']
        token.refresh_token = result['refresh_token']
        session.add(token)
        session.commit()
        session.refresh(token)
        
    return token

@celery.task(name='tasks.sync_allegro_orders')
def sync_allegro_orders(token_id: str, from_date: str = None) -> Dict[str, Any]:
    """
    Синхронизирует заказы для указанного токена.
    
    Args:
        token_id: ID токена
        from_date: Дата в формате DD-MM-YYYY (например, "20-03-2025"), с которой начать синхронизацию.
                  Если указана, синхронизация начнется с 00:00:00 указанного дня.
                  Если не указана, будет использовано время последней синхронизации или 30 дней назад.
    """
    try:
        # Парсим дату только если она передана как строка
        parsed_date = parse_date(from_date) if isinstance(from_date, str) else from_date
        
        # Получаем время последней синхронизации
        last_sync_time = celery.backend.get(f"last_sync_time_{token_id}")
        if parsed_date:
            last_sync_time = parsed_date.isoformat()
            logger.info(f"Синхронизация начнется с {parsed_date} (00:00:00)")
        elif last_sync_time:
            # Декодируем байты в строку и парсим в datetime
            last_sync_time = datetime.fromisoformat(last_sync_time.decode('utf-8'))
            logger.info(f"Синхронизация начнется с последней синхронизации: {last_sync_time}")
        else:
            last_sync_time = datetime.now() - timedelta(days=30)
            logger.info(f"Синхронизация начнется с 30 дней назад: {last_sync_time}")
            
        logger.info("Начинаем полную синхронизацию заказов Allegro")
        
        session = SessionLocal()
        try:
            service = SyncAllegroOrderService(session)
            
            # Получаем и проверяем токен из базы данных
            token = get_allegro_token(session, token_id)
            
            offset = 0
            limit = 100
            total_synced = 0
            
            # Получаем все существующие заказы из базы одним запросом
            existing_orders = {}
            orders_info = service.repository.get_all_orders_basic_info()
            if orders_info:
                existing_orders = {
                    order["id"]: order["updateTime"] 
                    for order in orders_info
                }
                logging.info(f"Загружено {len(existing_orders)} существующих заказов")
            else:
                logging.info("Нет существующих заказов, будет выполнена полная синхронизация")
            
            while True:
                # Проверяем rate limit перед запросом
                allegro_rate_limiter.wait_if_needed()
                
                # Получаем страницу заказов
                orders_data = service.api_service.get_orders(
                    token=token.access_token,
                    status="READY_FOR_PROCESSING",
                    offset=offset,
                    limit=limit,
                    updated_at_gte=last_sync_time if last_sync_time else None,
                    sort="-lineItems.boughtAt"  # Сначала новые заказы
                )
                
                checkout_forms = orders_data.get("checkoutForms", [])
                if not checkout_forms:
                    break
                
                # Собираем ID заказов, которые нужно обновить
                orders_to_update = []
                for order_data in checkout_forms:
                    order_id = order_data["id"]
                    update_time = order_data.get("updateTime")
                    
                    # Проверяем, нужно ли обновлять заказ
                    if order_id not in existing_orders or existing_orders[order_id] != update_time:
                        orders_to_update.append(order_id)
                
                # Получаем детали только для заказов, которые нужно обновить
                for order_id in orders_to_update:
                    # Проверяем rate limit перед каждым запросом деталей
                    allegro_rate_limiter.wait_if_needed()
                    
                    order_details = service.api_service.get_order_details(
                        token=token.access_token,
                        order_id=order_id
                    )
                    
                    if order_id in existing_orders:
                        service.repository.update_order(order_id, order_details)
                    else:
                        service.repository.add_order(order_details)
                    
                    total_synced += 1
                
                # Если получили меньше заказов чем limit, значит это последняя страница
                if len(checkout_forms) < limit:
                    break
                    
                offset += limit
            
            # Сохраняем время последней синхронизации
            if checkout_forms:
                last_order_time = checkout_forms[0].get("updateTime")
                if last_order_time:
                    # Если last_order_time это строка, преобразуем её в datetime
                    if isinstance(last_order_time, str):
                        last_order_time = datetime.fromisoformat(last_order_time)
                    celery.backend.set(f"last_sync_time_{token_id}", last_order_time.isoformat())
            else:
                # Если заказов нет, сохраняем текущее время
                celery.backend.set(f"last_sync_time_{token_id}", datetime.utcnow().isoformat())
            
            logger.info(f"Успешно синхронизировано {total_synced} заказов")
            return {
                "status": "success",
                "message": "Синхронизация завершена",
                "from_date": from_date
            }
        finally:
            session.close()
            
    except ValueError as e:
        logger.error(f"Ошибка валидации: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Ошибка при синхронизации: {str(e)}")
        return {
            "status": "error",
            "message": f"Ошибка при синхронизации: {str(e)}"
        }

@celery.task(name='tasks.check_recent_orders')
def check_recent_orders(token_id: str):
    """
    Задача для проверки обновлений заказов за последние 3 дня.
    Запускается каждый час.
    """
    logger.info("Начинаем проверку недавних заказов Allegro")
    
    try:
        with Session(engine) as session:
            service = SyncAllegroOrderService(session)
            
            # Получаем и проверяем токен из базы данных
            token = get_allegro_token(session, token_id)
            
            # Устанавливаем временной диапазон
            now = datetime.utcnow()
            three_days_ago = now - timedelta(days=3)
            
            # Получаем время последней проверки из Redis
            last_check_time = celery.backend.get('last_check_time')
            if last_check_time:
                # Декодируем байты в строку и парсим в datetime
                last_check_time = datetime.fromisoformat(last_check_time.decode('utf-8'))
                # Используем более раннее время для надежности
                from_time = min(three_days_ago, last_check_time)
            else:
                from_time = three_days_ago
            
            offset = 0
            limit = 100
            total_checked = 0
            updated_orders = 0
            
            # Получаем все существующие заказы из базы одним запросом
            existing_orders = {
                order["id"]: order["updateTime"] 
                for order in service.repository.get_all_orders_basic_info()
            }
            
            while True:
                # Проверяем rate limit перед запросом
                allegro_rate_limiter.wait_if_needed()
                
                # Получаем страницу заказов
                orders_data = service.api_service.get_orders(
                    token=token.access_token,
                    status="READY_FOR_PROCESSING",
                    offset=offset,
                    limit=limit,
                    updated_at_gte=from_time,
                    updated_at_lte=now,
                    sort="-updatedAt"  # Сортируем по времени обновления
                )
                
                checkout_forms = orders_data.get("checkoutForms", [])
                if not checkout_forms:
                    break
                
                # Собираем ID заказов, которые нужно обновить
                orders_to_update = []
                for order_data in checkout_forms:
                    order_id = order_data["id"]
                    update_time = order_data.get("updateTime")
                    total_checked += 1
                    
                    # Проверяем, нужно ли обновлять заказ
                    if order_id not in existing_orders or existing_orders[order_id] != update_time:
                        orders_to_update.append(order_id)
                
                # Получаем детали только для заказов, которые нужно обновить
                for order_id in orders_to_update:
                    # Проверяем rate limit перед каждым запросом деталей
                    allegro_rate_limiter.wait_if_needed()
                    
                    order_details = service.api_service.get_order_details(
                        token=token.access_token,
                        order_id=order_id
                    )
                    
                    if order_id in existing_orders:
                        service.repository.update_order(order_id, order_details)
                    else:
                        service.repository.add_order(order_details)
                    
                    updated_orders += 1
                
                # Если получили меньше заказов чем limit, значит это последняя страница
                if len(checkout_forms) < limit:
                    break
                    
                offset += limit
            
            # Сохраняем время проверки
            celery.backend.set('last_check_time', now.isoformat())
            
            logger.info(f"Проверено {total_checked} заказов, обновлено {updated_orders}")
            return {
                "status": "success",
                "total_checked": total_checked,
                "updated_orders": updated_orders,
                "period": {
                    "from": from_time.isoformat(),
                    "to": now.isoformat()
                }
            }
            
    except Exception as e:
        logger.error(f"Ошибка при проверке заказов: {str(e)}")
        raise

@celery.task(name='tasks.sync_all_tokens')
def sync_all_tokens():
    """
    Задача для синхронизации заказов всех токенов.
    Запускается каждый час.
    """
    logger.info("Начинаем синхронизацию заказов для всех токенов")
    
    try:
        with Session(engine) as session:
            # Получаем все активные токены
            tokens = session.query(AllegroToken).all()
            
            for token in tokens:
                try:
                    # Запускаем проверку новых заказов для каждого токена
                    check_recent_orders.delay(token.id_)
                except Exception as e:
                    logger.error(f"Ошибка при синхронизации токена {token.id_}: {str(e)}")
                    continue
                    
        logger.info("Синхронизация всех токенов завершена")
    except Exception as e:
        logger.error(f"Ошибка при синхронизации токенов: {str(e)}")
        raise

@celery.task(name='tasks.sync_allegro_orders_immediate')
def sync_allegro_orders_immediate(token_id: str, from_date: str = None) -> Dict[str, Any]:
    """
    Немедленно синхронизирует заказы для указанного токена.
    
    Args:
        token_id: ID токена
        from_date: Дата в формате DD-MM-YYYY, с которой начать синхронизацию (опционально)
    """
    try:
        # Парсим дату только если она передана как строка
        parsed_date = parse_date(from_date) if isinstance(from_date, str) else from_date
        
        # Получаем время последней синхронизации
        last_sync_time = celery.backend.get(f"last_sync_time_{token_id}")
        if last_sync_time:
            last_sync_time = last_sync_time.decode('utf-8')
        if parsed_date:
            last_sync_time = parsed_date
            logger.info(f"Синхронизация начнется с {parsed_date} (00:00:00)")
        elif last_sync_time:
            # Если last_sync_time это строка, преобразуем её в datetime
            if isinstance(last_sync_time, str):
                last_sync_time = datetime.fromisoformat(last_sync_time)
            logger.info(f"Синхронизация начнется с последней синхронизации: {last_sync_time}")
        else:
            last_sync_time = datetime.now() - timedelta(days=30)
            logger.info(f"Синхронизация начнется с 30 дней назад: {last_sync_time}")
            
        logger.info("Начинаем немедленную синхронизацию заказов Allegro")
        
        session = SessionLocal()
        try:
            service = SyncAllegroOrderService(session)
            
            # Получаем и проверяем токен из базы данных
            token = get_allegro_token(session, token_id)
            
            offset = 0
            limit = 100
            total_synced = 0
            
            # Получаем все существующие заказы из базы одним запросом
            existing_orders = {}
            orders_info = service.repository.get_all_orders_basic_info()
            if orders_info:
                existing_orders = {
                    order["id"]: order["updateTime"] 
                    for order in orders_info
                }
                logging.info(f"Загружено {len(existing_orders)} существующих заказов")
            else:
                logging.info("Нет существующих заказов, будет выполнена полная синхронизация")
            
            while True:
                # Проверяем rate limit перед запросом
                allegro_rate_limiter.wait_if_needed()
                
                # Получаем страницу заказов
                orders_data = service.api_service.get_orders(
                    token=token.access_token,
                    status="READY_FOR_PROCESSING",
                    offset=offset,
                    limit=limit,
                    updated_at_gte=last_sync_time if last_sync_time else None,
                    sort="-lineItems.boughtAt"  # Сначала новые заказы
                )
                
                checkout_forms = orders_data.get("checkoutForms", [])
                if not checkout_forms:
                    break
                
                # Собираем ID заказов, которые нужно обновить
                orders_to_update = []
                for order_data in checkout_forms:
                    order_id = order_data["id"]
                    update_time = order_data.get("updateTime")
                    
                    # Проверяем, нужно ли обновлять заказ
                    if order_id not in existing_orders or existing_orders[order_id] != update_time:
                        orders_to_update.append(order_id)
                
                # Получаем детали только для заказов, которые нужно обновить
                for order_id in orders_to_update:
                    # Проверяем rate limit перед каждым запросом деталей
                    allegro_rate_limiter.wait_if_needed()
                    
                    order_details = service.api_service.get_order_details(
                        token=token.access_token,
                        order_id=order_id
                    )
                    
                    try:
                        if order_id in existing_orders:
                            service.repository.update_order(token_id, order_id, order_details)
                        else:
                            service.repository.add_order(token_id, order_details)
                        
                        total_synced += 1
                    except Exception as e:
                        if "duplicate key value violates unique constraint" in str(e):
                            # Если это дублирование покупателя, получаем существующего и пробуем снова
                            logger.info(f"Найден существующий покупатель для заказа {order_id}, используем его")
                            # Получаем существующего покупателя и пробуем добавить заказ снова
                            service.repository.add_order_with_existing_buyer(token_id, order_details)
                            total_synced += 1
                        else:
                            raise
                
                # Если получили меньше заказов чем limit, значит это последняя страница
                if len(checkout_forms) < limit:
                    break
                    
                offset += limit
            
            # Сохраняем время последней синхронизации
            if checkout_forms:
                last_order_time = checkout_forms[0].get("updateTime")
                if last_order_time:
                    # Если last_order_time это строка, преобразуем её в datetime
                    if isinstance(last_order_time, str):
                        last_order_time = datetime.fromisoformat(last_order_time)
                    celery.backend.set(f"last_sync_time_{token_id}", last_order_time.isoformat())
            else:
                # Если заказов нет, сохраняем текущее время
                celery.backend.set(f"last_sync_time_{token_id}", datetime.utcnow().isoformat())
            
            logger.info(f"Успешно синхронизировано {total_synced} заказов")
            return {
                "status": "success",
                "message": "Немедленная синхронизация завершена",
                "from_date": from_date
            }
        finally:
            session.close()
            
    except ValueError as e:
        logger.error(f"Ошибка валидации: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }
    except Exception as e:
        logger.error(f"Ошибка при синхронизации: {str(e)}")
        return {
            "status": "error",
            "message": f"Ошибка при синхронизации: {str(e)}"
        }


