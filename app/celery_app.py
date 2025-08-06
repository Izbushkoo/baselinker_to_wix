import traceback
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlmodel import Session, select
from sqlalchemy import func
import os
from dotenv import load_dotenv
# Загружаем переменные окружения перед импортом config
load_dotenv()

# Проверяем, запущено ли приложение в Docker
is_docker = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")

# Если запущено в Docker, перезагружаем переменные из .env.docker
if is_docker:
    load_dotenv(".env.docker", override=True)
    print("Celery: Загружены переменные из .env.docker")

from app.core.config import settings
from app.core.security import create_access_token
from celery import chord, group, chain
from celery.schedules import crontab, schedule
from app.celery_shared import celery, SessionLocal, get_allegro_token

from app.services.warehouse.manager import Warehouses
from app.services import baselinker as BL
from app.services.process_funcs import transform_product_for_shoper, transform_product
from app.schemas.wix_models import WixImportFileModel
from app.schemas.wix_models import generate_handle_id
from app.utils.logging_config import logger, get_logger, log_business_event, log_error_with_context
from app.services.tg_client import TelegramManager

from app.services.allegro.order_service import SyncAllegroOrderService
from app.services.allegro.allegro_api_service import SyncAllegroApiService, NotFoundDetails

import time
from app.models.allegro_token import AllegroToken
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
from app.repositories.allegro_event_tracker_repository import AllegroEventTrackerRepository
from app.services.wix_api_service.base import WixApiService, WixInventoryUpdate
from app.models.warehouse import Product, Stock
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient

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

# Настройки celery импортированы из celery_shared.py

# Определяем расписание по умолчанию
DEFAULT_BEAT_SCHEDULE = {
    # 'backup-base-daily': {
    #     'task': 'app.backup_base',
    #     'schedule': crontab(hour="3", minute="10").__repr__(),
    # },
    # 'check-and-update-stock': {
    #     'task': 'app.celery_app.check_and_update_stock',
    #     'schedule': 3600,  # 1 час
    # },
    'sync-wix-inventory': {
        'task': 'app.celery_app.sync_wix_inventory',
        'schedule': 3600,  # 1 час
    },
    # Задачи новой системы синхронизации складских остатков
    'process-pending-stock-operations': {
        'task': 'app.services.stock_sync_tasks.process_pending_stock_operations',
        'schedule': 300,  # 5 минут
        'kwargs': {'limit': 50}
    },
    'validate-pending-operations': {
        'task': 'app.services.stock_sync_tasks.validate_pending_operations',
        'schedule': 900,  # 15 минут
        'kwargs': {'limit': 100}
    },
    'reconcile-stock-states': {
        'task': 'app.services.stock_sync_tasks.reconcile_stock_states',
        'schedule': 3600,  # 1 час
        'kwargs': {'limit': 200}
    },
    'monitor-sync-system-health': {
        'task': 'app.services.stock_sync_tasks.monitor_sync_system_health',
        'schedule': 600  # 10 минут
    },
    'send-daily-sync-summary': {
        'task': 'app.services.stock_sync_tasks.send_daily_sync_summary',
        'schedule': crontab(hour=8, minute=0).__repr__()  # 8:00 UTC ежедневно
    },
    'cleanup-old-sync-logs': {
        'task': 'app.services.stock_sync_tasks.cleanup_old_sync_logs',
        'schedule': crontab(hour=2, minute=0).__repr__(),  # 02:00 UTC ежедневно
        'kwargs': {'days_to_keep': 30}
    }
}

