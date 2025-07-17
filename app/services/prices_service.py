"""
 * @file: prices_service.py
 * @description: Сервис для работы с удаленной БД цен
 * @dependencies: SQLModel, SQLAlchemy, pydantic, app.core.config
 * @created: 2024-01-XX
"""

from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime
import logging
logger = logging.getLogger(__name__)

from sqlmodel import SQLModel, Field, create_engine, Session, select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel, Field as PydanticField

from app.core.config import settings


class PriceData(SQLModel, table=True):
    """Модель для таблицы prices_data в удаленной БД"""
    __tablename__ = "prices_data"
    
    sku: str = Field(primary_key=True, max_length=200)
    min_price: Optional[Decimal] = Field(default=Decimal('0.00'), decimal_places=2, max_digits=10)


class PriceDataCreate(BaseModel):
    """Схема для создания записи цены"""
    sku: str = PydanticField(..., min_length=1, max_length=200)
    min_price: Decimal = PydanticField(..., ge=0, decimal_places=2)


class PriceDataUpdate(BaseModel):
    """Схема для обновления записи цены"""
    min_price: Decimal = PydanticField(..., ge=0, decimal_places=2)


class PriceDataResponse(BaseModel):
    """Схема для ответа с данными цены"""
    sku: str
    min_price: Decimal
    
    class Config:
        from_attributes = True


