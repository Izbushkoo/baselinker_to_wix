import traceback
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlmodel import Session, select
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from celery import Celery, chord, group, chain
from celery.schedules import crontab, schedule

from app.services.warehouse.manager import Warehouses
from app.services import baselinker as BL
from app.services.process_funcs import transform_product
from app.schemas.wix_models import WixImportFileModel
from app.schemas.wix_models import generate_handle_id
from app.utils.logging_config import logger

import os

from app.services.allegro.order_service import SyncAllegroOrderService
from app.services.allegro.allegro_api_service import SyncAllegroApiService
from app.database import engine

import time
from app.models.allegro_token import AllegroToken
from app.services.allegro.tokens import check_token_sync
from app.services.allegro.data_access import get_token_by_id_sync
from app.utils.date_utils import parse_date
from app.drive import authenticate_service_account, imperson_auth
from app.utils.dump_utils import dump_and_upload_to_drive
import redis
from celery.beat import PersistentScheduler, ScheduleEntry
import json
from collections import UserDict
from app.services.stock_service import AllegroStockService
from app.services.warehouse import manager
from app.services.warehouse.manager import InventoryManager
from app.services.tg_client import TelegramManager
from app.models.allegro_order import AllegroOrder
import csv
import requests

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
        """
        Переводим каждую запись schedule_dict в ScheduleEntry и обновляем
        self.app.conf.beat_schedule.
        """
        new_schedule = {}

        for name, config in schedule_dict.items():
            # 1) Если это уже ScheduleEntry — оставляем «как есть»
            if isinstance(config, ScheduleEntry):
                new_schedule[name] = config
                continue

            # 2) Иначе config — dict, вытаскиваем параметры
            task = config.get("task")
            args = tuple(config.get("args", []))
            kwargs = config.get("kwargs", {})
            options = config.get("options", {})
            raw_sched = config.get("schedule")

            # 3) Обрабатываем разные типы raw_sched
            if isinstance(raw_sched, (schedule, crontab)):
                entry_schedule = raw_sched
            elif isinstance(raw_sched, str) and "crontab" in raw_sched:
                # Преобразуем строковое представление crontab обратно в объект
                try:
                    # Извлекаем параметры из строки
                    import re
                    pattern = r"crontab\(([^)]+)\)"
                    match = re.search(pattern, raw_sched)
                    if match:
                        params = match.group(1)
                        # Безопасное выполнение crontab с извлеченными параметрами
                        entry_schedule = eval(f"crontab({params})")
                    else:
                        entry_schedule = crontab()
                except Exception as e:
                    logger.error(f"Ошибка при парсинге crontab: {str(e)}")
                    entry_schedule = crontab()
            else:
                # Пытаемся привести к числу секунд
                try:
                    seconds = float(raw_sched)
                except (TypeError, ValueError):
                    seconds = 300  # fallback
                entry_schedule = timedelta(seconds=seconds)

            # 4) Создаём новый ScheduleEntry
            entry = ScheduleEntry(
                name=name,
                task=task,
                schedule=entry_schedule,
                args=args,
                kwargs=kwargs,
                options=options,
                last_run_at=None,
            )
            new_schedule[name] = entry

        # 5) Заменяем beat_schedule целиком
        self.app.conf.beat_schedule = new_schedule
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

# Определяем расписание по умолчанию
DEFAULT_BEAT_SCHEDULE = {
    # 'backup-base-daily': {
    #     'task': 'app.backup_base',
    #     'schedule': crontab(hour="3", minute="10").__repr__(),
    # },
    'check-and-update-stock': {
        'task': 'app.celery_app.check_and_update_stock',
        'schedule': 500,  # 20 минут = 1200 секунд
    },
}

def initialize_beat_schedule():
    """Инициализирует расписание в Redis, если оно отсутствует"""
    try:
        redis_client = get_redis_client()
        schedule_raw = redis_client.get("celery_beat_schedule")
        
        if not schedule_raw:
            logger.info("Инициализация начального расписания в Redis")
            redis_client.set("celery_beat_schedule", json.dumps(DEFAULT_BEAT_SCHEDULE))
            logger.info("Начальное расписание успешно установлено")
        else:
            # Проверяем наличие задач по умолчанию в существующем расписании
            current_schedule = json.loads(schedule_raw.decode("utf-8"))
            schedule_updated = False
            
            for task_name, task_config in DEFAULT_BEAT_SCHEDULE.items():
                if task_name not in current_schedule:
                    current_schedule[task_name] = task_config
                    schedule_updated = True
            
            if schedule_updated:
                logger.info("Добавление отсутствующих задач по умолчанию в существующее расписание")
                redis_client.set("celery_beat_schedule", json.dumps(current_schedule))
                logger.info("Расписание успешно обновлено")
            
    except Exception as e:
        logger.error(f"Ошибка при инициализации расписания: {str(e)}")

