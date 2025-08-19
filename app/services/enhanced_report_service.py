"""
 * @file: enhanced_report_service.py
 * @description: Расширенный сервис генерации отчетов с автоматическим получением недостающих данных о публикации
 * @dependencies: publication_update_service, warehouse.manager
 * @created: 2024-12-19
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
from sqlmodel import Session, select, func
from app.models.warehouse import Product
from app.database import SessionLocal
from app.services.publication_update_service import PublicationUpdateService
from app.services.warehouse.manager import InventoryManager

logger = logging.getLogger(__name__)


class EnhancedReportService:
    """Расширенный сервис генерации отчетов с данными о публикации"""
    
    def __init__(self):
        self.publication_service = PublicationUpdateService()
        self.inventory_manager = None  # Будет инициализирован при необходимости
    
    def _get_inventory_manager(self) -> InventoryManager:
        """Получает экземпляр InventoryManager"""
        if self.inventory_manager is None:
            from app.services.warehouse.manager import get_manager
            self.inventory_manager = get_manager()
        return self.inventory_manager
    
    def generate_report_with_publications(
        self,
        skus: Optional[List[str]] = None,
        include_images: bool = True
    ) -> Tuple[pd.DataFrame, List[bytes]]:
        """Генерация отчета с автоматическим получением недостающих данных о публикации"""
        logger.info("Генерация расширенного отчета с данными о публикации")
        
        try:
            # Получаем базовый отчет
            inventory_manager = self._get_inventory_manager()
            df, images = inventory_manager.get_stock_report()
            
            if df.empty:
                logger.info("Отчет пуст, нет товаров для обработки")
                return df, images
            
            # Определяем товары без данных о публикации
            missing_publication_skus = self._get_missing_publication_dates(df)
            
            if missing_publication_skus:
                logger.info(f"Найдено {len(missing_publication_skus)} товаров без данных о публикации")
                logger.info(f"Примеры SKU без дат: {missing_publication_skus[:5]}")
                
                # Получаем недостающие данные о публикации
                publication_data = self._get_missing_publication_dates_batch(missing_publication_skus)
                
                # Сохраняем полученные данные в базу
                if publication_data:
                    self._save_publication_dates_to_products(publication_data)
                    
                    # Обновляем отчет с новыми данными
                    df = self._update_report_with_publication_data(df, publication_data)
                    
                    logger.info(f"Отчет обновлен с данными о публикации для {len(publication_data)} товаров")
                else:
                    logger.warning("Не удалось получить данные о публикации для недостающих товаров")
            else:
                logger.info("Все товары имеют данные о публикации")
                # Проверяем несколько примеров дат для отладки
                sample_dates = df['first_publication_date'].head(5).tolist()
                logger.info(f"Примеры дат в отчете: {sample_dates}")
            
            # Фильтруем по указанным SKU, если нужно
            if skus:
                df = df[df['sku'].isin(skus)]
                # Обновляем изображения соответственно
                if include_images:
                    filtered_images = []
                    for sku in skus:
                        if sku in df['sku'].values:
                            sku_index = df[df['sku'] == sku].index[0]
                            if sku_index < len(images):
                                filtered_images.append(images[sku_index])
                    images = filtered_images
                else:
                    images = []
            
            # Убираем изображения, если не нужны
            if not include_images:
                images = []
            
            logger.info(f"Расширенный отчет сгенерирован: {len(df)} товаров")
            return df, images
            
        except Exception as e:
            logger.error(f"Ошибка при генерации расширенного отчета: {e}")
            raise
    
    def _get_missing_publication_dates(self, df: pd.DataFrame) -> List[str]:
        """Определяет товары без данных о публикации"""
        missing_skus = []
        
        for _, row in df.iterrows():
            sku = row['sku']
            publication_date = row.get('first_publication_date')
            
            # Проверяем, что дата действительно есть (теперь это datetime объект)
            if (pd.isna(publication_date) or 
                publication_date is None):
                missing_skus.append(sku)
                logger.debug(f"SKU {sku} не имеет даты публикации: {publication_date}")
            else:
                logger.debug(f"SKU {sku} имеет дату публикации: {publication_date} (тип: {type(publication_date)})")
        
        return missing_skus
    
    def _get_missing_publication_dates_batch(
        self, 
        skus: List[str]
    ) -> Dict[str, Optional[datetime]]:
        """Получает данные о публикации для товаров без этой информации в базе"""
        try:
            logger.info(f"Получаем данные о публикации для {len(skus)} товаров без этой информации")
            
            # Используем PublicationUpdateService для получения данных
            publication_data = self.publication_service.get_publication_dates_batch(skus)
            
            logger.info(f"Получены данные о публикации для {len(publication_data)} товаров")
            return publication_data
            
        except Exception as e:
            logger.error(f"Ошибка при получении недостающих данных о публикации: {e}")
            return {}
    
    def _save_publication_dates_to_products(
        self, 
        publication_data: Dict[str, Optional[datetime]]
    ) -> int:
        """Сохраняет полученные данные о публикации в таблицу Product"""
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
                                
                                logger.debug(f"Обновлена дата публикации для SKU {sku}: {publication_date}")
                        
                    except Exception as e:
                        logger.error(f"Ошибка при обновлении товара {sku}: {e}")
                        continue
                
                # Сохраняем изменения в базе
                db.commit()
                logger.info(f"Сохранено в базу данных: {updated_count} товаров обновлено")
                
                return updated_count
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении в базу данных: {e}")
            raise
    
    def _update_report_with_publication_data(
        self, 
        df: pd.DataFrame, 
        publication_data: Dict[str, Optional[datetime]]
    ) -> pd.DataFrame:
        """Обновляет отчет с новыми данными о публикации"""
        try:
            # Создаем копию DataFrame для обновления
            updated_df = df.copy()
            
            for sku, publication_date in publication_data.items():
                # Находим строку с данным SKU
                mask = updated_df['sku'] == sku
                if mask.any():
                    if publication_date:
                        # Сохраняем объект datetime для правильного форматирования в отчете
                        updated_df.loc[mask, 'first_publication_date'] = publication_date
                        logger.info(f"Обновлена дата в отчете для SKU {sku}: {publication_date}")
                    else:
                        updated_df.loc[mask, 'first_publication_date'] = None
                        logger.info(f"Установлена None дата в отчете для SKU {sku}")
            
            logger.info(f"Отчет обновлен с данными о публикации для {len(publication_data)} товаров")
            return updated_df
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении отчета: {e}")
            return df
    
    def get_publication_statistics(self) -> Dict[str, int]:
        """Получает статистику по данным о публикации"""
        try:
            with SessionLocal() as db:
                # Общее количество товаров
                total_products = db.exec(select(func.count(Product.sku))).first()
                
                # Товары с данными о публикации
                products_with_publication = db.exec(
                    select(func.count(Product.sku))
                    .where(Product.first_publication_date.is_not(None))
                ).first()
                
                # Товары без данных о публикации
                products_without_publication = total_products - products_with_publication
                
                return {
                    "total_products": total_products or 0,
                    "with_publication_date": products_with_publication or 0,
                    "without_publication_date": products_without_publication or 0,
                    "coverage_percentage": round((products_with_publication or 0) / (total_products or 1) * 100, 2)
                }
                
        except Exception as e:
            logger.error(f"Ошибка при получении статистики публикаций: {e}")
            return {
                "total_products": 0,
                "with_publication_date": 0,
                "without_publication_date": 0,
                "coverage_percentage": 0
            }
