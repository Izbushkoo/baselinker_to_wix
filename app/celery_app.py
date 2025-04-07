import requests
import csv
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlmodel import Session
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

from celery import Celery, chord, group, chain
from celery.schedules import crontab, schedule

from app.services import baselinker as BL
from app.services.process_funcs import transform_product
from app.schemas.wix_models import WixImportFileModel
from app.schemas.wix_models import generate_handle_id
from app.utils.logging_config import logger

import os

from app.services.allegro.order_service import SyncAllegroOrderService
from app.database import engine

import time
from app.models.allegro_token import AllegroToken
from app.services.allegro.tokens import check_token_sync
from app.services.allegro.data_access import get_token_by_id_sync
from app.utils.date_utils import parse_date
from app.drive import authenticate_service_account
from app.utils.dump_utils import dump_and_upload_to_drive
import redis
from celery.beat import PersistentScheduler, ScheduleEntry
import json
from collections import UserDict


def get_redis_client():
    redis_url = os.getenv("CELERY_REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(redis_url)

class DummyStore(UserDict):
    def sync(self):
        # Для совместимости; здесь ничего не нужно делать
        pass

    def close(self):
        # Для совместимости; ничего не делаем
        pass

class RedisScheduler(PersistentScheduler):
    def __init__(self, *args, **kwargs):
        super(RedisScheduler, self).__init__(*args, **kwargs)
        # Получаем URL Redis из переменной окружения (по умолчанию: redis://redis:6379/0)
        redis_url = os.getenv("CELERY_REDIS_URL", "redis://redis:6379/0")
        self.redis_client = redis.Redis.from_url(redis_url)
        self.schedule_key = "celery_beat_schedule"
        self.last_schedule = None
        self.reload_schedule_from_redis()

    def reload_schedule_from_redis(self):
        schedule_data = self.redis_client.get(self.schedule_key)
        if schedule_data:
            try:
                new_schedule = json.loads(schedule_data.decode("utf-8"))
                if new_schedule != self.last_schedule:
                    self.merge_inplace(new_schedule)
                    # Оборачиваем обновлённое расписание в DummyStore с ключом 'entries'
                    self._store = DummyStore({'entries': self.app.conf.beat_schedule})
                    self.last_schedule = new_schedule
                    logger.info("RedisScheduler: Schedule reloaded from Redis: %s", new_schedule)
            except Exception as e:
                logger.error("RedisScheduler: Error loading schedule from Redis: %s", e)
        else:
            logger.info("RedisScheduler: No schedule found in Redis.")

    def tick(self):
        # При каждом тике проверяем изменения в расписании и обновляем их
        self.reload_schedule_from_redis()
        return super(RedisScheduler, self).tick()

    def merge_inplace(self, schedule_dict):
        for name, config in schedule_dict.items():
            sched = config.get("schedule")

            if isinstance(config, ScheduleEntry):
                # если это уже Entry — оставляем как есть
                entry = config

            elif isinstance(sched, (schedule, crontab)):
                # если это crontab или другой schedule — используем его напрямую
                entry = ScheduleEntry(
                    name=name,
                    task=config["task"],
                    schedule=sched,
                    args=tuple(config.get("args", [])),
                    kwargs=config.get("kwargs", {}),
                    options=config.get("options", {}),
                    last_run_at=None,
                )

            else:
                # иначе пытаемся трактовать как число секунд
                try:
                    seconds = float(sched)
                except (ValueError, TypeError):
                    seconds = 300
                entry = ScheduleEntry(
                    name=name,
                    task=config["task"],
                    schedule=timedelta(seconds=seconds),
                    args=tuple(config.get("args", [])),
                    kwargs=config.get("kwargs", {}),
                    options=config.get("options", {}),
                    last_run_at=None,
                )

            self.app.conf.beat_schedule[name] = entry

        return self.app.conf.beat_schedule
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
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s',
    broker_connection_retry_on_startup=True  # Добавляем эту настройку для устранения предупреждения
)

celery.conf.beat_scheduler = "app.celery_app.RedisScheduler"
# Настройка периодических задач
celery.conf.beat_schedule = {
    'backup-base-daily': {
        'task': 'app.backup_base',
        'schedule': crontab(hour="3", minute="10"),
    },
}

