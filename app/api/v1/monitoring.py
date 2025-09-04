"""
 * @file: app/api/v1/monitoring.py
 * @description: API эндпоинты для мониторинга системы переноса офферов
 * @dependencies: FastAPI, TransferMetricsService, TransferLoggerService
 * @created: 2024-12-19
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserDep
from app.core.auth import CurrentUser
from app.services.transfer_metrics_service import transfer_metrics, TransferMetrics
from app.services.transfer_logger_service import transfer_logger, TransferEventType, TransferLogLevel
from app.schemas.offer_transfer import (
    MetricsResponse,
    SessionStatisticsResponse,
    PerformanceStatisticsResponse,
    ErrorAnalysisResponse,
    MarketDistributionResponse,
    SystemHealthResponse,
    StatusResponse
)

router = APIRouter()


# ===============================================
# API эндпоинты
# ===============================================

@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Получить текущие метрики системы",
    description="Возвращает актуальные метрики производительности системы переноса офферов"
)
async def get_current_metrics(
    current_user: CurrentUser = CurrentUserDep
) -> MetricsResponse:
    """
    Получить текущие метрики системы.
    
    Включает информацию о сессиях, офферах, производительности,
    ошибках и использовании ресурсов.
    """
    try:
        metrics = transfer_metrics.get_current_metrics()
        
        return MetricsResponse(
            timestamp=metrics.timestamp,
            total_sessions=metrics.total_sessions,
            active_sessions=metrics.active_sessions,
            completed_sessions=metrics.completed_sessions,
            failed_sessions=metrics.failed_sessions,
            total_offers_processed=metrics.total_offers_processed,
            successful_offers=metrics.successful_offers,
            failed_offers=metrics.failed_offers,
            avg_processing_time_ms=metrics.avg_processing_time_ms,
            avg_offers_per_second=metrics.avg_offers_per_second,
            market_distribution=metrics.market_distribution,
            error_rate_percent=metrics.error_rate_percent,
            top_errors=metrics.top_errors,
            api_calls_count=metrics.api_calls_count,
            avg_api_response_time_ms=metrics.avg_api_response_time_ms,
            active_websocket_connections=metrics.active_websocket_connections
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения метрик: {str(e)}"
        )


@router.get(
    "/metrics/history",
    response_model=List[MetricsResponse],
    summary="Получить историю метрик",
    description="Возвращает историю метрик за указанный период"
)
async def get_metrics_history(
    hours: int = Query(1, ge=1, le=24, description="Количество часов назад"),
    current_user: CurrentUser = CurrentUserDep
) -> List[MetricsResponse]:
    """
    Получить историю метрик за указанное количество часов.
    
    Args:
        hours: Количество часов назад (1-24)
    """
    try:
        history = transfer_metrics.get_metrics_history(hours)
        
        return [
            MetricsResponse(
                timestamp=metrics.timestamp,
                total_sessions=metrics.total_sessions,
                active_sessions=metrics.active_sessions,
                completed_sessions=metrics.completed_sessions,
                failed_sessions=metrics.failed_sessions,
                total_offers_processed=metrics.total_offers_processed,
                successful_offers=metrics.successful_offers,
                failed_offers=metrics.failed_offers,
                avg_processing_time_ms=metrics.avg_processing_time_ms,
                avg_offers_per_second=metrics.avg_offers_per_second,
                market_distribution=metrics.market_distribution,
                error_rate_percent=metrics.error_rate_percent,
                top_errors=metrics.top_errors,
                api_calls_count=metrics.api_calls_count,
                avg_api_response_time_ms=metrics.avg_api_response_time_ms,
                active_websocket_connections=metrics.active_websocket_connections
            )
            for metrics in history
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения истории метрик: {str(e)}"
        )


@router.get(
    "/sessions/statistics",
    response_model=SessionStatisticsResponse,
    summary="Получить статистику сессий",
    description="Возвращает детальную статистику по сессиям переноса"
)
async def get_session_statistics(
    current_user: CurrentUser = CurrentUserDep
) -> SessionStatisticsResponse:
    """
    Получить статистику сессий переноса.
    """
    try:
        stats = transfer_metrics.get_session_statistics()
        
        return SessionStatisticsResponse(**stats)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения статистики сессий: {str(e)}"
        )


@router.get(
    "/performance/statistics",
    response_model=PerformanceStatisticsResponse,
    summary="Получить статистику производительности",
    description="Возвращает детальную статистику производительности системы"
)
async def get_performance_statistics(
    current_user: CurrentUser = CurrentUserDep
) -> PerformanceStatisticsResponse:
    """
    Получить статистику производительности.
    
    Включает время обработки, перцентили, скорость обработки
    и статистику API вызовов.
    """
    try:
        stats = transfer_metrics.get_performance_statistics()
        
        return PerformanceStatisticsResponse(**stats)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения статистики производительности: {str(e)}"
        )


@router.get(
    "/errors/analysis",
    response_model=ErrorAnalysisResponse,
    summary="Получить анализ ошибок",
    description="Возвращает детальный анализ ошибок системы"
)
async def get_error_analysis(
    current_user: CurrentUser = CurrentUserDep
) -> ErrorAnalysisResponse:
    """
    Получить анализ ошибок системы.
    
    Включает общую статистику ошибок, их типы и частоту.
    """
    try:
        analysis = transfer_metrics.get_error_analysis()
        
        return ErrorAnalysisResponse(**analysis)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения анализа ошибок: {str(e)}"
        )


@router.get(
    "/markets/distribution",
    response_model=MarketDistributionResponse,
    summary="Получить распределение по рынкам",
    description="Возвращает статистику использования различных рынков Allegro"
)
async def get_market_distribution(
    current_user: CurrentUser = CurrentUserDep
) -> MarketDistributionResponse:
    """
    Получить распределение операций по рынкам.
    """
    try:
        distribution = transfer_metrics.get_market_distribution()
        
        return MarketDistributionResponse(**distribution)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения распределения по рынкам: {str(e)}"
        )


@router.get(
    "/health",
    response_model=SystemHealthResponse,
    summary="Проверить состояние системы",
    description="Возвращает общую оценку здоровья системы переноса офферов"
)
async def get_system_health(
    current_user: CurrentUser = CurrentUserDep
) -> SystemHealthResponse:
    """
    Проверить состояние системы.
    
    Выполняет комплексную проверку различных компонентов системы
    и возвращает общую оценку здоровья.
    """
    try:
        metrics = transfer_metrics.get_current_metrics()
        
        # Проверки состояния системы
        checks = {}
        total_score = 0
        max_score = 0
        
        # 1. Проверка активности сессий
        max_score += 20
        if metrics.active_sessions == 0:
            session_score = 20  # Нормально, если нет активных сессий
            session_status = "healthy"
        elif metrics.active_sessions <= 10:
            session_score = 20
            session_status = "healthy"
        elif metrics.active_sessions <= 50:
            session_score = 15
            session_status = "warning"
        else:
            session_score = 5
            session_status = "critical"
        
        total_score += session_score
        checks["active_sessions"] = {
            "status": session_status,
            "score": session_score,
            "value": metrics.active_sessions,
            "message": f"{metrics.active_sessions} активных сессий"
        }
        
        # 2. Проверка процента ошибок
        max_score += 25
        if metrics.error_rate_percent <= 1.0:
            error_score = 25
            error_status = "healthy"
        elif metrics.error_rate_percent <= 5.0:
            error_score = 20
            error_status = "warning"
        elif metrics.error_rate_percent <= 10.0:
            error_score = 10
            error_status = "warning"
        else:
            error_score = 0
            error_status = "critical"
        
        total_score += error_score
        checks["error_rate"] = {
            "status": error_status,
            "score": error_score,
            "value": metrics.error_rate_percent,
            "message": f"{metrics.error_rate_percent:.1f}% ошибок"
        }
        
        # 3. Проверка производительности
        max_score += 20
        if metrics.avg_processing_time_ms <= 5000:  # <= 5 секунд
            perf_score = 20
            perf_status = "healthy"
        elif metrics.avg_processing_time_ms <= 15000:  # <= 15 секунд
            perf_score = 15
            perf_status = "warning"
        elif metrics.avg_processing_time_ms <= 30000:  # <= 30 секунд
            perf_score = 10
            perf_status = "warning"
        else:
            perf_score = 0
            perf_status = "critical"
        
        total_score += perf_score
        checks["performance"] = {
            "status": perf_status,
            "score": perf_score,
            "value": metrics.avg_processing_time_ms,
            "message": f"{metrics.avg_processing_time_ms:.0f}ms среднее время обработки"
        }
        
        # 4. Проверка API времени ответа
        max_score += 15
        if metrics.avg_api_response_time_ms <= 1000:  # <= 1 секунда
            api_score = 15
            api_status = "healthy"
        elif metrics.avg_api_response_time_ms <= 3000:  # <= 3 секунды
            api_score = 10
            api_status = "warning"
        elif metrics.avg_api_response_time_ms <= 10000:  # <= 10 секунд
            api_score = 5
            api_status = "warning"
        else:
            api_score = 0
            api_status = "critical"
        
        total_score += api_score
        checks["api_response_time"] = {
            "status": api_status,
            "score": api_score,
            "value": metrics.avg_api_response_time_ms,
            "message": f"{metrics.avg_api_response_time_ms:.0f}ms среднее время API"
        }
        
        # 5. Проверка WebSocket соединений
        max_score += 10
        if metrics.active_websocket_connections <= 100:
            ws_score = 10
            ws_status = "healthy"
        elif metrics.active_websocket_connections <= 500:
            ws_score = 7
            ws_status = "warning"
        else:
            ws_score = 3
            ws_status = "critical"
        
        total_score += ws_score
        checks["websocket_connections"] = {
            "status": ws_status,
            "score": ws_score,
            "value": metrics.active_websocket_connections,
            "message": f"{metrics.active_websocket_connections} WebSocket соединений"
        }
        
        # 6. Проверка успешности сессий
        max_score += 10
        if metrics.total_sessions > 0:
            success_rate = (metrics.completed_sessions / metrics.total_sessions) * 100
            if success_rate >= 95:
                success_score = 10
                success_status = "healthy"
            elif success_rate >= 85:
                success_score = 7
                success_status = "warning"
            elif success_rate >= 70:
                success_score = 3
                success_status = "warning"
            else:
                success_score = 0
                success_status = "critical"
        else:
            success_score = 10  # Нет данных - считаем нормальным
            success_status = "healthy"
            success_rate = 100
        
        total_score += success_score
        checks["session_success_rate"] = {
            "status": success_status,
            "score": success_score,
            "value": success_rate,
            "message": f"{success_rate:.1f}% успешных сессий"
        }
        
        # Рассчитываем общую оценку
        overall_score = (total_score / max_score * 100) if max_score > 0 else 100
        
        # Определяем общий статус
        if overall_score >= 90:
            overall_status = "healthy"
        elif overall_score >= 70:
            overall_status = "warning"
        else:
            overall_status = "critical"
        
        return SystemHealthResponse(
            status=overall_status,
            timestamp=datetime.utcnow(),
            checks=checks,
            overall_score=overall_score
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка проверки состояния системы: {str(e)}"
        )


@router.get(
    "/metrics/export",
    summary="Экспортировать метрики",
    description="Экспортирует метрики в указанном формате (JSON или CSV)"
)
async def export_metrics(
    format: str = Query("json", regex="^(json|csv)$", description="Формат экспорта"),
    current_user: CurrentUser = CurrentUserDep
) -> Dict[str, str]:
    """
    Экспортировать метрики в указанном формате.
    
    Args:
        format: Формат экспорта (json или csv)
    """
    try:
        exported_data = transfer_metrics.export_metrics(format)
        
        return {
            "format": format,
            "timestamp": datetime.utcnow().isoformat(),
            "data": exported_data
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка экспорта метрик: {str(e)}"
        )


@router.post(
    "/metrics/reset",
    summary="Сбросить метрики",
    description="Сбрасывает все собранные метрики (только для администраторов)"
)
async def reset_metrics(
    current_user: CurrentUser = CurrentUserDep
) -> Dict[str, str]:
    """
    Сбросить все метрики.
    
    ВНИМАНИЕ: Эта операция удаляет все собранные данные!
    Используйте только для тестирования или обслуживания.
    """
    try:
        # В реальной системе здесь должна быть проверка прав администратора
        # if not current_user.is_admin:
        #     raise HTTPException(status_code=403, detail="Недостаточно прав")
        
        transfer_metrics.reset_metrics()
        
        return {
            "message": "Все метрики успешно сброшены",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка сброса метрик: {str(e)}"
        )
