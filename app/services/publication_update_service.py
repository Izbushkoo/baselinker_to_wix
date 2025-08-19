"""
 * @file: publication_update_service.py
 * @description: Сервис для обновления данных о публикации офферт Allegro в базе данных
 * @dependencies: models.warehouse, database, Allegro_Microservice.offers_endpoint
 * @created: 2024-12-19
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from sqlmodel import Session, select
from app.models.warehouse import Product
from app.database import SessionLocal
from app.services.Allegro_Microservice.offers_endpoint import AllegroOffersMicroserviceClient
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings
import uuid

logger = logging.getLogger(__name__)


class PublicationUpdateService:
    """Сервис для обновления данных о публикации офферт в базе данных"""
    
    def __init__(self):
        # Создаем JWT токен для микросервиса
        self.jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        self.offers_client = AllegroOffersMicroserviceClient(
            jwt_token=self.jwt_token,
            base_url=settings.MICRO_SERVICE_URL
        )
        self.tokens_client = AllegroTokenMicroserviceClient(
            jwt_token=self.jwt_token,
            base_url=settings.MICRO_SERVICE_URL
        )
        self.batch_size = 100  # Размер батча для API запросов (POST не ограничен URL)
    
    def _get_active_allegro_tokens(self) -> List[uuid.UUID]:
        """Получает список активных токенов Allegro с микросервиса"""
        try:
            # Получаем все активные токены с микросервиса
            response = self.tokens_client.get_tokens(
                page=1,
                per_page=100,  # Получаем максимум токенов
                active_only=True
            )
            
            # Извлекаем ID токенов из ответа
            token_uuids = []
            for token_data in response.items:
                try:
                    token_id = token_data.get('id')
                    if token_id:
                        token_uuids.append(uuid.UUID(token_id))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Неверный формат UUID токена {token_data}: {e}")
                    continue
            
            logger.info(f"Найдено {len(token_uuids)} активных токенов Allegro на микросервисе")
            return token_uuids
                
        except Exception as e:
            logger.error(f"Ошибка при получении токенов Allegro с микросервиса: {e}")
            return []
    
    def update_all_products_publication_dates(self) -> Dict[str, int]:
        """Обновляет данные о публикации для всех товаров в базе"""
        logger.info("Начинаем обновление данных о публикации для всех товаров")
        
        try:
            # Получаем все SKU из базы данных
            # Примечание: select(Product.sku) возвращает список строк, а не объектов Product
            # Поэтому мы можем использовать результат напрямую как список SKU
            with SessionLocal() as db:
                products = db.exec(select(Product.sku)).all()
                skus = products
            
            if not skus:
                logger.info("В базе данных нет товаров для обновления")
                return {"total_products": 0, "updated_products": 0, "errors": 0}
            
            logger.info(f"Найдено {len(skus)} товаров для обновления")
            
            # Обновляем данные батчами
            result = self.update_specific_products_publication_dates(skus)
            result["total_products"] = len(skus)
            
            logger.info(f"Обновление завершено: {result['updated_products']} обновлено, {result['errors']} ошибок")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении всех товаров: {e}")
            raise
    
    def update_specific_products_publication_dates(
        self, 
        skus: List[str]
    ) -> Dict[str, int]:
        """Обновляет данные о публикации для указанных SKU"""
        logger.info(f"Начинаем обновление данных о публикации для {len(skus)} товаров")
        
        updated_count = 0
        error_count = 0
        
        try:
            # Разбиваем SKU на батчи
            batches = [skus[i:i + self.batch_size] for i in range(0, len(skus), self.batch_size)]
            logger.info(f"Создано {len(batches)} батчей по {self.batch_size} SKU")
            
            for batch_num, batch_skus in enumerate(batches, 1):
                logger.info(f"Обрабатываем батч {batch_num}/{len(batches)} ({len(batch_skus)} SKU)")
                
                try:
                    logger.info(f"Батч {batch_num}: отправляем {len(batch_skus)} SKU в микросервис")
                    logger.info(f"SKU в батче {batch_num}: {batch_skus[:5]}... (показано первые 5)")
                    
                    # Получаем данные о публикации для батча
                    publication_data = self.get_publication_dates_batch(batch_skus)
                    
                    logger.info(f"Батч {batch_num}: получено {len(publication_data)} дат публикации от микросервиса")
                    
                    # Сохраняем данные в базу
                    batch_updated = self._save_publication_dates_to_db(publication_data)
                    updated_count += batch_updated
                    
                    logger.info(f"Батч {batch_num} обработан: {batch_updated} товаров обновлено")
                    
                    # Задержка между батчами для соблюдения rate limits
                    if batch_num < len(batches):
                        import time
                        time.sleep(2)  # Увеличена задержка для снижения нагрузки на микросервис
                        
                except Exception as e:
                    logger.error(f"Ошибка при обработке батча {batch_num}: {e}")
                    error_count += len(batch_skus)
                    continue
            
            result = {
                "updated_products": updated_count,
                "errors": error_count
            }
            
            logger.info(f"Обновление завершено: {updated_count} обновлено, {error_count} ошибок")
            return result
            
        except Exception as e:
            logger.error(f"Критическая ошибка при обновлении товаров: {e}")
            raise
    
    def get_publication_dates_batch(
        self, 
        skus: List[str], 
        batch_size: int = None
    ) -> Dict[str, Optional[datetime]]:
        """Получает данные о публикации батчами через микросервис"""
        if batch_size is None:
            batch_size = self.batch_size
            
        logger.info(f"Получаем данные о публикации для {len(skus)} SKU через микросервис")
        
        publication_data = {}
        
        try:
            # Получаем все активные токены для доступа к Allegro API
            token_ids = self._get_active_allegro_tokens()
            
            # Вызываем микросервис для получения данных об офферах
            # Используем метод get_offers_by_external_ids для батчевой обработки
            try:
                
                if token_ids:
                    logger.info(f"Вызываем микросервис с {len(token_ids)} токенами и {len(skus)} SKU")
                    logger.debug(f"Токены: {token_ids[:3]}... (показано первые 3)")
                    logger.debug(f"SKU: {skus[:3]}... (показано первые 3)")
                    
                    # Получаем данные об офферах через микросервис
                    response = self.offers_client.get_offers_by_external_ids(
                        token_ids=token_ids,
                        external_ids=skus
                    )
                    
                    # Обрабатываем ответ и извлекаем даты публикации
                    # response - это OfferListResponse, нужно получить поле offers
                    logger.info(f"Тип ответа: {type(response)}")
                    logger.info(f"Атрибуты ответа: {dir(response)}")
                    
                    if hasattr(response, 'offers'):
                        offers_data = response.offers
                        logger.info(f"Тип offers_data: {type(offers_data)}")
                        logger.info(f"Содержимое offers_data: {offers_data[:2] if isinstance(offers_data, list) else offers_data}")
                        
                        # Логируем структуру ответа для отладки
                        if isinstance(offers_data, list):
                            logger.info(f"Микросервис вернул {len(offers_data)} результатов для токенов")
                            for i, token_result in enumerate(offers_data):
                                if isinstance(token_result, dict):
                                    offers_count = len(token_result.get('offers', []))
                                    logger.info(f"Токен {i}: {token_result.get('token_id')} ({token_result.get('account_name')}) - {offers_count} офферов")
                        
                        publication_data = self._process_offers_response(offers_data)
                    else:
                        logger.error(f"Неожиданный формат ответа: {type(response)}")
                        publication_data = {sku: None for sku in skus}
                else:
                    logger.warning("Нет активных токенов для получения данных об офферах")
                    # Возвращаем пустые данные для всех SKU
                    publication_data = {sku: None for sku in skus}
                    
            except Exception as e:
                logger.error(f"Ошибка при вызове микросервиса оффертов: {e}")
                logger.error(f"Детали запроса: {len(token_ids)} токенов, {len(skus)} SKU")
                # Возвращаем пустые данные для всех SKU в случае ошибки
                publication_data = {sku: None for sku in skus}
                
            logger.info(f"Получены данные о публикации для {len(skus)} SKU")
            return publication_data
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных о публикации: {e}")
            # Возвращаем пустые данные для всех SKU в случае ошибки
            return {sku: None for sku in skus}
    
    def _process_offers_response(
        self, 
        offers_response: List[Dict]
    ) -> Dict[str, datetime]:
        """Обрабатывает ответ микросервиса и извлекает даты публикации"""
        publication_dates = {}
        
        try:
            logger.info(f"Начинаем обработку ответа микросервиса. Тип: {type(offers_response)}")
            logger.info(f"Содержимое ответа: {offers_response[:2] if isinstance(offers_response, list) else offers_response}")
            
            # Проверяем, что это список
            if not isinstance(offers_response, list):
                logger.error(f"Ожидался список, получен: {type(offers_response)}")
                return {}
            
            # Проходим по каждому токену в ответе
            for i, token_result in enumerate(offers_response):
                try:
                    logger.info(f"Обрабатываем токен {i}: {type(token_result)}")
                    
                    # Проверяем, что это словарь
                    if not isinstance(token_result, dict):
                        logger.warning(f"Токен {i} не является словарем: {type(token_result)}")
                        continue
                    
                    token_id = token_result.get('token_id')
                    account_name = token_result.get('account_name')
                    offers = token_result.get('offers', [])
                    error = token_result.get('error')
                    
                    logger.info(f"Токен {i}: id={token_id}, account={account_name}, offers_count={len(offers) if offers else 0}")
                    
                    if error:
                        logger.warning(f"Ошибка для токена {token_id} ({account_name}): {error}")
                        continue
                    
                    if not offers:
                        logger.info(f"Нет офферов для токена {token_id} ({account_name})")
                        continue
                    
                    logger.info(f"Обрабатываем {len(offers)} офферов для токена {token_id} ({account_name})")
                    
                    # Обрабатываем офферы для текущего токена
                    for j, offer in enumerate(offers):
                        try:
                            # Проверяем, что оффер - это словарь
                            if not isinstance(offer, dict):
                                logger.warning(f"Оффер {j} для токена {token_id} не является словарем: {type(offer)}")
                                continue
                            
                            # Извлекаем SKU из оффера (может быть в разных полях)
                            sku = offer.get('external', {}).get('id') or offer.get('external_id') or offer.get('sku') or offer.get('product_id')
                            
                            # Извлекаем дату публикации (может быть в разных полях)
                            publication_date = (
                                offer.get('publication', {}).get('startedAt') or
                                offer.get('publication', {}).get('startingAt') or
                                offer.get('publication_date') or 
                                offer.get('created_at') or 
                                offer.get('published_at') or
                                offer.get('listing_date') or
                                offer.get('activation_date')
                            )
                            
                            if sku and publication_date:
                                try:
                                    logger.info(f"Обрабатываем SKU {sku} с датой {publication_date} (тип: {type(publication_date)})")
                                    
                                    # Парсим дату из строки
                                    if isinstance(publication_date, str):
                                        # Убираем 'Z' и парсим ISO формат
                                        parsed_date = datetime.fromisoformat(publication_date.replace('Z', '+00:00'))
                                        logger.info(f"Парсинг строки '{publication_date}' -> {parsed_date}")
                                    elif isinstance(publication_date, datetime):
                                        parsed_date = publication_date
                                        logger.info(f"Дата уже в формате datetime: {parsed_date}")
                                    else:
                                        logger.warning(f"Неизвестный формат даты для SKU {sku}: {publication_date} (тип: {type(publication_date)})")
                                        continue
                                    
                                    # Приводим к offset-naive datetime для совместимости с базой данных
                                    if parsed_date.tzinfo is not None:
                                        parsed_date = parsed_date.replace(tzinfo=None)
                                        logger.info(f"Дата приведена к offset-naive: {parsed_date}")
                                    
                                    # Если для этого SKU уже есть дата, выбираем самую раннюю
                                    if sku in publication_dates:
                                        if parsed_date < publication_dates[sku]:
                                            publication_dates[sku] = parsed_date
                                            logger.info(f"Обновлена дата публикации для SKU {sku}: {parsed_date} (было: {publication_dates[sku]}, токен {account_name})")
                                        else:
                                            logger.info(f"Дата для SKU {sku} не обновлена: {parsed_date} >= {publication_dates[sku]} (токен {account_name})")
                                    else:
                                        publication_dates[sku] = parsed_date
                                        logger.info(f"Добавлена дата публикации для SKU {sku}: {parsed_date} (токен {account_name})")
                                        
                                except ValueError as e:
                                    logger.warning(f"Не удалось распарсить дату для SKU {sku}: {e}, значение: {publication_date}")
                                    continue
                            elif not sku:
                                logger.warning(f"Не найден SKU в оффере. Поля: external={offer.get('external')}, external_id={offer.get('external_id')}, sku={offer.get('sku')}, product_id={offer.get('product_id')}")
                                logger.info(f"Полный оффер для анализа: {offer}")
                            elif not publication_date:
                                logger.info(f"Не найдена дата публикации для SKU {sku}. Поля: publication={offer.get('publication')}, publication_date={offer.get('publication_date')}, created_at={offer.get('created_at')}")
                                logger.info(f"Доступные поля оффера: {list(offer.keys())}")
                                
                        except Exception as e:
                            logger.error(f"Ошибка при обработке оффера {j} для токена {token_id}: {e}")
                            continue
                            
                except Exception as e:
                    logger.error(f"Ошибка при обработке токена {i}: {e}")
                    continue
            
            logger.info(f"Обработано {len(publication_dates)} дат публикации из {len(offers_response)} токенов")
            return publication_dates
            
        except Exception as e:
            logger.error(f"Ошибка при обработке ответа микросервиса: {e}")
            logger.error(f"Тип ответа: {type(offers_response)}")
            return {}
    
    def _save_publication_dates_to_db(
        self, 
        publication_data: Dict[str, Optional[datetime]]
    ) -> int:
        """Сохраняет данные о публикации в базу данных"""
        if not publication_data:
            return 0
            
        updated_count = 0
        
        try:
            with SessionLocal() as db:
                for sku, publication_date in publication_data.items():
                    try:
                        # Находим товар в базе
                        product = db.exec(select(Product).where(Product.sku == sku)).first()
                        
                        if product:
                            # Обновляем дату публикации только если она не была установлена ранее
                            # или если новая дата раньше существующей
                            if (product.first_publication_date is None or 
                                (publication_date and publication_date < product.first_publication_date)):
                                
                                product.first_publication_date = publication_date
                                updated_count += 1
                                
                                logger.info(f"Обновлена дата публикации для SKU {sku}: {publication_date}")
                            else:
                                logger.info(f"Дата для SKU {sku} не обновлена: {publication_date} >= {product.first_publication_date}")
                        
                    except Exception as e:
                        logger.error(f"Ошибка при обновлении товара {sku}: {e}")
                        continue
                
                # Сохраняем изменения в базе
                db.commit()
                logger.info(f"Сохранено в базу данных: {updated_count} товаров обновлено")
                
                return updated_count
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении в базу данных: {e}")
