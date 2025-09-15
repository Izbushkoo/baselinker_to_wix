"""
 * @file: sync_tasks.py
 * @description: Celery-задачи для массовой синхронизации остатков с Allegro через микросервис
 * @dependencies: celery_app, микросервис Allegro, get_manager, Product, sync_allegro_stock_single_account, sync_allegro_stock_single_product
 * @created: 2024-06-13
 * @updated: 2024-12-19 - Рефакторинг для использования микросервиса Allegro
"""

from app.celery_shared import celery, SessionLocal, get_celery_session
from app.services.warehouse.manager import get_manager
from app.services.product_allegro_sync_service import get_sync_service
from app.services.Allegro_Microservice import AllegroTokenMicroserviceClient, AllegroOffersMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings
from celery import group
from sqlmodel import select
import logging
import time
import uuid
from typing import List, Dict, Any, Optional
from uuid import UUID
from app.services.warehouse.locks import acquire_product_sync_lock, release_product_sync_lock

# ===============================================
# Вспомогательные функции для работы с микросервисом
# ===============================================

def get_microservice_jwt_token() -> str:
    """
    Создает JWT токен для аутентификации в микросервисе Allegro.
    """
    return create_access_token(user_id=settings.PROJECT_NAME)

def get_active_tokens_from_microservice() -> List[Dict[str, Any]]:
    """
    Получает список активных токенов из микросервиса Allegro.
    
    Returns:
        List[Dict[str, Any]]: Список активных токенов с полями id, account_name, user_id
    """
    try:
        jwt_token = get_microservice_jwt_token()
        token_client = AllegroTokenMicroserviceClient(jwt_token=jwt_token)
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if not tokens_response.items:
            return []
        
        # Преобразуем токены в нужный формат
        tokens = []
        for token_data in tokens_response.items:
            tokens.append({
                'id': token_data['id'],
                'account_name': token_data['account_name'],
                'user_id': token_data['user_id']
            })
        
        return tokens
    except Exception as e:
        logger = logging.getLogger("allegro.sync")
        logger.error(f"[AllegroSync] Ошибка получения токенов из микросервиса: {e}")
        return []

