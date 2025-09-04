"""
 * @file: offer_transfer.py
 * @description: Схемы данных для системы переноса офферов Allegro
 * @dependencies: pydantic, datetime, typing
 * @created: 2024-12-19
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator
from uuid import UUID


# ===============================================
# Базовые модели
# ===============================================

class StatusResponse(BaseModel):
    """Базовый ответ с статусом операции."""
    success: bool = Field(..., description="Успешность операции")
    message: str = Field(..., description="Сообщение о результате")
    details: Optional[Dict[str, Any]] = Field(None, description="Дополнительные детали")


class MarketPricingRule(BaseModel):
    """Правило ценообразования для рынка."""
    type: str = Field(..., description="Тип правила: multiply, add, convert_with_markup, custom")
    value: float = Field(..., description="Значение правила")
    currency: Optional[str] = Field(None, description="Валюта для правила")
    description: Optional[str] = Field(None, description="Описание правила")

    @validator('type')
    def validate_type(cls, v):
        allowed_types = ['multiply', 'add', 'convert_with_markup', 'custom']
        if v not in allowed_types:
            raise ValueError(f'Тип правила должен быть одним из: {allowed_types}')
        return v


class PricingRuleDTO(BaseModel):
    """DTO для правила ценообразования."""
    market: str = Field(..., description="Код рынка")
    rule: MarketPricingRule = Field(..., description="Правило ценообразования")


# ===============================================
# Модели для переноса офферов
# ===============================================

class OfferTransferRequest(BaseModel):
    """Запрос на перенос оффера."""
    offer_id: str = Field(..., description="ID оффера для переноса")
    source_token_id: int = Field(..., description="ID токена исходного аккаунта")
    target_token_id: int = Field(..., description="ID токена целевого аккаунта")
    pricing_rules: Optional[Dict[str, MarketPricingRule]] = Field(None, description="Правила ценообразования")


class MultipleOffersTransferRequest(BaseModel):
    """Запрос на перенос нескольких офферов."""
    offer_ids: List[str] = Field(..., description="Список ID офферов для переноса")
    source_token_id: int = Field(..., description="ID токена исходного аккаунта")
    target_token_id: int = Field(..., description="ID токена целевого аккаунта")
    pricing_rules: Optional[Dict[str, MarketPricingRule]] = Field(None, description="Правила ценообразования")


class TestTransferRequest(BaseModel):
    """Тестовый запрос на перенос оффера."""
    user_id: int = Field(..., description="ID пользователя")
    offer_id: str = Field(..., description="ID оффера для переноса")
    source_token_id: int = Field(..., description="ID токена исходного аккаунта")
    target_token_id: int = Field(..., description="ID токена целевого аккаунта")


class OfferTransferResponse(BaseModel):
    """Ответ на запрос переноса оффера."""
    offer_id: str = Field(..., description="ID исходного оффера")
    new_offer_id: Optional[str] = Field(None, description="ID нового оффера")
    transfer_status: str = Field(..., description="Статус переноса")
    source_account: str = Field(..., description="Название исходного аккаунта")
    target_account: str = Field(..., description="Название целевого аккаунта")
    error: Optional[str] = Field(None, description="Описание ошибки, если есть")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Время создания")


class MultipleOffersTransferResponse(BaseModel):
    """Ответ на запрос массового переноса офферов."""
    total_offers: int = Field(..., description="Общее количество офферов")
    successful_transfers: int = Field(..., description="Количество успешных переносов")
    failed_transfers: int = Field(..., description="Количество неудачных переносов")
    results: List[OfferTransferResponse] = Field(..., description="Результаты переноса")
    summary: Dict[str, Any] = Field(..., description="Общая сводка")


# ===============================================
# Модели для сравнения офферов
# ===============================================

class CompareOffersRequest(BaseModel):
    """Запрос на сравнение офферов между аккаунтами."""
    source_token_id: int = Field(..., description="ID токена исходного аккаунта")
    target_token_id: int = Field(..., description="ID токена целевого аккаунта")
    filters: Optional[Dict[str, Any]] = Field(None, description="Фильтры для офферов")


class OfferInfo(BaseModel):
    """Информация об оффере."""
    id: str = Field(..., description="ID оффера")
    external_id: Optional[str] = Field(None, description="Внешний ID оффера")
    name: str = Field(..., description="Название оффера")
    price: float = Field(..., description="Цена оффера")
    currency: str = Field(..., description="Валюта цены")
    stock: int = Field(..., description="Доступный остаток")
    category: Optional[str] = Field(None, description="Категория оффера")
    images: List[str] = Field(default_factory=list, description="URL изображений")
    status: str = Field(..., description="Статус оффера")
    created_at: Optional[datetime] = Field(None, description="Время создания")


class CompareOffersResponse(BaseModel):
    """Ответ на запрос сравнения офферов."""
    source_account: str = Field(..., description="Название исходного аккаунта")
    target_account: str = Field(..., description="Название целевого аккаунта")
    available_offers: List[OfferInfo] = Field(..., description="Доступные для переноса офферы")
    total_count: int = Field(..., description="Общее количество доступных офферов")
    comparison_completed_at: datetime = Field(default_factory=datetime.utcnow, description="Время завершения сравнения")


# ===============================================
# Модели для сессий переноса
# ===============================================

class StartTransferRequest(BaseModel):
    """Запрос на запуск сессии переноса."""
    offer_ids: List[str] = Field(..., description="Список ID офферов для переноса")
    source_token_id: int = Field(..., description="ID токена исходного аккаунта")
    target_token_id: int = Field(..., description="ID токена целевого аккаунта")
    excluded_offer_ids: Optional[List[str]] = Field(None, description="ID офферов для исключения")
    markets: List[str] = Field(..., description="Целевые рынки")
    pricing_rules: Dict[str, MarketPricingRule] = Field(..., description="Правила ценообразования")
    template_name: Optional[str] = Field(None, description="Название использованного шаблона")


class TransferSessionResponse(BaseModel):
    """Ответ с информацией о сессии переноса."""
    id: str = Field(..., description="ID сессии")
    status: str = Field(..., description="Статус сессии")
    total_offers: int = Field(..., description="Общее количество офферов")
    processed_offers: int = Field(..., description="Количество обработанных офферов")
    successful_offers: int = Field(..., description="Количество успешных переносов")
    failed_offers: int = Field(..., description="Количество неудачных переносов")
    progress_percentage: float = Field(..., description="Процент выполнения")
    offer_results: List[Dict[str, Any]] = Field(..., description="Результаты по офферам")
    created_at: datetime = Field(..., description="Время создания")
    started_at: Optional[datetime] = Field(None, description="Время запуска")
    completed_at: Optional[datetime] = Field(None, description="Время завершения")


# ===============================================
# Модели для шаблонов
# ===============================================

class TransferTemplate(BaseModel):
    """Шаблон переноса офферов."""
    id: int = Field(..., description="ID шаблона")
    name: str = Field(..., description="Название шаблона")
    description: Optional[str] = Field(None, description="Описание шаблона")
    markets: List[str] = Field(..., description="Целевые рынки")
    pricing_rules: Dict[str, MarketPricingRule] = Field(..., description="Правила ценообразования")
    filter_settings: Dict[str, Any] = Field(default_factory=dict, description="Настройки фильтрации")
    transfer_settings: Dict[str, Any] = Field(default_factory=dict, description="Настройки переноса")
    usage_count: int = Field(default=0, description="Количество использований")
    is_default: bool = Field(default=False, description="Является ли шаблоном по умолчанию")
    is_active: bool = Field(default=True, description="Активен ли шаблон")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Время создания")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Время обновления")
    last_used_at: Optional[datetime] = Field(None, description="Время последнего использования")


# ===============================================
# Модели для метрик
# ===============================================

class TransferMetrics(BaseModel):
    """Метрики системы переноса офферов."""
    active_sessions: int = Field(default=0, description="Количество активных сессий")
    total_processed_offers: int = Field(default=0, description="Общее количество обработанных офферов")
    success_rate: float = Field(default=0.0, description="Процент успешных переносов")
    average_processing_time: float = Field(default=0.0, description="Среднее время обработки")
    market_distribution: List[Dict[str, Any]] = Field(default_factory=list, description="Распределение по рынкам")
    top_errors: List[Dict[str, Any]] = Field(default_factory=list, description="Топ ошибок")


# ===============================================
# Модели для рынков и валют
# ===============================================

class MarketInfo(BaseModel):
    """Информация о рынке."""
    code: str = Field(..., description="Код рынка")
    name: str = Field(..., description="Название рынка")
    currency: str = Field(..., description="Валюта рынка")
    flag: str = Field(..., description="Эмодзи флага")
    exchange_rate: Optional[float] = Field(None, description="Курс обмена к базовой валюте")


class MarketResponse(BaseModel):
    """Ответ со списком рынков."""
    markets: List[MarketInfo] = Field(..., description="Список доступных рынков")


class CurrencyRatesResponse(BaseModel):
    """Ответ с курсами валют."""
    rates: Dict[str, float] = Field(..., description="Курсы валют")
    base_currency: str = Field(..., description="Базовая валюта")
    last_updated: datetime = Field(..., description="Время последнего обновления")


class PricingPreviewRequest(BaseModel):
    """Запрос на предварительный расчет цен."""
    offers: List[OfferInfo] = Field(..., description="Список офферов")
    markets: List[str] = Field(..., description="Целевые рынки")
    pricing_rules: Dict[str, MarketPricingRule] = Field(..., description="Правила ценообразования")


class PricingPreviewResponse(BaseModel):
    """Ответ с предварительным расчетом цен."""
    previews: List[Dict[str, Any]] = Field(..., description="Предварительные расчеты")
    total_offers: int = Field(..., description="Общее количество офферов")
    markets: List[str] = Field(..., description="Целевые рынки")


# ===============================================
# Модели для мониторинга
# ===============================================

class MetricsResponse(BaseModel):
    """Ответ с метриками системы."""
    timestamp: datetime = Field(..., description="Время сбора метрик")
    total_sessions: int = Field(..., description="Общее количество сессий")
    active_sessions: int = Field(..., description="Активные сессии")
    completed_sessions: int = Field(..., description="Завершенные сессии")
    failed_sessions: int = Field(..., description="Неудачные сессии")
    total_offers_processed: int = Field(..., description="Общее количество обработанных офферов")
    successful_offers: int = Field(..., description="Успешно обработанные офферы")
    failed_offers: int = Field(..., description="Неудачно обработанные офферы")
    avg_processing_time_ms: float = Field(..., description="Среднее время обработки (мс)")
    avg_offers_per_second: float = Field(..., description="Средняя скорость обработки (офферы/сек)")
    market_distribution: Dict[str, int] = Field(..., description="Распределение по рынкам")
    error_rate_percent: float = Field(..., description="Процент ошибок")
    top_errors: List[Dict[str, Any]] = Field(..., description="Топ ошибок")
    api_calls_count: int = Field(..., description="Количество API вызовов")
    avg_api_response_time_ms: float = Field(..., description="Среднее время ответа API (мс)")
    active_websocket_connections: int = Field(..., description="Активные WebSocket соединения")


class SessionStatisticsResponse(BaseModel):
    """Статистика сессий."""
    total_sessions: int = Field(..., description="Общее количество сессий")
    completed_sessions: int = Field(..., description="Завершенные сессии")
    failed_sessions: int = Field(..., description="Неудачные сессии")
    active_sessions: int = Field(..., description="Активные сессии")
    success_rate_percent: float = Field(..., description="Процент успешных сессий")
    completion_rate_percent: float = Field(..., description="Процент завершенных сессий")


class PerformanceStatisticsResponse(BaseModel):
    """Статистика производительности."""
    processing: Dict[str, Any] = Field(..., description="Статистика времени обработки")
    api: Dict[str, Any] = Field(..., description="Статистика API вызовов")
    offers_per_second: float = Field(..., description="Скорость обработки офферов")


class ErrorAnalysisResponse(BaseModel):
    """Анализ ошибок."""
    total_errors: int = Field(..., description="Общее количество ошибок")
    error_rate_percent: float = Field(..., description="Процент ошибок")
    error_breakdown: List[Dict[str, Any]] = Field(..., description="Разбивка ошибок")
    unique_error_types: int = Field(..., description="Количество уникальных типов ошибок")


class MarketDistributionResponse(BaseModel):
    """Распределение по рынкам."""
    total_operations: int = Field(..., description="Общее количество операций")
    distribution: List[Dict[str, Any]] = Field(..., description="Распределение по рынкам")


class SystemHealthResponse(BaseModel):
    """Состояние системы."""
    status: str = Field(..., description="Статус системы (healthy/warning/critical)")
    timestamp: datetime = Field(..., description="Время проверки")
    checks: Dict[str, Dict[str, Any]] = Field(..., description="Результаты проверок")
    overall_score: float = Field(..., description="Общая оценка здоровья (0-100)")


# ===============================================
# Модели для WebSocket
# ===============================================

class WebSocketMessage(BaseModel):
    """Сообщение WebSocket."""
    type: str = Field(..., description="Тип сообщения")
    data: Dict[str, Any] = Field(..., description="Данные сообщения")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время отправки")


class SessionUpdateMessage(BaseModel):
    """Сообщение об обновлении сессии."""
    session_id: str = Field(..., description="ID сессии")
    status: str = Field(..., description="Новый статус")
    progress: float = Field(..., description="Прогресс выполнения")
    message: str = Field(..., description="Сообщение об обновлении")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время обновления")