celery.conf.timezone = 'UTC'
celery.conf.worker_pool = 'threads'
celery.conf.worker_concurrency = 4

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
    logger.info(f"{result}")

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
    logger.info(f"{all_products}")
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

@celery.task(name='app.celery_app.sync_allegro_orders')
def sync_allegro_orders(token_id: str, from_date: str = None) -> Dict[str, Any]:
    """
    Синхронизирует заказы для указанного токена.
    
    Args:
        token_id: ID токена
        from_date: Дата в формате DD-MM-YYYY (например, "20-03-2025"), с которой начать синхронизацию.
                  Если указана, синхронизация начнется с 00:00:00 указанного дня.
                  Если не указана, будет использовано время 30 дней назад.
    """
    try:
        redis_client = get_redis_client()
        
        # Определяем время начала синхронизации
        if from_date:
            # Если передана дата, преобразуем её в datetime с временем 00:00:00
            last_sync_time = parse_date(from_date)
            if not last_sync_time:
                raise ValueError(f"Неверный формат даты: {from_date}")
            logger.info(f"Синхронизация начнется с {last_sync_time.isoformat()}")
        else:
            # Получаем время последней синхронизации из Redis
            last_sync_raw = redis_client.get(f"last_sync_time_{token_id}")
            if last_sync_raw:
                try:
                    last_sync_time = datetime.fromisoformat(last_sync_raw.decode('utf-8'))
                    logger.info(f"Синхронизация начнется с последней синхронизации: {last_sync_time.isoformat()}")
                except ValueError:
                    # Если не удалось распарсить дату из Redis, используем 30 дней назад
                    last_sync_time = datetime.utcnow() - timedelta(days=30)
                    logger.warning(f"Не удалось распарсить дату из Redis, используем: {last_sync_time.isoformat()}")
            else:
                # Если нет сохраненного времени, используем 30 дней назад
                last_sync_time = datetime.utcnow() - timedelta(days=30)
                logger.info(f"Синхронизация начнется с 30 дней назад: {last_sync_time.isoformat()}")

        logger.info(f"last_sync_time_{token_id}: {last_sync_time.isoformat()}")    
        logger.info("Начинаем полную синхронизацию заказов Allegro")
        
        session = SessionLocal()
        try:
            service = SyncAllegroOrderService(session)
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
                logger.info(f"Загружено {len(existing_orders)} существующих заказов")
            else:
                logger.info("Нет существующих заказов, будет выполнена полная синхронизация")
            
            while True:
                # Проверяем rate limit перед запросом
                allegro_rate_limiter.wait_if_needed()
                
                orders_data = service.api_service.get_orders(
                    token=token.access_token,
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
                    update_time = datetime.fromisoformat(order_data.get("updatedAt").replace('Z', '+00:00'))

                    order_id = order_data["id"]
                    
                    # Проверяем, нужно ли обновлять заказ
                    if order_id not in existing_orders:
                        orders_to_update.append(order_id)
                    else:
                        existing_update_time = existing_orders[order_id]
                        if update_time.replace(tzinfo=None) > existing_update_time.replace(tzinfo=None):
                            orders_to_update.append(order_id)
                
                # Получаем детали только для заказов, которые нужно обновить
                for order_id in orders_to_update:
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
            
            redis_client.set(f"last_sync_time_{token_id}", (datetime.utcnow() - timedelta(days=10)).isoformat())
            
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

@celery.task(name='app.celery_app.check_recent_orders')
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
            
            offset = 0
            limit = 100
            total_checked = 0
            updated_orders = 0
            
            # Получаем все существующие заказы из базы одним запросом
            existing_orders = {}
            orders_info = service.repository.get_all_orders_basic_info()
            if orders_info:
                existing_orders = {
                    order["id"]: order["updateTime"] for order in orders_info
                }
            
            while True:
                # Проверяем rate limit перед запросом
                allegro_rate_limiter.wait_if_needed()
                
                # Получаем страницу заказов
                orders_data = service.api_service.get_orders(
                    token=token.access_token,
                    # status="READY_FOR_PROCESSING",
                    offset=offset,
                    limit=limit,
                    updated_at_gte=three_days_ago,
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
                    try:
                        update_time = datetime.fromisoformat(order_data.get("updatedAt").replace('Z', '+00:00'))
                    except Exception as e:
                        logger.error(f"Ошибка при парсинге даты для заказа {order_id}: {str(e)} {order_data.get('updatedAt')}")
                        continue
                    total_checked += 1
                    logger.info(f"update_time: {update_time}    existing_orders[order_id]: {existing_orders[order_id]}")
                    # Проверяем, нужно ли обновлять заказ
                    if order_id not in existing_orders or update_time.replace(tzinfo=None) !=  existing_orders[order_id].replace(tzinfo=None):
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
                        updated_orders += 1
                    except Exception as e:
                        if "duplicate key value violates unique constraint" in str(e):
                            # Если это дублирование покупателя, получаем существующего и пробуем снова
                            logger.info(f"Найден существующий покупатель для заказа {order_id}, используем его")
                            service.repository.add_order_with_existing_buyer(token_id, order_details)
                            updated_orders += 1
                        else:
                            raise
                
                # Если получили меньше заказов чем limit, значит это последняя страница
                if len(checkout_forms) < limit:
                    break
                    
                offset += limit
            
            logger.info(f"Проверено {total_checked} заказов, обновлено {updated_orders}\n Срок проверки: {three_days_ago.isoformat()} - {now.isoformat()}")
            return {
                "status": "success",
                "total_checked": total_checked,
                "updated_orders": updated_orders,
                "period": {
                    "from": three_days_ago.isoformat(),
                    "to": now.isoformat()
                }
            }
            
    except Exception as e:
        logger.error(f"Ошибка при проверке заказов: {str(e)}")
        return {"status": "error", "message": str(e)}


@celery.task(name="app.backup_base")
def backup_base():
    permission = {
        'type': 'user',
        'role': 'writer',
        'emailAddress': 'info@tailwhip.store'
    }

    service = authenticate_service_account()

    return dump_and_upload_to_drive(
        service=service,
        database_url=settings.SQLALCHEMY_DATABASE_URI.unicode_string(),
        permission=permission
    )


@celery.task(name='app.celery_app.sync_allegro_orders_immediate')
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
        
        # Получаем время последней синхронизации из Redis
        redis_client = get_redis_client()
        last_sync_raw = redis_client.get(f"last_sync_time_{token_id}")
        if last_sync_raw:
            try:
                last_sync_time = datetime.fromisoformat(last_sync_raw.decode('utf-8'))
                logger.info(f"Синхронизация начнется с последней синхронизации: {last_sync_time.isoformat()}")
            except ValueError:
                last_sync_time = datetime.utcnow() - timedelta(days=30)
                logger.warning(f"Не удалось распарсить дату из Redis, используем: {last_sync_time.isoformat()}")
        else:
            last_sync_time = datetime.utcnow() - timedelta(days=30)
            logger.info(f"Синхронизация начнется с 30 дней назад: {last_sync_time.isoformat()}")

        if parsed_date:
            last_sync_time = parsed_date
            logger.info(f"Синхронизация начнется с {parsed_date.isoformat()} (00:00:00)")
            
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
                logger.info(f"Загружено {len(existing_orders)} существующих заказов")
            else:
                logger.info("Нет существующих заказов, будет выполнена полная синхронизация")
            
            while True:
                # Проверяем rate limit перед запросом
                allegro_rate_limiter.wait_if_needed()
                
                # Получаем страницу заказов
                orders_data = service.api_service.get_orders(
                    token=token.access_token,
                    # status=["BOUGHT"],
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
                    update_time = datetime.fromisoformat(order_data.get("updatedAt").replace('Z', '+00:00'))
                    order_id = order_data["id"]
                    
                    # Проверяем, нужно ли обновлять заказ
                    if order_id not in existing_orders:
                        orders_to_update.append(order_id)
                    else:
                        existing_update_time = existing_orders[order_id]
                        if update_time > existing_update_time:
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
            redis_client.set(f"last_sync_time_{token_id}", (datetime.utcnow() - timedelta(seconds=5)).isoformat())

            logger.info(f"Успешно синхронизировано {total_synced} заказов")
            return {
                "status": "success",
                "message": "Немедленная синхронизация завершена",
                "total_synced": total_synced,
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





