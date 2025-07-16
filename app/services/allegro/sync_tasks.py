"""
 * @file: sync_tasks.py
 * @description: Celery-задачи для массовой синхронизации остатков с Allegro (все аккаунты/товары, один товар по всем аккаунтам)
 * @dependencies: celery_app, AllegroToken, get_manager, Product, sync_allegro_stock_single_account, sync_allegro_stock_single_product
 * @created: 2024-06-13
"""

from app.celery_shared import celery, SessionLocal, get_allegro_token
from app.models.allegro_token import AllegroToken
from app.services.warehouse.manager import get_manager
from app.services.allegro.rate_limiter import AllegroRateLimiter
from celery import group
from sqlmodel import select
from app.services.allegro.tokens import check_token_sync
import logging
import time
import uuid
from app.services.warehouse.locks import acquire_product_sync_lock, release_product_sync_lock

@celery.task
def sync_allegro_stock_all_accounts():
    """
    Основная Celery-задача: массовая синхронизация остатков по всем аккаунтам Allegro.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info("[AllegroSync] Старт массовой синхронизации остатков по всем аккаунтам Allegro")
    results = []
    # Получаем все активные токены Allegro
    with SessionLocal() as session:
        tokens = session.exec(select(AllegroToken)).all()
    for token in tokens:
        get_allegro_token(session, token.id_)

    # Получаем все товары с is_sync_enabled=True
    inventory = get_manager()
    products = inventory.get_sync_enabled_products()
    logger.info(f"[AllegroSync] Всего активных аккаунтов: {len(tokens)}, товаров к синхронизации: {len(products)}")
    # Для каждого токена запускаем подзадачу
    subtasks = [
        sync_allegro_stock_single_account.s(token.id_, [p.sku for p in products])
        for token in tokens
    ]
    job = group(subtasks).apply_async()
    logger.info(f"[AllegroSync] Задачи по аккаунтам запущены. Время выполнения: {time.time() - start:.2f} сек")
    return {"success": True, "accounts": len(tokens), "products": len(products), "group_id": job.id}

@celery.task
def sync_allegro_stock_single_product(sku: str):
    """
    Celery-задача: синхронизация остатков одного конкретного товара по всем аккаунтам Allegro.
    Принимает SKU товара и запускает синхронизацию для всех активных аккаунтов.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт синхронизации товара {sku} по всем аккаунтам Allegro")
    results = []
    # Получаем все активные токены Allegro
    with SessionLocal() as session:
        tokens = session.exec(select(AllegroToken)).all()
    
    if not tokens:
        logger.warning(f"[AllegroSync] Нет активных токенов Allegro для товара {sku}")
        return {"success": False, "error": "Нет активных токенов Allegro", "sku": sku}
    
    # Проверяем существование товара в БД
    from app.models.warehouse import Product
    with SessionLocal() as session:
        product = session.exec(select(Product).where(Product.sku == sku)).first()
        if not product:
            logger.error(f"[AllegroSync] Товар с SKU {sku} не найден в БД")
            return {"success": False, "error": "Товар не найден", "sku": sku}
        
        if not product.is_sync_enabled:
            logger.warning(f"[AllegroSync] Синхронизация отключена для товара {sku}")
            return {"success": False, "error": "Синхронизация отключена", "sku": sku}
    
    logger.info(f"[AllegroSync] Товар {sku}: запуск синхронизации для {len(tokens)} аккаунтов")
    
    # Для каждого токена запускаем подзадачу синхронизации товара
    subtasks = [
        sync_allegro_offers_batch.s(token.id_, [sku])
        for token in tokens
    ]
    job = group(subtasks).apply_async()
    logger.info(f"[AllegroSync] Синхронизация товара {sku} запущена для всех аккаунтов. Время выполнения: {time.time() - start:.2f} сек")
    return {"success": True, "sku": sku, "accounts": len(tokens), "group_id": job.id}