def get_offers_from_microservice(token_ids: List[UUID], external_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Получает офферы из микросервиса Allegro по external_ids.
    
    Args:
        token_ids: Список ID токенов
        external_ids: Список external_id (SKU)
        
    Returns:
        List[Dict[str, Any]]: Список офферов
    """
    logger = logging.getLogger("allegro.sync")
    logger.info(f"[AllegroSync] Запрос офферов из микросервиса: token_ids={token_ids}, external_ids={external_ids}")
    
    try:
        jwt_token = get_microservice_jwt_token()
        offers_client = AllegroOffersMicroserviceClient(jwt_token=jwt_token)
        
        # Разбиваем на батчи по 100 SKU (лимит микросервиса)
        batch_size = 100
        all_offers = []
        
        for i in range(0, len(external_ids), batch_size):
            batch_external_ids = external_ids[i:i + batch_size]
            logger.info(f"[AllegroSync] Запрос батча {i//batch_size + 1}: external_ids={batch_external_ids}")
            
            response = offers_client.get_offers_by_external_ids(token_ids, batch_external_ids)
            
            # Проверяем структуру ответа
            logger.info(f"[AllegroSync] Структура ответа микросервиса: {type(response)}")
            logger.info(f"[AllegroSync] Содержимое ответа микросервиса: {response}")
            
            if hasattr(response, 'offers'):
                offers_list = response.offers
                logger.info(f"[AllegroSync] Извлечены офферы через response.offers: {len(offers_list) if offers_list else 0}")
            elif isinstance(response, dict) and 'offers' in response:
                offers_list = response['offers']
                logger.info(f"[AllegroSync] Извлечены офферы через response['offers']: {len(offers_list) if offers_list else 0}")
            else:
                logger.error(f"[AllegroSync] Неожиданная структура ответа микросервиса: {response}")
                offers_list = []
            
            logger.info(f"[AllegroSync] Ответ микросервиса для батча {i//batch_size + 1}: найдено офферов={len(offers_list) if offers_list else 0}")
            
            if offers_list:
                logger.debug(f"[AllegroSync] Офферы из батча {i//batch_size + 1}: {[offer.get('external', {}).get('id', 'NO_EXTERNAL_ID') for offer in offers_list]}")
                all_offers.extend(offers_list)
            else:
                logger.warning(f"[AllegroSync] Микросервис вернул пустой список офферов для батча {i//batch_size + 1}")
        
        logger.info(f"[AllegroSync] Итого получено офферов из микросервиса: {len(all_offers)}")
        return all_offers
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка получения офферов из микросервиса: {e}")
        return []

def update_offer_stock_via_microservice(token_id: UUID, external_id: str, stock: int) -> bool:
    """
    Обновляет остаток оффера через микросервис Allegro.
    
    Args:
        token_id: ID токена
        external_id: External ID оффера (SKU)
        stock: Новый остаток
        
    Returns:
        bool: True если обновление успешно
    """
    logger = logging.getLogger("allegro.sync")
    try:
        jwt_token = get_microservice_jwt_token()
        offers_client = AllegroOffersMicroserviceClient(jwt_token=jwt_token)
        
        response = offers_client.update_stock_single(token_id, external_id, stock)
        logger.info(f"[AllegroSync] Response: {response}")
        return response.success
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка обновления остатка оффера {external_id}: {e}")
        return False

def update_offer_price_via_microservice(token_id: UUID, offer_id: str, price: float, currency: str = "PLN") -> bool:
    """
    Обновляет цену оффера через микросервис Allegro.
    
    Args:
        token_id: ID токена
        offer_id: ID оффера
        price: Новая цена
        currency: Валюта (по умолчанию PLN)
        
    Returns:
        bool: True если обновление успешно
    """
    try:
        jwt_token = get_microservice_jwt_token()
        offers_client = AllegroOffersMicroserviceClient(jwt_token=jwt_token)
        
        response = offers_client.update_offer_price(token_id, offer_id, price, currency)
        return response.success
    except Exception as e:
        logger = logging.getLogger("allegro.sync")
        logger.error(f"[AllegroSync] Ошибка обновления цены оффера {offer_id}: {e}")
        return False

# ===============================================
# Celery задачи
# ===============================================

@celery.task
def sync_allegro_stock_all_accounts():
    """
    Основная Celery-задача: массовая синхронизация остатков по всем аккаунтам Allegro через микросервис.
    Для каждого аккаунта запускает синхронизацию только тех товаров, для которых
    включена синхронизация остатков в настройках ProductAllegroSyncSettings.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info("[AllegroSync] Старт массовой синхронизации остатков по всем аккаунтам Allegro через микросервис")
    
    # Получаем все активные токены из микросервиса
    tokens = get_active_tokens_from_microservice()
    
    if not tokens:
        logger.warning("[AllegroSync] Нет активных токенов Allegro для синхронизации")
        return {"success": False, "error": "Нет активных токенов Allegro", "accounts": 0, "products": 0}
    
    logger.info(f"[AllegroSync] Всего активных аккаунтов: {len(tokens)}")
    
    # Для каждого токена запускаем подзадачу с пустым списком SKU
    # Функция sync_allegro_stock_single_account сама получит товары с включенной синхронизацией
    subtasks = [
        sync_allegro_stock_single_account.s(token['id'], [])
        for token in tokens
    ]
    job = group(subtasks).apply_async()
    
    logger.info(f"[AllegroSync] Задачи по аккаунтам запущены. Время выполнения: {time.time() - start:.2f} сек")
    return {"success": True, "accounts": len(tokens), "group_id": job.id}

@celery.task
def sync_allegro_stock_all_accounts_force():
    """
    Celery-задача: принудительная массовая синхронизация остатков по всем аккаунтам Allegro через микросервис.
    ИГНОРИРУЕТ флаг включения синхронизации остатков в настройках ProductAllegroSyncSettings.
    Синхронизирует ВСЕ товары для всех активных аккаунтов.
    
    ВНИМАНИЕ: Эта задача может быть ресурсоемкой и должна использоваться только в исключительных случаях.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info("[AllegroSync] Старт ПРИНУДИТЕЛЬНОЙ массовой синхронизации остатков по всем аккаунтам Allegro через микросервис")
    logger.warning("[AllegroSync] ВНИМАНИЕ: Игнорируется флаг включения синхронизации остатков!")
    
    # Получаем все активные токены из микросервиса
    tokens = get_active_tokens_from_microservice()
    
    if not tokens:
        logger.warning("[AllegroSync] Нет активных токенов Allegro для принудительной синхронизации")
        return {"success": False, "error": "Нет активных токенов Allegro", "accounts": 0, "products": 0}
    
    logger.info(f"[AllegroSync] Всего активных аккаунтов для принудительной синхронизации: {len(tokens)}")
    
    # Для каждого токена запускаем подзадачу с флагом принудительной синхронизации
    subtasks = [
        sync_allegro_stock_single_account_force.s(token['id'])
        for token in tokens
    ]
    job = group(subtasks).apply_async()
    
    logger.info(f"[AllegroSync] Принудительные задачи по аккаунтам запущены. Время выполнения: {time.time() - start:.2f} сек")
    return {"success": True, "accounts": len(tokens), "group_id": job.id, "force_mode": True}

@celery.task
def sync_allegro_stock_single_account_force(token_id: str):
    """
    Celery-задача: принудительная синхронизация остатков для одного аккаунта Allegro через микросервис.
    ИГНОРИРУЕТ флаг включения синхронизации остатков и синхронизирует ВСЕ товары для данного аккаунта.
    
    ВНИМАНИЕ: Эта задача может быть ресурсоемкой и должна использоваться только в исключительных случаях.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт ПРИНУДИТЕЛЬНОЙ синхронизации аккаунта {token_id} через микросервис")
    logger.warning(f"[AllegroSync] ВНИМАНИЕ: Игнорируется флаг включения синхронизации остатков для аккаунта {token_id}!")
    
    # Получаем информацию о токене из микросервиса
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['id'] == token_id:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен с id={token_id} не найден в микросервисе")
        return {"success": False, "error": "Токен не найден", "token_id": token_id}
    
    account_name = token_info['account_name']
    
    with SessionLocal() as session:
        # Получаем сервис синхронизации
        sync_service = get_sync_service(session)
        
        # ПРИНУДИТЕЛЬНО получаем ВСЕ товары с настройками для данного аккаунта
        # независимо от флага включения синхронизации остатков
        all_settings = sync_service.get_all_account_settings_sync(account_name)
        skus_to_sync = [setting.product_sku for setting in all_settings]
        
        logger.info(f"[AllegroSync] Аккаунт {account_name} (ПРИНУДИТЕЛЬНО): товаров для синхронизации - {len(skus_to_sync)}")
        logger.info(f"[AllegroSync] Список SKU для синхронизации: {skus_to_sync}")
        logger.warning(f"[AllegroSync] ВНИМАНИЕ: Синхронизируются ВСЕ товары аккаунта {account_name}, включая те, у которых отключена синхронизация остатков!")
        
        if not skus_to_sync:
            logger.warning(f"[AllegroSync] Нет товаров с настройками для аккаунта {account_name}")
            return {"success": True, "token_id": token_id, "batches": 0, "group_id": None, "force_mode": True}
        
        # Разбиваем на батчи по 100 SKU
        batch_size = 100
        batches = [skus_to_sync[i:i+batch_size] for i in range(0, len(skus_to_sync), batch_size)]
        logger.info(f"[AllegroSync] Аккаунт {account_name} (ПРИНУДИТЕЛЬНО): {len(batches)} батчей для синхронизации")
        
        # Запускаем подзадачи для каждого батча в принудительном режиме
        subtasks = [
            sync_allegro_offers_batch.s(token_id, batch, True)  # force_mode=True
            for batch in batches
        ]
        job = group(subtasks).apply_async()
        
    logger.info(f"[AllegroSync] ПРИНУДИТЕЛЬНАЯ синхронизация аккаунта {token_id} завершена. Время: {time.time() - start:.2f} сек")
    return {"success": True, "token_id": token_id, "batches": len(batches), "group_id": job.id, "force_mode": True}

@celery.task
def sync_allegro_stock_single_product(sku: str):
    """
    Celery-задача: синхронизация остатков одного конкретного товара по всем аккаунтам Allegro через микросервис.
    Принимает SKU товара и запускает синхронизацию для всех активных аккаунтов,
    где включена синхронизация остатков для данного товара.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт синхронизации товара {sku} по всем аккаунтам Allegro через микросервис")
    
    # Получаем все активные токены из микросервиса
    tokens = get_active_tokens_from_microservice()
    
    if not tokens:
        logger.warning(f"[AllegroSync] Нет активных токенов Allegro для товара {sku}")
        return {"success": False, "error": "Нет активных токенов Allegro", "sku": sku}
    
    # Проверяем существование товара в БД
    from app.models.warehouse import Product
    with get_celery_session() as session:
        product = session.exec(select(Product).where(Product.sku == sku)).first()
        if not product:
            logger.error(f"[AllegroSync] Товар с SKU {sku} не найден в БД")
            return {"success": False, "error": "Товар не найден", "sku": sku}
        
        # Получаем сервис синхронизации и проверяем настройки для каждого аккаунта
        sync_service = get_sync_service(session)
        tokens_to_sync = []
        
        for token in tokens:
            # Проверяем настройки синхронизации для данного товара и аккаунта
            if sync_service.should_sync_product_sync(sku, token['account_name'], "stock"):
                tokens_to_sync.append(token)
                logger.debug(f"[AllegroSync] Товар {sku}: синхронизация включена для аккаунта {token['account_name']}")
            else:
                logger.debug(f"[AllegroSync] Товар {sku}: синхронизация отключена для аккаунта {token['account_name']}")
    
    if not tokens_to_sync:
        logger.warning(f"[AllegroSync] Нет аккаунтов с включенной синхронизацией для товара {sku}")
        return {"success": False, "error": "Нет аккаунтов с включенной синхронизацией", "sku": sku}
    
    logger.info(f"[AllegroSync] Товар {sku}: запуск синхронизации для {len(tokens_to_sync)} аккаунтов из {len(tokens)} доступных")
    
    # Для каждого токена с включенной синхронизацией запускаем подзадачу синхронизации товара
    subtasks = [
        sync_allegro_offers_batch.s(token['id'], [sku])
        for token in tokens_to_sync
    ]
    job = group(subtasks).apply_async()
    logger.info(f"[AllegroSync] Синхронизация товара {sku} запущена для {len(tokens_to_sync)} аккаунтов. Время выполнения: {time.time() - start:.2f} сек")
    return {"success": True, "sku": sku, "accounts": len(tokens_to_sync), "total_accounts": len(tokens), "group_id": job.id}

@celery.task
def sync_allegro_stock_single_account(token_id: str, skus: list[str]):
    """
    Celery-задача: синхронизация остатков для одного аккаунта Allegro через микросервис.
    Получает товары с включенной синхронизацией остатков для данного аккаунта,
    делит список SKU на батчи по 100 и запускает подзадачи для каждого батча.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт синхронизации аккаунта {token_id} через микросервис")
    
    # Получаем информацию о токене из микросервиса
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['id'] == token_id:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен с id={token_id} не найден в микросервисе")
        return {"success": False, "error": "Токен не найден", "token_id": token_id}
    
    account_name = token_info['account_name']
    
    with SessionLocal() as session:
        # Получаем сервис синхронизации
        sync_service = get_sync_service(session)
        
        # Если передан список SKU, фильтруем его по настройкам синхронизации
        if skus:
            filtered_skus = []
            for sku in skus:
                if sync_service.should_sync_product_sync(sku, account_name, "stock"):
                    filtered_skus.append(sku)
                    logger.debug(f"[AllegroSync] SKU {sku}: синхронизация включена для аккаунта {account_name}")
                else:
                    logger.debug(f"[AllegroSync] SKU {sku}: синхронизация отключена для аккаунта {account_name}")
            skus_to_sync = filtered_skus
        else:
            # Если список SKU не передан, получаем все товары с включенной синхронизацией для данного аккаунта
            sync_settings = sync_service.get_products_for_stock_sync_sync(account_name)
            skus_to_sync = [setting.product_sku for setting in sync_settings]
        
        logger.info(f"[AllegroSync] Аккаунт {account_name}: товаров для синхронизации - {len(skus_to_sync)}")
        
        if not skus_to_sync:
            logger.warning(f"[AllegroSync] Нет товаров для синхронизации для аккаунта {account_name}")
            return {"success": True, "token_id": token_id, "batches": 0, "group_id": None}
        
        # Разбиваем на батчи по 100 SKU
        batch_size = 100
        batches = [skus_to_sync[i:i+batch_size] for i in range(0, len(skus_to_sync), batch_size)]
        logger.info(f"[AllegroSync] Аккаунт {account_name}: {len(batches)} батчей для синхронизации")
        
        # Запускаем подзадачи для каждого батча
        subtasks = [
            sync_allegro_offers_batch.s(token_id, batch)
            for batch in batches
        ]
        job = group(subtasks).apply_async()
        
    logger.info(f"[AllegroSync] Синхронизация аккаунта {token_id} завершена. Время: {time.time() - start:.2f} сек")
    return {"success": True, "token_id": token_id, "batches": len(batches), "group_id": job.id}

@celery.task
def sync_allegro_stock_single_product_account(sku: str, account_name: str):
    """
    Celery-задача: синхронизация остатков конкретного товара с конкретным аккаунтом Allegro через микросервис.
    Используется при переключении настроек синхронизации.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт синхронизации товара {sku} для аккаунта {account_name} через микросервис")
    
    # Получаем информацию о токене из микросервиса
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['account_name'] == account_name:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен для аккаунта {account_name} не найден в микросервисе")
        return {"success": False, "error": "Токен не найден", "account_name": account_name}
    
    token_id = token_info['id']
    
    with SessionLocal() as session:
        # Получаем сервис синхронизации
        sync_service = get_sync_service(session)
        
        # Проверяем, включена ли синхронизация остатков для данного товара и аккаунта
        if not sync_service.should_sync_product_sync(sku, account_name, "stock"):
            logger.info(f"[AllegroSync] Синхронизация остатков для товара {sku} и аккаунта {account_name} отключена")
            return {"success": False, "error": "Синхронизация остатков отключена", "sku": sku, "account_name": account_name}
        
    # Запускаем синхронизацию через существующую задачу
    result = sync_allegro_offers_batch.apply_async(args=[token_id, [sku]])
    
    logger.info(f"[AllegroSync] Синхронизация товара {sku} для аккаунта {account_name} запущена. Время: {time.time() - start:.2f} сек")
    return {"success": True, "sku": sku, "account_name": account_name, "token_id": token_id, "task_id": result.id}

@celery.task
def sync_allegro_price_single_product_account(sku: str, account_name: str):
    """
    Celery-задача: синхронизация цен конкретного товара с конкретным аккаунтом Allegro через микросервис.
    Используется при переключении настроек синхронизации цен.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт синхронизации цены товара {sku} для аккаунта {account_name} через микросервис")
    
    # Получаем информацию о токене из микросервиса
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['account_name'] == account_name:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен для аккаунта {account_name} не найден в микросервисе")
        return {"success": False, "error": "Токен не найден", "account_name": account_name}
    
    token_id = token_info['id']
    
    from app.models.warehouse import Product
    from decimal import Decimal
    
    with SessionLocal() as session:
        # Получаем сервис синхронизации
        sync_service = get_sync_service(session)
        
        # Проверяем, включена ли синхронизация цен для данного товара и аккаунта
        if not sync_service.should_sync_product_sync(sku, account_name, "price"):
            logger.info(f"[AllegroSync] Синхронизация цен для товара {sku} и аккаунта {account_name} отключена")
            return {"success": False, "error": "Синхронизация цен отключена", "sku": sku, "account_name": account_name}
        
        # Получаем товар из БД
        product = session.exec(select(Product).where(Product.sku == sku)).first()
        if not product:
            logger.error(f"[AllegroSync] Товар с SKU {sku} не найден в БД")
            return {"success": False, "error": "Товар не найден", "sku": sku}
        
        # Получаем цену товара из сервиса цен
        from app.services.prices_service import prices_service
        price_data = prices_service.get_price_by_sku(sku)
        if not price_data or price_data.min_price <= 0:
            logger.warning(f"[AllegroSync] У товара {sku} не указана минимальная цена")
            return {"success": False, "error": "Минимальная цена не указана", "sku": sku}
        
        # Получаем мультипликатор цены для данного аккаунта
        sync_settings = sync_service.get_account_sync_settings_sync(sku, account_name)
        price_multiplier = sync_settings.price_multiplier if sync_settings else Decimal("1.0")
        
        # Рассчитываем итоговую цену в PLN
        base_price_pln = price_data.min_price
        final_price_pln = base_price_pln * price_multiplier
        
        logger.info(f"[AllegroSync] Товар {sku}: базовая цена {base_price_pln} PLN, мультипликатор {price_multiplier}, итоговая цена {final_price_pln} PLN")
    
    try:
        # Получаем офферы через микросервис
        offers = get_offers_from_microservice([UUID(token_id)], [sku])
        
        if not offers:
            logger.warning(f"[AllegroSync] Оффер для SKU {sku} не найден в аккаунте {account_name}")
            return {"success": False, "error": "Оффер не найден", "sku": sku, "account_name": account_name}
        
        logger.info(f"[AllegroSync] Найдено {len(offers)} офферов для SKU {sku} в аккаунте {account_name}")
        
        # Обрабатываем каждый найденный оффер
        updated_offers = []
        skipped_offers = []
        
        for offer in offers:
            offer_id = offer.get("id")
            
            # Получаем текущую цену и валюту оффера
            current_price_info = offer.get("sellingMode", {}).get("price", {})
            current_currency = current_price_info.get("currency", "PLN")
            current_amount = current_price_info.get("amount", "0")
            
            logger.info(f"[AllegroSync] Текущая цена оффера {offer_id}: {current_amount} {current_currency}")
            
            # Всегда используем PLN
            target_price = final_price_pln
            target_currency = "PLN"
            
            # Сравниваем цены
            current_price_decimal = Decimal(current_amount)
            if abs(current_price_decimal - target_price) < Decimal("0.01"):  # Разница менее 1 цента
                logger.info(f"[AllegroSync] Цена оффера {offer_id} актуальна: {current_amount} {current_currency}")
                skipped_offers.append({"offer_id": offer_id, "reason": "Price up to date"})
                continue
            
            # Обновляем цену оффера через микросервис
            formatted_price = float(target_price)
            
            # Логируем данные перед отправкой в API
            logger.info(f"[AllegroSync] Отправка запроса на обновление цены: offer_id={offer_id}, price={formatted_price}, currency={target_currency}")
            
            success = update_offer_price_via_microservice(UUID(token_id), offer_id, formatted_price, target_currency)
            
            if success:
                logger.info(f"[AllegroSync] Цена оффера {offer_id} обновлена: {current_amount} -> {formatted_price} {target_currency}")
                updated_offers.append({
                    "offer_id": offer_id,
                    "old_price": current_amount,
                    "new_price": str(formatted_price),
                    "currency": target_currency
                })
            else:
                logger.error(f"[AllegroSync] Ошибка обновления цены оффера {offer_id}")
                skipped_offers.append({"offer_id": offer_id, "reason": "Update failed"})
        
        # Если ни один оффер не был обновлен
        if not updated_offers:
            logger.info(f"[AllegroSync] Все офферы для SKU {sku} имеют актуальные цены")
            return {"success": True, "sku": sku, "account_name": account_name, "updated": False, "reason": "All prices up to date", "offers_processed": len(offers)}
        
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка синхронизации цены товара {sku} для аккаунта {account_name}: {e}")
        return {"success": False, "error": str(e), "sku": sku, "account_name": account_name}
    
    logger.info(f"[AllegroSync] Синхронизация цены товара {sku} для аккаунта {account_name} завершена. Время: {time.time() - start:.2f} сек")
    return {
        "success": True, 
        "sku": sku, 
        "account_name": account_name, 
        "updated": True, 
        "updated_offers": updated_offers,
        "skipped_offers": skipped_offers,
        "offers_processed": len(offers)
    }

@celery.task
def sync_allegro_offers_batch(token_id: str, skus: list[str], force_mode: bool = False):
    """
    Celery-задача: обработка батча SKU для одного аккаунта Allegro через микросервис.
    Получает офферы по external.id, проверяет настройки синхронизации (если не в принудительном режиме),
    сравнивает остатки, запускает задачи на обновление офферов.
    
    Args:
        token_id: ID токена Allegro
        skus: Список SKU для синхронизации
        force_mode: Если True, игнорирует настройки синхронизации
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт батча для аккаунта {token_id}, SKU: {skus} через микросервис")
    
    # Получаем информацию о токене из микросервиса
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['id'] == token_id:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен с id={token_id} не найден в микросервисе (batch)")
        return {"success": False, "error": "Токен не найден", "token_id": token_id}
    
    account_name = token_info['account_name']
    
    from app.models.warehouse import Product
    
    with SessionLocal() as session:
        # Получаем товары из БД по SKU и проверяем настройки синхронизации
        logger.info(f"[AllegroSync] Поиск товаров в локальной БД по SKU: {skus}")
        products = session.exec(select(Product).where(Product.sku.in_(skus))).all()
        sku_to_product = {p.sku: p for p in products}
        
        logger.info(f"[AllegroSync] Найдено товаров в локальной БД: {len(products)} из {len(skus)}")
        for sku in skus:
            try:
                if sku in sku_to_product:
                    product = sku_to_product[sku]
                    # Безопасное логирование названия товара
                    product_name = str(product.name)[:50] + "..." if len(str(product.name)) > 50 else str(product.name)
                    logger.info(f"[AllegroSync] Товар {sku}: найден в БД (SKU: {product.sku}, название: {product_name})")
                else:
                    logger.warning(f"[AllegroSync] Товар {sku}: НЕ НАЙДЕН в локальной БД")
            except Exception as e:
                logger.error(f"[AllegroSync] Ошибка при логировании товара {sku}: {e}")
        
        # Получаем сервис синхронизации
        sync_service = get_sync_service(session)
        
        # Фильтруем SKU по настройкам синхронизации (если не в принудительном режиме)
        filtered_skus = []
        
        if force_mode:
            logger.info(f"[AllegroSync] ПРИНУДИТЕЛЬНЫЙ РЕЖИМ: игнорируем настройки синхронизации для {len(skus)} товаров в аккаунте {account_name}")
            # В принудительном режиме синхронизируем все товары, которые есть в локальной БД
            for sku in skus:
                if sku in sku_to_product:
                    filtered_skus.append(sku)
                    logger.info(f"[AllegroSync] SKU {sku}: принудительная синхронизация для аккаунта {account_name}")
                else:
                    logger.warning(f"[AllegroSync] SKU {sku}: товар НЕ НАЙДЕН в локальной базе данных")
        else:
            logger.info(f"[AllegroSync] Проверка настроек синхронизации для {len(skus)} товаров в аккаунте {account_name}")
            
            for sku in skus:
                try:
                    if sku in sku_to_product:
                        should_sync = sync_service.should_sync_product_sync(sku, account_name, "stock")
                        if should_sync:
                            filtered_skus.append(sku)
                            logger.info(f"[AllegroSync] SKU {sku}: синхронизация ВКЛЮЧЕНА для аккаунта {account_name}")
                        else:
                            logger.info(f"[AllegroSync] SKU {sku}: синхронизация ОТКЛЮЧЕНА для аккаунта {account_name}")
                    else:
                        logger.warning(f"[AllegroSync] SKU {sku}: товар НЕ НАЙДЕН в локальной базе данных")
                except Exception as e:
                    logger.error(f"[AllegroSync] Ошибка при проверке настроек синхронизации для SKU {sku}: {e}")
        
        logger.info(f"[AllegroSync] Результат фильтрации: {len(filtered_skus)} из {len(skus)} товаров будут синхронизированы")
        
        if not filtered_skus:
            logger.warning(f"[AllegroSync] Нет товаров для синхронизации в батче для аккаунта {account_name}")
            return {"success": True, "token_id": token_id, "skus": skus, "offers_to_update": 0, "group_id": None}
        
        logger.info(f"[AllegroSync] Батч аккаунта {account_name}: {len(filtered_skus)} из {len(skus)} товаров будут синхронизированы")
    
    # Получаем офферы через микросервис
    try:
        offers = get_offers_from_microservice([UUID(token_id)], filtered_skus)
        
        logger.info(f"[AllegroSync] Получено офферов для аккаунта {account_name}: {len(offers)}")
        logger.debug(f"[AllegroSync] Тип данных offers: {type(offers)}")
        if offers:
            logger.debug(f"[AllegroSync] Первый элемент offers: {offers[0]} (тип: {type(offers[0])})")
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка получения офферов для аккаунта {account_name}: {e}")
        return {"success": False, "error": str(e), "token_id": token_id, "skus": skus}
    
    # Сопоставляем офферы и товары, сравниваем остатки
    subtasks = []
    updated = 0
    
    # Проверяем тип данных offers
    if not offers:
        logger.warning(f"[AllegroSync] Нет офферов для обработки в аккаунте {account_name}")
        return {"success": True, "token_id": token_id, "skus": skus, "offers_to_update": 0, "group_id": None}
    
    if not isinstance(offers, list):
        logger.error(f"[AllegroSync] Неожиданный тип данных offers: {type(offers)}, содержимое: {offers}")
        return {"success": False, "error": f"Неожиданный тип данных offers: {type(offers)}", "token_id": token_id, "skus": skus}
    
    for i, offer_response in enumerate(offers):
        logger.info(f"[AllegroSync] Обработка ответа микросервиса {i+1}/{len(offers)}: {offer_response} (тип: {type(offer_response)})")
        
        # Проверяем, что это ответ микросервиса с офферами
        if not isinstance(offer_response, dict):
            logger.error(f"[AllegroSync] Ответ {i+1} не является словарем: {offer_response} (тип: {type(offer_response)})")
            continue
        
        # Извлекаем массив офферов из ответа микросервиса
        offers_list = offer_response.get("offers", [])
        if not offers_list:
            logger.warning(f"[AllegroSync] Ответ {i+1} не содержит офферов: {offer_response}")
            continue
            
        logger.info(f"[AllegroSync] Найдено {len(offers_list)} офферов в ответе {i+1}")
        
        # Обрабатываем каждый оффер из массива
        for j, offer in enumerate(offers_list):
            logger.info(f"[AllegroSync] Обработка оффера {j+1}/{len(offers_list)} из ответа {i+1}: {offer}")
            
            if not isinstance(offer, dict):
                logger.error(f"[AllegroSync] Оффер {j+1} не является словарем: {offer} (тип: {type(offer)})")
                continue
            
            # Детальная отладка структуры оффера
            logger.info(f"[AllegroSync] Структура оффера {j+1}: keys={list(offer.keys())}")
            if "external" in offer:
                logger.info(f"[AllegroSync] Поле external в оффере {j+1}: {offer['external']}")
            
            sku = offer.get("external", {}).get("id")
            if not sku:
                logger.warning(f"[AllegroSync] Оффер {j+1} не содержит external.id: {offer}")
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
def update_single_allegro_offer(self, token_id: str, offer_id: str, target_stock: int, sku: str):
    """
    Celery-задача: обновление оффера через микросервис Allegro с учетом лимита, retry и уведомлением в Telegram при неудаче.
    """
    from app.services.tg_client import TelegramManager
    import logging
    import time
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    owner_id = str(uuid.uuid4())
    
    # Получаем информацию о токене из микросервиса
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['id'] == token_id:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен с id={token_id} не найден в микросервисе (update)")
        return {"success": False, "offer_id": offer_id, "sku": sku, "error": "Token not found"}
    
    account_name = token_info['account_name']
    
    # Попытка установить лок
    if not acquire_product_sync_lock(sku, owner_id):
        logger.warning(f"[AllegroSync] Лок на SKU {sku} уже активен, задача не будет выполнена (offer_id={offer_id})")
        return {"success": False, "offer_id": offer_id, "sku": sku, "error": "Lock already active"}
    
    try:
        # Обновляем остаток оффера через микросервис
        success = update_offer_stock_via_microservice(UUID(token_id), sku, target_stock)
        
        if success:
            logger.info(f"[AllegroSync] Обновлен оффер {offer_id} (stock={target_stock}) для аккаунта {account_name}. Время: {time.time() - start:.2f} сек")
            release_product_sync_lock(sku, owner_id, status="success")
            return {"success": True, "offer_id": offer_id, "sku": sku, "stock": target_stock}
        else:
            raise Exception("Микросервис вернул ошибку при обновлении остатка")
            
    except Exception as e:
        logger.error(f"[AllegroSync] Ошибка обновления оффера {offer_id} для аккаунта {account_name}: {e}")
        release_product_sync_lock(sku, owner_id, status="error", error=str(e))
        
        if self.request.retries >= self.max_retries:
            msg = (
                f"❗️ Ошибка обновления оффера Allegro\n"
                f"Аккаунт: {account_name}\n"
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
    

@celery.task
def sync_all_offers_for_account(account_name: str):
    """
    Celery-задача: синхронизация цен для всех товаров конкретного аккаунта Allegro через микросервис.
    Игнорирует флаг price_sync_enabled и запускает синхронизацию цен для всех товаров,
    у которых есть настройки синхронизации для данного аккаунта.
    """
    logger = logging.getLogger("allegro.sync")
    start = time.time()
    logger.info(f"[AllegroSync] Старт массовой синхронизации цен для аккаунта {account_name} через микросервис")
    
    # Проверяем существование аккаунта в микросервисе
    tokens = get_active_tokens_from_microservice()
    token_info = None
    for token in tokens:
        if token['account_name'] == account_name:
            token_info = token
            break
    
    if not token_info:
        logger.error(f"[AllegroSync] Токен для аккаунта {account_name} не найден в микросервисе")
        return {"success": False, "error": "Токен не найден", "account_name": account_name}
    
    with SessionLocal() as session:
        # Получаем сервис синхронизации
        sync_service = get_sync_service(session)
        
        # Получаем все настройки синхронизации для данного аккаунта
        # Независимо от флага price_sync_enabled
        from app.models.product_allegro_sync_settings import ProductAllegroSyncSettings
        settings_query = select(ProductAllegroSyncSettings).where(
            ProductAllegroSyncSettings.allegro_account_name == account_name
        )
        settings_result = session.exec(settings_query)
        all_settings = settings_result.all()
        
        if not all_settings:
            logger.warning(f"[AllegroSync] Нет настроек синхронизации для аккаунта {account_name}")
            return {
                "success": True,
                "account_name": account_name,
                "products_queued": 0,
                "message": "Нет товаров с настройками синхронизации"
            }
        
        logger.info(f"[AllegroSync] Найдено {len(all_settings)} товаров с настройками для аккаунта {account_name}")
        
        # Запускаем задачи синхронизации цен для каждого товара
        queued_tasks = []
        for settings in all_settings:
            try:
                task = sync_allegro_price_single_product_account.apply_async(
                    args=[settings.product_sku, account_name]
                )
                queued_tasks.append({
                    "sku": settings.product_sku,
                    "task_id": task.id
                })
                logger.debug(f"[AllegroSync] Запущена синхронизация цены для SKU {settings.product_sku}, task_id: {task.id}")
            except Exception as e:
                logger.error(f"[AllegroSync] Ошибка запуска задачи для SKU {settings.product_sku}: {e}")
        
        logger.info(f"[AllegroSync] Массовая синхронизация аккаунта {account_name} завершена. "
                   f"Запущено задач: {len(queued_tasks)}. Время: {time.time() - start:.2f} сек")
        
        return {
            "success": True,
            "account_name": account_name,
            "products_queued": len(queued_tasks),
            "total_products": len(all_settings),
            "queued_tasks": queued_tasks
        }