def initialize_beat_schedule():
    """Инициализирует и синхронизирует расписание в Redis с DEFAULT_BEAT_SCHEDULE"""
    try:
        redis_client = get_redis_client()
        schedule_raw = redis_client.get("celery_beat_schedule")
        
        if not schedule_raw:
            # Если расписания нет - создаем новое из дефолтного
            logger.info("Инициализация начального расписания в Redis")
            redis_client.set("celery_beat_schedule", json.dumps(DEFAULT_BEAT_SCHEDULE))
            logger.info("Начальное расписание успешно установлено")
            return

        # Если расписание есть - проверяем соответствие с дефолтным
        current_schedule = json.loads(schedule_raw.decode("utf-8"))
        schedule_updated = False

        for task_name, task_config in DEFAULT_BEAT_SCHEDULE.items():
            if task_name not in current_schedule:
                # Добавляем отсутствующую задачу
                current_schedule[task_name] = task_config
                schedule_updated = True
            elif current_schedule[task_name] != task_config:
                # Обновляем конфигурацию существующей задачи
                current_schedule[task_name] = task_config
                schedule_updated = True

        if schedule_updated:
            logger.info("Обновление расписания в Redis")
            redis_client.set("celery_beat_schedule", json.dumps(current_schedule))
            logger.info("Расписание успешно синхронизировано с DEFAULT_BEAT_SCHEDULE")

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

    # TODO: Временно используем transform_product_for_shoper, потом переделаем на transform_product

    if result["status"] == "SUCCESS":
        # Обработка данных (ваша логика)
        products = result.get("products", {})
        processed_data = [transform_product_for_shoper(products.get(product_id)).model_dump() for product_id in products_chunk]
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

