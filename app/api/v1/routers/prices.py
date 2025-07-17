"""
 * @file: prices.py
 * @description: API роуты для работы с ценами товаров
 * @dependencies: FastAPI, prices_service
 * @created: 2024-01-XX
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlmodel import Session
import logging
logger = logging.getLogger(__name__)

from app.services.prices_service import (
    prices_service,
    PriceDataCreate,
    PriceDataUpdate,
    PriceDataResponse
)
from app.api.deps import get_current_user, get_current_user_optional
from app.models.user import User

router = APIRouter()


@router.get("/health", response_model=dict)
async def prices_health_check():
    """Проверка доступности сервиса цен"""
    return {
        "status": "healthy" if prices_service.is_available() else "unavailable",
        "service": "prices_service"
    }


@router.get("/statistics", response_model=Dict[str, Any])
async def get_price_statistics(
    current_user: User = Depends(get_current_user_optional)
):
    """Получение статистики по ценам"""
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        return prices_service.get_price_statistics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting price statistics: {str(e)}")


@router.get("/", response_model=List[PriceDataResponse])
async def get_all_prices(
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user_optional)
):
    """Получение всех цен с пагинацией"""
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        return prices_service.get_all_prices(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting prices: {str(e)}")


@router.get("/{sku}", response_model=PriceDataResponse)
async def get_price_by_sku(
    sku: str,
    current_user: User = Depends(get_current_user_optional)
):
    """Получение цены по SKU"""
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        price = prices_service.get_price_by_sku(sku)
        if not price:
            raise HTTPException(status_code=404, detail="Price not found")
        return price
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting price: {str(e)}")


@router.post("/batch", response_model=Dict[str, PriceDataResponse])
async def get_prices_batch(
    skus: List[str],
    current_user: User = Depends(get_current_user_optional)
):
    """Получение цен по списку SKU"""
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        return prices_service.get_prices_by_skus(skus)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting prices: {str(e)}")


@router.post("/", response_model=PriceDataResponse)
async def create_price(
    price_data: PriceDataCreate,
    current_user: User = Depends(get_current_user_optional)
):
    """Создание или обновление цены"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        return prices_service.create_price(price_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating price: {str(e)}")


@router.put("/{sku}", response_model=PriceDataResponse)
async def update_price(
    sku: str,
    price_data: PriceDataUpdate,
    current_user: User = Depends(get_current_user_optional),
    request: Request = None
):
    logger.info(f"[API] PUT /api/prices/{sku} | user={getattr(current_user, 'email', None)} | is_admin={getattr(current_user, 'is_admin', None)} | body={price_data}")
    if not current_user.is_admin:
        logger.warning(f"[API] 403 Forbidden: user={getattr(current_user, 'email', None)} не админ")
        raise HTTPException(status_code=403, detail="Admin access required")
    if not prices_service.is_available():
        logger.error("[API] 503 Prices service is not available")
        raise HTTPException(status_code=503, detail="Prices service is not available")
    try:
        updated_price = prices_service.update_price(sku, price_data)
        logger.info(f"[API] Цена обновлена: {updated_price}")
        if not updated_price:
            logger.warning(f"[API] 404 Price not found: {sku}")
            raise HTTPException(status_code=404, detail="Price not found")
        return updated_price
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error updating price: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating price: {str(e)}")


@router.delete("/{sku}")
async def delete_price(
    sku: str,
    current_user: User = Depends(get_current_user_optional)
):
    """Удаление цены товара"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        deleted = prices_service.delete_price(sku)
        if not deleted:
            raise HTTPException(status_code=404, detail="Price not found")
        return {"message": "Price deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting price: {str(e)}")


@router.put("/batch/update", response_model=List[PriceDataResponse])
async def update_prices_batch(
    prices: List[Dict[str, Any]],
    current_user: User = Depends(get_current_user_optional)
):
    """Массовое обновление цен"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        return prices_service.update_prices_batch(prices)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating prices: {str(e)}")


@router.post("/import", response_model=dict)
async def import_prices(
    prices: List[PriceDataCreate],
    current_user: User = Depends(get_current_user_optional)
):
    """Импорт цен из списка"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not prices_service.is_available():
        raise HTTPException(status_code=503, detail="Prices service is not available")
    
    try:
        created_count = 0
        updated_count = 0
        errors = []
        
        for price_data in prices:
            try:
                existing_price = prices_service.get_price_by_sku(price_data.sku)
                if existing_price:
                    prices_service.update_price(
                        price_data.sku,
                        PriceDataUpdate(min_price=price_data.min_price)
                    )
                    updated_count += 1
                else:
                    prices_service.create_price(price_data)
                    created_count += 1
            except Exception as e:
                errors.append(f"Error processing SKU {price_data.sku}: {str(e)}")
        
        return {
            "created": created_count,
            "updated": updated_count,
            "errors": errors
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing prices: {str(e)}") 