@celery.task
def sync_allegro_stock_single_account(token_id: int, skus: list[str]):
    """
    Celery-задача: синхронизация остатков для одного аккаунта Allegro.
    Делит список SKU на батчи по 100 и запускает подзадачи для каждого батча.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт синхронизации аккаунта {token_id}, товаров: {len(skus)}")
    from app.models.allegro_token import AllegroToken
    from celery import group
    from sqlmodel import select
    with SessionLocal() as session:
        token = session.exec(select(AllegroToken).where(AllegroToken.id_ == token_id)).first()
        if not token:
            logger.error(f"[AllegroSync] Токен с id={token_id} не найден")
            return {"success": False, "error": "Токен не найден", "token_id": token_id}
        # Разбиваем на батчи по 100 SKU
        batch_size = 100
        batches = [skus[i:i+batch_size] for i in range(0, len(skus), batch_size)]
        logger.info(f"[AllegroSync] Аккаунт {token.account_name}: {len(batches)} батчей для синхронизации")
        # Запускаем подзадачи для каждого батча
        subtasks = [
            sync_allegro_offers_batch.s(token_id, batch)
            for batch in batches
        ]
        job = group(subtasks).apply_async()
    logger.info(f"[AllegroSync] Синхронизация аккаунта {token_id} завершена. Время: {time.time() - start:.2f} сек")
    return {"success": True, "token_id": token_id, "batches": len(batches), "group_id": job.id}

@celery.task
def sync_allegro_offers_batch(token_id: int, skus: list[str]):
    """
    Celery-задача: обработка батча SKU для одного аккаунта Allegro.
    Получает офферы по external.id, сравнивает остатки, запускает задачи на обновление офферов.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт батча для аккаунта {token_id}, SKU: {skus}")
    from app.models.allegro_token import AllegroToken
    from app.models.warehouse import Product
    from app.services.allegro.allegro_api_service import SyncAllegroApiService
    from app.celery_app import SessionLocal
    from sqlmodel import select
    with SessionLocal() as session:
        token = session.exec(select(AllegroToken).where(AllegroToken.id_ == token_id)).first()
        if not token:
            logger.error(f"[AllegroSync] Токен с id={token_id} не найден (batch)")
            return {"success": False, "error": "Токен не найден", "token_id": token_id}
        # Получаем товары из БД по SKU
        products = session.exec(select(Product).where(Product.sku.in_(skus))).all()
        sku_to_product = {p.sku: p for p in products}

    allegro_api = SyncAllegroApiService()
    # Получаем офферы по external.id (SKU)
    try:
        offers_response = allegro_api.get_offers(token.access_token, external_ids=skus)
        logger.debug(f"[AllegroSync] Полный ответ API: {offers_response}")
        
        # Извлекаем список офферов из ответа API
        offers = offers_response.get("offers", []) if isinstance(offers_response, dict) else []
        
        logger.info(f"[AllegroSync] Получено офферов для аккаунта {token.account_name}: {len(offers)}")
        logger.debug(f"[AllegroSync] Тип данных offers: {type(offers)}")
        if offers:
            logger.debug(f"[AllegroSync] Первый элемент offers: {offers[0]} (тип: {type(offers[0])})")
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка получения офферов для аккаунта {token.account_name}: {e}")
        return {"success": False, "error": str(e), "token_id": token_id, "skus": skus}
    # Сопоставляем офферы и товары, сравниваем остатки
    subtasks = []
    updated = 0
    
    # Проверяем тип данных offers
    if not offers:
        logger.warning(f"[AllegroSync] Нет офферов для обработки в аккаунте {token.account_name}")
        return {"success": True, "token_id": token_id, "skus": skus, "offers_to_update": 0, "group_id": None}
    
    if not isinstance(offers, list):
        logger.error(f"[AllegroSync] Неожиданный тип данных offers: {type(offers)}, содержимое: {offers}")
        return {"success": False, "error": f"Неожиданный тип данных offers: {type(offers)}", "token_id": token_id, "skus": skus}
    
    for i, offer in enumerate(offers):
        logger.debug(f"[AllegroSync] Обработка оффера {i+1}/{len(offers)}: {offer} (тип: {type(offer)})")
        
        # Проверяем, что offer - это словарь
        if not isinstance(offer, dict):
            logger.error(f"[AllegroSync] Оффер {i+1} не является словарем: {offer} (тип: {type(offer)})")
            continue
        
        sku = offer.get("external", {}).get("id")
        if not sku:
            logger.warning(f"[AllegroSync] Оффер {i+1} не содержит external.id: {offer}")
            continue
            
        if sku not in sku_to_product:
            logger.debug(f"[AllegroSync] SKU {sku} не найден в списке товаров для синхронизации")
            continue
            
        product = sku_to_product[sku]
        current_stock = offer.get("stock", {}).get("available")
        
        # Получаем актуальный остаток товара
        inventory = get_manager()
        stock_by_warehouse = inventory.get_stock_by_sku(sku)
        target_stock = sum(stock_by_warehouse.values()) if stock_by_warehouse else 0
        
        logger.debug(f"[AllegroSync] SKU {sku}: остатки по складам={stock_by_warehouse}, общий остаток={target_stock}, текущий остаток в Allegro={current_stock}")
        
        if current_stock == target_stock:
            logger.debug(f"[AllegroSync] SKU {sku}: обновление не требуется")
            continue  # Не требуется обновление
        
        # Запускаем задачу на обновление оффера
        offer_id = offer.get("id")
        if not offer_id:
            logger.error(f"[AllegroSync] Оффер для SKU {sku} не содержит ID: {offer}")
            continue
            
        subtasks.append(update_single_allegro_offer.s(token_id, offer_id, target_stock, sku))
        updated += 1
        logger.info(f"[AllegroSync] Запланировано обновление оффера {offer_id} для SKU {sku}: {current_stock} -> {target_stock}")
    if subtasks:
        job = group(subtasks).apply_async()
        group_id = job.id
    else:
        group_id = None
    logger.info(f"[AllegroSync] Батч аккаунта {token_id} завершён. Офферов к обновлению: {updated}, время: {time.time() - start:.2f} сек")
    return {"success": True, "token_id": token_id, "skus": skus, "offers_to_update": updated, "group_id": group_id}