# SessionLocal и get_allegro_token импортированы из celery_shared.py


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
    если они еще не были списаны (stock_updated = False).
    Использует микросервис для получения заказов.
    """
    try:
        # Создаем JWT токен для работы с микросервисом
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        base_url = settings.MICRO_SERVICE_URL
        
        # Инициализируем клиенты микросервиса
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token,
            base_url=base_url
        )
        orders_client = OrdersClient(
            jwt_token=jwt_token,
            base_url=base_url
        )

        # Получаем все токены через микросервис
        tokens_response = token_client.get_tokens(per_page=100)
        logging.info(f"tokens response {tokens_response}")
        tokens = tokens_response.items
        
        if not tokens:
            logger.info("Нет токенов Allegro в базе данных")
            return {"status": "success", "message": "Нет токенов для обработки"}

        total_processed = 0
        total_updated = 0
        
        # Создаем сессию БД для работы со stock_service
        session = SessionLocal()
        try:
            stock_service = AllegroStockService(manager.get_manager())

            for token in tokens:
                token_id = token.get("id")
                logger.info(f"Обрабатываем токен {token_id}")
                
                # Получаем все заказы для токена с фильтром stock_updated = False
                # Используем пагинацию для получения всех заказов
                offset = 0
                limit = 100
                all_orders = []
                
                while True:
                    try:
                        orders_response = orders_client.get_orders(
                            token_id=token_id,
                            stock_updated=False,  # Фильтр по флагу обновления стока
                            limit=limit,
                            offset=offset
                        )
                        orders = orders_response.orders
                        
                        if not orders:
                            break
                            
                        all_orders.extend(orders)
                        
                        # Если получили меньше заказов чем лимит, значит это последняя страница
                        if len(orders) < limit:
                            break
                            
                        offset += limit
                        
                    except Exception as e:
                        logger.error(f"Ошибка при получении заказов для токена {token_id} (offset: {offset}): {str(e)}")
                        break

                logger.info(f"Найдено {len(all_orders)} необработанных заказов для токена {token_id}")

                for order_data in all_orders:
                    try:
                        if stock_service.process_order_stock_update(order_data, warehouse=manager.Warehouses.A.value, token_id=token_id, token=token):
                            total_updated += 1
                        total_processed += 1
                        
                    except Exception as e:
                        logger.error(f"Ошибка при обработке заказа {order_data.get('allegro_order_id')}: {str(e)}")
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
        session = SessionLocal()
        
        try:
            # Получаем и проверяем токен
            token = get_allegro_token(session, token_id)
            
            # Создаем необходимые сервисы
            api_service = SyncAllegroApiService()
            order_service = SyncAllegroOrderService(session)
            event_tracker_repo = AllegroEventTrackerRepository(session)
            
            # Получаем ID последнего обработанного события из БД
            last_event_id = event_tracker_repo.get_last_event_id(token_id)
            
            if not last_event_id:
                # Если нет сохраненного события, получаем статистику
                logger.info(f"Нет сохраненного события для токена {token_id}, получаем статистику")
                stats = api_service.get_order_events_statistics(token.access_token)
                logger.info(f"Получена статистика: {stats}")
                
                # Проверяем структуру ответа
                if not stats:
                    logger.error(f"Получена пустая статистика для токена {token_id}")
                    return {"status": "error", "message": "Получена пустая статистика"}
                
                latest_event = stats.get("latestEvent")
                logger.info(f"latestEvent из статистики: {latest_event}")
                
                if not latest_event:
                    logger.error(f"Поле latestEvent отсутствует в статистике для токена {token_id}")
                    return {"status": "error", "message": "Поле latestEvent отсутствует в статистике"}
                
                last_event_id = latest_event.get("id")
                logger.info(f"Извлеченный last_event_id: {last_event_id}")
                
                if not last_event_id:
                    logger.warning(f"Не удалось получить ID последнего события для токена {token_id}")
                    return {"status": "error", "message": "Не удалось получить ID последнего события"}

                event_tracker_repo.update_last_event_id(token_id, last_event_id)
                logger.info(f"Сохранен ID последнего события: {last_event_id}")
            
            # Получаем новые события
            allegro_rate_limiter.wait_if_needed()
            events = api_service.get_order_events_v2(
                token=token.access_token,
                from_event_id=last_event_id,
                limit=100
            )
            
            logger.info(f"Получены события: {events}")
            
            # Проверяем структуру ответа
            if not events:
                logger.error(f"Получен пустой ответ событий для токена {token_id}")
                return {"status": "error", "message": "Получен пустой ответ событий"}
            
            events_list = events.get("events", [])
            logger.info(f"Список событий: {events_list}")
            
            if not events_list:
                logger.info(f"Нет новых событий для токена {token_id}")
                return {"status": "success", "message": "Нет новых событий"}
            
            # Обрабатываем каждое событие
            processed_count = 0
            last_processed_id = None
            tg_client = TelegramManager(chat_id=os.getenv("NOTIFY_GROUP_ID"))

            for event in events_list:
                try:
                    # Обрабатываем событие
                    order = order_service.repository.process_order_event(token_id, token.access_token, event, api_service, token=token)
                    order = order_service.repository.process_order_event(token_id, token.access_token, event, api_service, token=token)
                    if order:
                        processed_count += 1
                        last_processed_id = event.get("id")
                        event_tracker_repo.update_last_event_id(token_id, last_processed_id)
                        logger.info(f"Сохранен ID последнего обработанного события: {last_processed_id}")
                except NotFoundDetails as e:
                    logger.error(f"Заказ {event.get('id')} не найден, пропускаем")
                    send_message_to_tg.delay(f"Задача по обработке ивента упала с ошибкой {str(e)}\n Заказ пропущен и синхронизирован не будет, если он существует необходимо вручную списать позиции такого заказа из каталога.")
                    continue
                except Exception as e:
                    logger.error(f"Ошибка при обработке события {event.get('id')}: {str(e)}")
                    send_message_to_tg.delay(f"Задача по обработке ивента упала с ошибкой {str(e)}\n Требуется вмешательство")
                    raise
                
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


@celery.task(name="app.celery_app.send_message_to_tg")
def send_message_to_tg(message: str):
    tg_client = TelegramManager(chat_id=os.getenv("NOTIFY_GROUP_ID"))
    tg_client.send_message(message)

@celery.task(name="app.celery_app.sync_wix_inventory")
def sync_wix_inventory():
    """
    Синхронизирует количество товаров между локальной базой данных и Wix.
    
    Процесс:
    1. Получает все SKU и их количество из локальной базы данных
    2. Получает информацию о товарах в Wix по SKU (product_id, variant_id, текущее количество)
    3. Вычисляет разницу между локальным и Wix количеством
    4. Обновляет количество товаров в Wix до соответствия локальной базе
    
    Returns:
        Dict: Результат синхронизации с детальной статистикой
    """
    # Проверяем загрузку переменных Wix в начале задачи
    wix_api_key = os.getenv("WIX_API_KEY")
    wix_site_id = os.getenv("WIX_SITE_ID")
    wix_account_id = os.getenv("WIX_ACCOUNT_ID")
    
    logger.info(f"Задача sync_wix_inventory - проверка переменных Wix:")
    logger.info(f"  WIX_API_KEY: {'Загружен' if wix_api_key else 'НЕ ЗАГРУЖЕН'}")
    logger.info(f"  WIX_SITE_ID: {'Загружен' if wix_site_id else 'НЕ ЗАГРУЖЕН'}")
    logger.info(f"  WIX_ACCOUNT_ID: {'Загружен' if wix_account_id else 'НЕ ЗАГРУЖЕН'}")
    
    if not wix_api_key or not wix_site_id:
        error_msg = "Критические переменные Wix не загружены в Celery worker!"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "total_products": 0,
            "found_in_wix": 0,
            "updated_in_wix": 0,
            "errors": 1
        }
    
    try:
        session = SessionLocal()
        wix_service = WixApiService()
        
        # Тестируем подключение к Wix API
        connection_test = wix_service.test_connection()
        if connection_test["status"] == "error":
            logger.error(f"Ошибка подключения к Wix API: {connection_test['message']}")
            return {
                "status": "error",
                "message": f"Ошибка подключения к Wix API: {connection_test['message']}",
                "total_products": 0,
                "found_in_wix": 0,
                "updated_in_wix": 0,
                "errors": 1
            }
        
        logger.info("Подключение к Wix API успешно установлено")
        
        try:
            logger.info("Начало синхронизации количества товаров с Wix")
            
            # 1. Получаем все товары и их остатки из локальной базы
            logger.info("Получение товаров из локальной базы данных...")
            
            # Запрос для получения всех товаров с суммарным количеством по всем складам
            products_query = select(
                Product.sku,
                Product.name,
                func.coalesce(func.sum(Stock.quantity), 0).label('total_quantity')
            ).outerjoin(
                Stock, Product.sku == Stock.sku
            ).group_by(
                Product.sku, Product.name
            ).having(
                func.coalesce(func.sum(Stock.quantity), 0) > 0  # Только товары с остатками
            )
            
            result = session.exec(products_query)
            local_products = result.all()
            
            logger.info(f"Найдено {len(local_products)} товаров с остатками в локальной базе")
            
            if not local_products:
                logger.info("Нет товаров с остатками для синхронизации")
                return {
                    "status": "success",
                    "message": "Нет товаров с остатками для синхронизации",
                    "total_products": 0,
                    "found_in_wix": 0,
                    "updated_in_wix": 0,
                    "errors": 0
                }
            
            # 2. Получаем список всех SKU
            sku_list = [product.sku for product in local_products]
            logger.info(f"Получен список из {len(sku_list)} SKU для поиска в Wix")
            
            # 3. Получаем информацию о товарах в Wix по SKU
            logger.info("Получение информации о товарах в Wix...")
            wix_products_info = wix_service.get_wix_products_info_by_sku_list(sku_list)
            
            logger.info(f"Найдено {len(wix_products_info)} товаров в Wix")
            
            # 4. Создаем словарь локальных товаров
            local_products_dict = {
                product.sku: product.total_quantity 
                for product in local_products
            }
            
            # 5. Подготавливаем обновления для Wix
            updates = []
            found_count = 0
            error_count = 0
            
            for sku, local_quantity in local_products_dict.items():
                try:
                    if sku in wix_products_info:
                        wix_info = wix_products_info[sku]
                        found_count += 1
                        
                        # Получаем текущее количество из Wix
                        current_wix_quantity = wix_info.get("current_quantity", 0)
                        
                        # Проверяем, нужно ли обновление
                        if current_wix_quantity != local_quantity:
                            # Создаем обновление для Wix
                            update = WixInventoryUpdate(
                                inventory_item_id=wix_info["inventory_item_id"],
                                variant_id=wix_info["variant_id"],
                                quantity=abs(local_quantity - current_wix_quantity)
                            )
                            updates.append((update, local_quantity > current_wix_quantity))
                            
                            logger.info(f"Подготовлено обновление для {sku}: {current_wix_quantity} -> {local_quantity} (diff: {local_quantity - current_wix_quantity})")
                        else:
                            logger.debug(f"Количество для {sku} уже актуально: {local_quantity}")
                    else:
                        logger.warning(f"Товар с SKU {sku} не найден в Wix")
                        
                except Exception as e:
                    logger.error(f"Ошибка при обработке товара {sku}: {str(e)}")
                    error_count += 1
                    continue
            
            # 6. Выполняем обновления в Wix
            updated_count = 0
            if updates:
                logger.info(f"Выполнение {len(updates)} обновлений в Wix...")
                
                # Разделяем обновления на инкременты и декременты
                increment_updates = []
                decrement_updates = []
                
                for update, is_increment in updates:
                    if is_increment:
                        increment_updates.append(update)
                    else:
                        decrement_updates.append(update)
                
                logger.info(f"Подготовлено {len(increment_updates)} инкрементов и {len(decrement_updates)} декрементов")
                
                # Выполняем групповые обновления
                try:
                    # Обновляем инкременты
                    if increment_updates:
                        logger.info(f"Выполнение {len(increment_updates)} инкрементов...")
                        wix_service.update_inventory(increment_updates, increment=True)
                        updated_count += len(increment_updates)
                        logger.info(f"Успешно выполнено {len(increment_updates)} инкрементов")
                    
                    # Обновляем декременты
                    if decrement_updates:
                        logger.info(f"Выполнение {len(decrement_updates)} декрементов...")
                        wix_service.update_inventory(decrement_updates, increment=False)
                        updated_count += len(decrement_updates)
                        logger.info(f"Успешно выполнено {len(decrement_updates)} декрементов")
                        
                except Exception as e:
                    logger.error(f"Ошибка при групповом обновлении: {str(e)}")
                    error_count += len(updates)
            else:
                logger.info("Нет товаров, требующих обновления в Wix")
            
            # 7. Формируем результат
            result = {
                "status": "success",
                "message": "Синхронизация завершена",
                "total_products": len(local_products),
                "found_in_wix": found_count,
                "updated_in_wix": updated_count,
                "errors": error_count,
                "details": {
                    "local_products_with_stock": len(local_products),
                    "wix_products_found": len(wix_products_info),
                    "updates_prepared": len(updates),
                    "updates_executed": updated_count
                }
            }
            
            logger.info(f"Синхронизация завершена: {result}")
            return result
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Критическая ошибка при синхронизации с Wix: {str(e)}")
        return {
            "status": "error",
            "message": f"Ошибка синхронизации: {str(e)}",
            "total_products": 0,
            "found_in_wix": 0,
            "updated_in_wix": 0,
            "errors": 1
        }

def launch_wix_sync():
    """
    Запускает синхронизацию количества товаров с Wix.
    
    Returns:
        celery.result.AsyncResult: Результат выполнения задачи
    """
    # Проверяем загрузку переменных Wix
    wix_api_key = os.getenv("WIX_API_KEY")
    wix_site_id = os.getenv("WIX_SITE_ID")
    wix_account_id = os.getenv("WIX_ACCOUNT_ID")
    
    logger.info(f"Wix переменные окружения:")
    logger.info(f"  WIX_API_KEY: {'Загружен' if wix_api_key else 'НЕ ЗАГРУЖЕН'}")
    logger.info(f"  WIX_SITE_ID: {'Загружен' if wix_site_id else 'НЕ ЗАГРУЖЕН'}")
    logger.info(f"  WIX_ACCOUNT_ID: {'Загружен' if wix_account_id else 'НЕ ЗАГРУЖЕН'}")
    
    if not wix_api_key or not wix_site_id:
        logger.error("Критические переменные Wix не загружены!")
        raise ValueError("Переменные WIX_API_KEY и WIX_SITE_ID должны быть установлены")
    
    result = sync_wix_inventory.delay()
    logger.info(f"Запущена синхронизация Wix с ID задачи: {result.id}")
    return result
