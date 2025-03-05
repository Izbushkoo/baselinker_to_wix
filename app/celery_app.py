import requests
import csv

from celery import Celery, chord, group, chain

from app.services import baselinker as BL
from app.services.process_funcs import transform_product
from app.schemas.wix_models import WixImportFileModel
from app.schemas.wix_models import generate_handle_id
from loggers import ToLog

import logging
import os

# Создаём или обновляем директорию для логов, если нужно
LOG_PATH = "/logs"
os.makedirs(LOG_PATH, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler(os.path.join(LOG_PATH, "celery_worker.log"), encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)
logger.info("Логирование настроено в Celery worker")

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
    worker_hijack_root_logger=False
)


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


