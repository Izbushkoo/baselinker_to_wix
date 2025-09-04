"""
 * @file: app/api/v1/markets.py
 * @description: API эндпоинты для работы с рынками Allegro и ценообразованием
 * @dependencies: FastAPI, MarketService, CurrencyRatesService
 * @created: 2024-12-19
"""

from typing import List
from fastapi import APIRouter, HTTPException, Depends

from app.api.dependencies import CurrentUserDep
from app.core.auth import CurrentUser
from app.services.market_service import MarketService
from app.services.currency_rates_service import CurrencyRatesService
from app.schemas.offer_transfer import (
    MarketResponse,
    CurrencyRatesResponse,
    PricingPreviewRequest,
    PricingPreviewResponse,
    StatusResponse
)

router = APIRouter()


@router.get(
    "/",
    response_model=MarketResponse,
    summary="Получить список доступных рынков",
    description="Возвращает список всех доступных рынков Allegro с информацией о валютах и курсах"
)
async def get_available_markets(
    current_user: CurrentUser = CurrentUserDep
) -> MarketResponse:
    """
    Получить список доступных рынков Allegro.
    
    Возвращает информацию о всех поддерживаемых рынках:
    - Польша (PL) - PLN
    - Словакия (SK) - EUR  
    - Чехия (CZ) - CZK
    - Венгрия (HU) - HUF
    - Бизнес Чехия (BUSINESS_CZ) - CZK
    """
    try:
        markets = MarketService.get_available_markets()
        
        # Получаем курсы валют для каждого рынка
        currency_rates = await CurrencyRatesService.get_rates()
        
        # Добавляем курсы к рынкам
        for market in markets:
            market.exchange_rate = currency_rates.rates.get(market.currency)
        
        return MarketResponse(markets=markets)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения списка рынков: {str(e)}"
        )


@router.get(
    "/currency-rates",
    response_model=CurrencyRatesResponse,
    summary="Получить актуальные курсы валют",
    description="Возвращает актуальные курсы валют для всех поддерживаемых рынков"
)
async def get_currency_rates(
    force_refresh: bool = False,
    current_user: CurrentUser = CurrentUserDep
) -> CurrencyRatesResponse:
    """
    Получить актуальные курсы валют.
    
    Args:
        force_refresh: Принудительно обновить кэш курсов валют
    """
    try:
        rates = await CurrencyRatesService.get_rates(force_refresh=force_refresh)
        return CurrencyRatesResponse(rates=rates)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения курсов валют: {str(e)}"
        )


@router.post(
    "/pricing/preview",
    response_model=PricingPreviewResponse,
    summary="Предварительный расчет цен",
    description="Рассчитывает цены для офферов на различных рынках согласно правилам ценообразования"
)
async def preview_pricing(
    request: PricingPreviewRequest,
    current_user: CurrentUser = CurrentUserDep
) -> PricingPreviewResponse:
    """
    Предварительный расчет цен для офферов.
    
    Позволяет увидеть, как будут выглядеть цены на различных рынках
    до фактического переноса офферов.
    """
    try:
        previews = []
        
        # Рассчитываем цены для каждого оффера
        for offer in request.offers:
            preview = await MarketService.preview_pricing(
                offer_id=offer.id,
                original_price=offer.price,
                markets=request.markets,
                pricing_rules=request.pricing_rules
            )
            previews.append(preview)
        
        return PricingPreviewResponse(
            previews=previews,
            total_offers=len(previews),
            markets=request.markets
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка расчета цен: {str(e)}"
        )


@router.post(
    "/currency-rates/clear-cache",
    response_model=StatusResponse,
    summary="Очистить кэш курсов валют",
    description="Принудительно очищает кэш курсов валют для получения свежих данных"
)
async def clear_currency_cache(
    current_user: CurrentUser = CurrentUserDep
) -> StatusResponse:
    """
    Очистить кэш курсов валют.
    
    Полезно для получения самых актуальных курсов валют
    при подозрении на устаревшие данные.
    """
    try:
        CurrencyRatesService.clear_cache()
        
        return StatusResponse(
            success=True,
            message="Кэш курсов валют очищен",
            details={"action": "cache_cleared"}
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка очистки кэша: {str(e)}"
        )


@router.get(
    "/supported-currencies",
    summary="Получить список поддерживаемых валют",
    description="Возвращает список всех поддерживаемых валют"
)
async def get_supported_currencies(
    current_user: CurrentUser = CurrentUserDep
) -> List[str]:
    """
    Получить список поддерживаемых валют.
    """
    try:
        currencies = CurrencyRatesService.get_supported_currencies()
        return currencies
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения списка валют: {str(e)}"
        )