celery.conf.beat_scheduler = "app.celery_app.RedisScheduler"

# Инициализируем расписание
initialize_beat_schedule()

celery.conf.timezone = 'UTC'
celery.conf.worker_pool = 'threads'
celery.conf.worker_concurrency = 4

def chunks(lst, n):
    """Возвращает генератор чанков размера n из списка lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


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


@celery.task(name="app.backup_base")
def backup_base():

    service = imperson_auth()

    return dump_and_upload_to_drive(
        service=service,
        database_url=settings.SQLALCHEMY_DATABASE_URI.unicode_string(),
    )



def _parse_date_val(val: Optional[Any]) -> Optional[datetime]:
    """Если val — str, пытаемся strptime; 
       если уже datetime, возвращаем как есть."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        # ожидаем формат 'DD-MM-YYYY'
        return datetime.strptime(val, "%d-%m-%Y")
    except Exception:
        raise ValueError(f"Неверный формат даты: {val}")

def _sync_orders_core(
    token_id: str,
    from_date: Optional[Any],
    stock_update_method: str
) -> Dict[str, Any]:
    """
    Универсальная синхронизация заказов.
    
    stock_update_method: имя метода AllegroStockService,
        либо 'process_order_stock_update', либо 'mark_order_stock_updated'
    """
    try:
        redis_client = get_redis_client()

        # 1) Определяем время с которого синхроним
        raw = redis_client.get(f"last_sync_time_{token_id}")
        if raw:
            try:
                # Если есть время последней синхронизации, берем его минус 10 дней
                last_sync_time = datetime.fromisoformat(raw.decode()) - timedelta(days=10)
                logging.info(f"Начинаем с последней точки минус 10 дней: {last_sync_time}")
            except ValueError:
                # При ошибке парсинга - 30 дней
                last_sync_time = datetime.utcnow() - timedelta(days=30)
                logging.warning(f"Не смогли парсить Redis, берём 30 дней назад: {last_sync_time}")
        else:
            # Если нет записи - 30 дней
            last_sync_time = datetime.utcnow() - timedelta(days=30)
            logging.info(f"Нет записи в Redis, берём 30 дней назад: {last_sync_time}")

        session: Session = SessionLocal()
        try:
            order_service = SyncAllegroOrderService(session)
            token = get_allegro_token(session, token_id)

            stock_service = AllegroStockService(session, manager.get_manager())
            updater = getattr(stock_service, stock_update_method)

            offset = 0
            limit = 100
            synced = 0
            stock_updates = 0

            # Загружаем все существующие заказы
            existing = {
                o["id"]: o["updateTime"]
                for o in order_service.repository.get_all_orders_basic_info(token_id) or []
            }

            while True:
                allegro_rate_limiter.wait_if_needed()
                page = order_service.api_service.get_orders(
                    token.access_token,
                    offset=offset,
                    limit=limit,
                    updated_at_gte=last_sync_time,
                    sort="-lineItems.boughtAt"
                )
                forms = page.get("checkoutForms", [])
                if not forms:
                    break

                # Обрабатываем все заказы на странице
                for form in forms:
                    order_id = form["id"]
                    allegro_rate_limiter.wait_if_needed()
                    
                    # Получаем детали заказа
                    details = order_service.api_service.get_order_details(
                        token.access_token, order_id
                    )
                    
                    try:
                        # Обновляем существующий или создаем новый заказ
                        if order_id in existing:
                            order = order_service.repository.update_order(token_id, order_id, details)
                        else:
                            order = order_service.repository.add_order(token_id, details)
                        synced += 1

                        # Обновляем статус склада
                        if updater(order, warehouse=Warehouses.A):
                            stock_updates += 1
                            
                    except Exception as e:
                        if "duplicate key value violates unique constraint" in str(e):
                            # Если это дублирование покупателя, получаем существующего и пробуем снова
                            logger.info(f"Найден существующий покупатель для заказа {order_id}, используем его")
                            order = order_service.repository.add_order_with_existing_buyer(token_id, details)
                            if updater(order, warehouse=Warehouses.A):
                                stock_updates += 1
                            synced += 1
                        else:
                            logger.error(f"Ошибка при обработке заказа {order_id}: {str(e)}")
                            continue

                # Если получили меньше заказов чем limit, значит это последняя страница
                if len(forms) < limit:
                    break
                    
                offset += limit

            # сохраняем точку
            redis_client.set(
                f"last_sync_time_{token_id}",
                (datetime.utcnow() - timedelta(seconds=5)).isoformat()
            )

            return {
                "status": "success",
                "orders_synced": synced,
                "stock_updated": stock_updates
            }
        finally:
            session.close()

    except Exception as e:
        logger.error("Ошибка при синхронизации:", exc_info=True)
        return {"status": "error", "message": str(e)}