class PricesService:
    """Сервис для работы с удаленной БД цен"""
    
    def __init__(self):
        self.engine = None
        self.async_engine = None
        self.session_local = None
        self.async_session_local = None
        self._init_connections()
    
    def _init_connections(self):
        """Инициализация подключений к БД"""
        if settings.PRICES_DB_URI:
            self.engine = create_engine(settings.PRICES_DB_URI, pool_pre_ping=True)
            self.session_local = sessionmaker(bind=self.engine, class_=Session)
            
        if settings.PRICES_DB_URI_ASYNC:
            self.async_engine = create_async_engine(settings.PRICES_DB_URI_ASYNC)
            self.async_session_local = async_sessionmaker(
                bind=self.async_engine, 
                autoflush=False, 
                expire_on_commit=False
            )
    
    def is_available(self) -> bool:
        """Проверка доступности БД цен"""
        return self.engine is not None or self.async_engine is not None
    
    def get_price_by_sku(self, sku: str) -> Optional[PriceDataResponse]:
        try:
            if not self.session_local:
                raise RuntimeError("Prices database connection is not configured")
            
            with self.session_local() as session:
                statement = select(PriceData).where(PriceData.sku == sku)
                result = session.exec(statement).first()
                return PriceDataResponse.model_validate(result) if result else None
        except Exception as e:
            logger.error(f'Error getting price for SKU {sku}: {e}')
            return None
    
    def get_prices_by_skus(self, skus: List[str]) -> Dict[str, PriceDataResponse]:
        """Получение цен по списку SKU"""
        try:
            if not self.session_local:
                raise RuntimeError("Prices database connection is not configured")
            
            with self.session_local() as session:
                statement = select(PriceData).where(PriceData.sku.in_(skus))
                results = session.exec(statement).all()
                
                return {
                    result.sku: PriceDataResponse.model_validate(result) 
                    for result in results
                }
        except Exception as e:
            logger.error(f'Error getting prices for SKUs: {e}')
            return {}
    
    def get_all_prices(self, limit: int = 1000, offset: int = 0) -> List[PriceDataResponse]:
        """Получение всех цен с пагинацией"""
        if not self.session_local:
            raise RuntimeError("Prices database connection is not configured")
        
        with self.session_local() as session:
            statement = select(PriceData).offset(offset).limit(limit)
            results = session.exec(statement).all()
            
            return [PriceDataResponse.model_validate(result) for result in results]
    
    def create_price(self, price_data: PriceDataCreate) -> PriceDataResponse:
        """Создание новой записи цены"""
        if not self.session_local:
            raise RuntimeError("Prices database connection is not configured")
        
        with self.session_local() as session:
            # Проверяем, есть ли уже запись с таким SKU
            existing = session.exec(
                select(PriceData).where(PriceData.sku == price_data.sku)
            ).first()
            
            if existing:
                # Обновляем существующую запись
                existing.min_price = price_data.min_price
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return PriceDataResponse.model_validate(existing)
            else:
                # Создаем новую запись
                db_price = PriceData(
                    sku=price_data.sku,
                    min_price=price_data.min_price
                )
                session.add(db_price)
                session.commit()
                session.refresh(db_price)
                return PriceDataResponse.model_validate(db_price)
    
    def update_price(self, sku: str, price_data: PriceDataUpdate) -> Optional[PriceDataResponse]:
        try:
            if not self.session_local:
                raise RuntimeError("Prices database connection is not configured")
            
            with self.session_local() as session:
                db_price = session.exec(
                    select(PriceData).where(PriceData.sku == sku)
                ).first()
                
                if not db_price:
                    return None
                
                db_price.min_price = price_data.min_price
                session.add(db_price)
                session.commit()
                session.refresh(db_price)
                
                return PriceDataResponse.model_validate(db_price)
        except Exception as e:
            logger.error(f'Error updating price for SKU {sku}: {e}')
            return None
    
    def delete_price(self, sku: str) -> bool:
        """Удаление цены товара"""
        if not self.session_local:
            raise RuntimeError("Prices database connection is not configured")
        
        with self.session_local() as session:
            db_price = session.exec(
                select(PriceData).where(PriceData.sku == sku)
            ).first()
            
            if not db_price:
                return False
            
            session.delete(db_price)
            session.commit()
            return True
    
    def update_prices_batch(self, prices: List[Dict[str, Any]]) -> List[PriceDataResponse]:
        """Массовое обновление цен"""
        if not self.session_local:
            raise RuntimeError("Prices database connection is not configured")
        
        updated_prices = []
        
        with self.session_local() as session:
            for price_item in prices:
                sku = price_item.get('sku')
                new_price = price_item.get('min_price') or price_item.get('price')  # Поддерживаем оба варианта
                
                if not sku or new_price is None:
                    continue
                
                db_price = session.exec(
                    select(PriceData).where(PriceData.sku == sku)
                ).first()
                
                if db_price:
                    db_price.min_price = Decimal(str(new_price))
                    session.add(db_price)
                    updated_prices.append(PriceDataResponse.model_validate(db_price))
                else:
                    # Создаем новую запись
                    new_db_price = PriceData(
                        sku=sku,
                        min_price=Decimal(str(new_price))
                    )
                    session.add(new_db_price)
                    session.flush()  # Чтобы получить SKU
                    updated_prices.append(PriceDataResponse.model_validate(new_db_price))
            
            session.commit()
        
        return updated_prices
    
    def get_price_statistics(self) -> Dict[str, Any]:
        """Получение статистики по ценам"""
        if not self.session_local:
            raise RuntimeError("Prices database connection is not configured")
        
        with self.session_local() as session:
            count_result = session.exec(select(func.count(PriceData.sku)))
            total_count = count_result.first()
            
            if total_count == 0:
                return {
                    'total_count': 0,
                    'avg_price': 0,
                    'min_price': 0,
                    'max_price': 0
                }
            
            # Получаем все цены для вычисления статистики
            prices = session.exec(select(PriceData.min_price)).all()
            # Фильтруем None значения
            prices = [p for p in prices if p is not None]
            
            if not prices:
                return {
                    'total_count': total_count,
                    'avg_price': 0,
                    'min_price': 0,
                    'max_price': 0
                }
            
            return {
                'total_count': total_count,
                'avg_price': float(sum(prices) / len(prices)),
                'min_price': float(min(prices)),
                'max_price': float(max(prices))
            }


# Создаем глобальный экземпляр сервиса
prices_service = PricesService() 