@celery.task(bind=True, max_retries=3, default_retry_delay=10)
def update_single_allegro_offer(self, token_id: int, offer_id: str, target_stock: int, sku: str):
    """
    Celery-задача: обновление оффера через PATCH /sale/offers/{offerId} с учетом лимита, retry и уведомлением в Telegram при неудаче.
    """
    from app.models.allegro_token import AllegroToken
    from app.services.allegro.allegro_api_service import SyncAllegroApiService
    from app.services.allegro.rate_limiter import AllegroRateLimiter
    from app.celery_app import SessionLocal
    from sqlmodel import select
    from app.services.tg_client import TelegramManager
    import logging
    import time
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    owner_id = str(uuid.uuid4())
    # Попытка установить лок
    if not acquire_product_sync_lock(sku, owner_id):
        logger.warning(f"[AllegroSync] Лок на SKU {sku} уже активен, задача не будет выполнена (offer_id={offer_id})")
        return {"success": False, "offer_id": offer_id, "sku": sku, "error": "Lock already active"}
    try:
        with SessionLocal() as session:
            token = session.exec(select(AllegroToken).where(AllegroToken.id_ == token_id)).first()
            if not token:
                logger.error(f"[AllegroSync] Токен с id={token_id} не найден (update)")
                release_product_sync_lock(sku, owner_id, status="error", error="Token not found")
                return {"success": False, "offer_id": offer_id, "sku": sku, "error": "Token not found"}
        limiter = AllegroRateLimiter()
        if not limiter.acquire(timeout=10):
            logger.warning(f"[AllegroSync] Rate limit exceeded для аккаунта {token.account_name}, offer {offer_id}")
            release_product_sync_lock(sku, owner_id, status="error", error="Rate limit exceeded")
            self.retry(countdown=10)
            return {"success": False, "offer_id": offer_id, "sku": sku, "error": "Rate limit exceeded"}
        allegro_api = SyncAllegroApiService()
        allegro_api.update_offer_stock(token.access_token, offer_id, target_stock)
        logger.info(f"[AllegroSync] Обновлен оффер {offer_id} (stock={target_stock}) для аккаунта {token.account_name}. Время: {time.time() - start:.2f} сек")
        release_product_sync_lock(sku, owner_id, status="success")
        return {"success": True, "offer_id": offer_id, "sku": sku, "stock": target_stock}
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка обновления оффера {offer_id} для аккаунта {token.account_name}: {e}")
        release_product_sync_lock(sku, owner_id, status="error", error=str(e))
        if self.request.retries >= self.max_retries:
            msg = (
                f"❗️ Ошибка обновления оффера Allegro\n"
                f"Аккаунт: {token.account_name}\n"
                f"Offer ID: {offer_id}\n"
                f"SKU: {sku}\n"
                f"Stock: {target_stock}\n"
                f"Ошибка: {e}"
            )
            try:
                TelegramManager().send_message(msg)
                logger.info(f"[AllegroSync] Уведомление отправлено в Telegram для оффера {offer_id}")
            except Exception as tg_err:
                logger.error(f"[AllegroSync] Ошибка отправки уведомления в Telegram: {tg_err}")
        self.retry(exc=e)
        return {"success": False, "offer_id": offer_id, "sku": sku, "error": str(e)} 