@celery.task(name="app.celery_app.sync_allegro_orders")
def sync_allegro_orders(token_id: str, from_date: Optional[str] = None):
    # здесь вызываем общий код с process_order_stock_update
    return _sync_orders_core(token_id, from_date, "process_order_stock_update")


@celery.task(name="app.celery_app.sync_allegro_orders_immediate")
def sync_allegro_orders_immediate(token_id: str, from_date: Optional[str] = None):
    # здесь — с mark_order_stock_updated
    return _sync_orders_core(token_id, from_date, "mark_order_stock_updated")


@celery.task(name="app.celery_app.check_and_update_stock")
def check_and_update_stock():
    """
    Проверяет все заказы для всех токенов и пытается произвести списание товаров,
    если они еще не были списаны (is_stock_updated = False).
    """
    try:
        session = SessionLocal()
        try:
            # Получаем все токены
            tokens_query = select(AllegroToken)
            tokens = session.exec(tokens_query).all()
            
            if not tokens:
                logger.info("Нет токенов Allegro в базе данных")
                return {"status": "success", "message": "Нет токенов для обработки"}

            total_processed = 0
            total_updated = 0
            stock_service = AllegroStockService(session, manager.get_manager())

            for token in tokens:
                # Получаем все заказы для токена, где is_stock_updated = False
                orders_query = select(AllegroOrder).where(
                    AllegroOrder.token_id == token.id_,
                    AllegroOrder.is_stock_updated == False
                )
                orders = session.exec(orders_query).all()

                logger.info(f"Найдено {len(orders)} необработанных заказов для токена {token.id_}")

                for order in orders:
                    try:
                        if stock_service.process_order_stock_update(order, warehouse=manager.Warehouses.A.value):
                            total_updated += 1
                        total_processed += 1
                    except Exception as e:
                        logger.error(f"Ошибка при обработке заказа {order.id}: {str(e)}")
                        continue

            logger.info(f"Обработано заказов: {total_processed}, успешно списано: {total_updated}")
            return {
                "status": "success", 
                "total_processed": total_processed,
                "total_updated": total_updated
            }

        finally:
            session.close()

    except Exception as e:
        logger.error(f"Ошибка при проверке и обновлении стоков: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@celery.task(name="app.celery_app.process_allegro_order_events")
def process_allegro_order_events(token_id: str):
    """
    Обрабатывает события заказов Allegro.
    
    Args:
        token_id: ID токена Allegro
    """
    try:
        redis_client = get_redis_client()
        session = SessionLocal()
        
        try:
            # Получаем и проверяем токен
            token = get_allegro_token(session, token_id)
            
            # Создаем необходимые сервисы
            api_service = SyncAllegroApiService()
            order_service = SyncAllegroOrderService(session)
            
            # Получаем ID последнего обработанного события из Redis
            last_event_id = redis_client.get(f"last_allegro_event_{token_id}")
            
            if not last_event_id:
                # Если нет сохраненного события, получаем статистику
                logger.info(f"Нет сохраненного события для токена {token_id}, получаем статистику")
                stats = api_service.get_order_events_statistics(token.access_token)
                last_event_id = stats.get("latestEvent", {}).get("id")
                
                if not last_event_id:
                    logger.warning(f"Не удалось получить ID последнего события для токена {token_id}")
                    return {"status": "error", "message": "Не удалось получить ID последнего события"}
            
            # Получаем новые события
            allegro_rate_limiter.wait_if_needed()
            events = api_service.get_order_events_v2(
                token=token.access_token,
                from_event_id=last_event_id.decode() if isinstance(last_event_id, bytes) else last_event_id,
                limit=100
            )
            
            events_list = events.get("events", [])
            if not events_list:
                logger.info(f"Нет новых событий для токена {token_id}")
                return {"status": "success", "message": "Нет новых событий"}
            
            # Обрабатываем каждое событие
            processed_count = 0
            last_processed_id = None
            
            for event in events_list:
                try:
                    # Обрабатываем событие
                    order = order_service.repository.process_order_event(token_id, event, api_service)
                    if order:
                        processed_count += 1
                        last_processed_id = event.get("id")
                except Exception as e:
                    logger.error(f"Ошибка при обработке события {event.get('id')}: {str(e)}")
                    continue
            
            # Сохраняем ID последнего обработанного события
            if last_processed_id:
                redis_client.set(f"last_allegro_event_{token_id}", last_processed_id)
                logger.info(f"Сохранен ID последнего обработанного события: {last_processed_id}")
            else:
                redis_client.set(f"last_allegro_event_{token_id}", last_event_id)

            return {
                "status": "success",
                "processed_events": processed_count,
                "last_event_id": last_processed_id if last_processed_id else last_event_id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при обработке событий заказов: {str(e)}")
        return {"status": "error", "message": str(e)}


