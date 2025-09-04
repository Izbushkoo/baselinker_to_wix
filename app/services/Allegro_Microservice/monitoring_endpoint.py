"""
 * @file: monitoring_endpoint.py
 * @description: Интерфейс для работы с микросервисом мониторинга системы переноса офферов
 * @dependencies: base.py, models.py, requests
 * @created: 2024-12-19
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .base import BaseClient
from .models import (
    MetricsResponse,
    SessionStatisticsResponse,
    PerformanceStatisticsResponse,
    ErrorAnalysisResponse,
    MarketDistributionResponse,
    SystemHealthResponse,
    StatusResponse
)


class MonitoringClient(BaseClient):
    """Клиент для работы с микросервисом мониторинга"""
    
    def __init__(self, jwt_token: str, base_url: str = None, timeout: Optional[int] = 30):
        super().__init__(jwt_token, base_url, timeout)
        self.endpoint = f"{self.base_url}/monitoring"
    
    async def get_current_metrics(self) -> MetricsResponse:
        """
        Получить текущие метрики системы.
        
        Включает информацию о сессиях, офферах, производительности,
        ошибках и использовании ресурсов.
        
        Returns:
            MetricsResponse: Актуальные метрики производительности системы
        """
        url = f"{self.endpoint}/metrics"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return MetricsResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения метрик: {str(e)}")
    
    async def get_metrics_history(self, hours: int = 1) -> List[MetricsResponse]:
        """
        Получить историю метрик за указанное количество часов.
        
        Args:
            hours: Количество часов назад (1-24)
            
        Returns:
            List[MetricsResponse]: История метрик за указанный период
        """
        if not 1 <= hours <= 24:
            raise ValueError("Количество часов должно быть от 1 до 24")
        
        url = f"{self.endpoint}/metrics/history"
        params = {"hours": hours}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            history_data = response.json()
            return [MetricsResponse(**metrics) for metrics in history_data]
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения истории метрик: {str(e)}")
    
    async def get_session_statistics(self) -> SessionStatisticsResponse:
        """
        Получить статистику сессий переноса.
        
        Returns:
            SessionStatisticsResponse: Детальная статистика по сессиям
        """
        url = f"{self.endpoint}/sessions/statistics"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return SessionStatisticsResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения статистики сессий: {str(e)}")
    
    async def get_performance_statistics(self) -> PerformanceStatisticsResponse:
        """
        Получить статистику производительности.
        
        Включает время обработки, перцентили, скорость обработки
        и статистику API вызовов.
        
        Returns:
            PerformanceStatisticsResponse: Детальная статистика производительности
        """
        url = f"{self.endpoint}/performance/statistics"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return PerformanceStatisticsResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения статистики производительности: {str(e)}")
    
    async def get_error_analysis(self) -> ErrorAnalysisResponse:
        """
        Получить анализ ошибок системы.
        
        Включает общую статистику ошибок, их типы и частоту.
        
        Returns:
            ErrorAnalysisResponse: Детальный анализ ошибок
        """
        url = f"{self.endpoint}/errors/analysis"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return ErrorAnalysisResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения анализа ошибок: {str(e)}")
    
    async def get_market_distribution(self) -> MarketDistributionResponse:
        """
        Получить распределение операций по рынкам.
        
        Returns:
            MarketDistributionResponse: Статистика использования различных рынков
        """
        url = f"{self.endpoint}/markets/distribution"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return MarketDistributionResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения распределения по рынкам: {str(e)}")
    
    async def get_system_health(self) -> SystemHealthResponse:
        """
        Проверить состояние системы.
        
        Выполняет комплексную проверку различных компонентов системы
        и возвращает общую оценку здоровья.
        
        Returns:
            SystemHealthResponse: Общая оценка здоровья системы
        """
        url = f"{self.endpoint}/health"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return SystemHealthResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка проверки состояния системы: {str(e)}")
    
    async def export_metrics(self, format: str = "json") -> Dict[str, str]:
        """
        Экспортировать метрики в указанном формате.
        
        Args:
            format: Формат экспорта (json или csv)
            
        Returns:
            Dict[str, str]: Экспортированные данные
        """
        if format not in ["json", "csv"]:
            raise ValueError("Формат должен быть 'json' или 'csv'")
        
        url = f"{self.endpoint}/metrics/export"
        params = {"format": format}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка экспорта метрик: {str(e)}")
    
    async def reset_metrics(self) -> Dict[str, str]:
        """
        Сбросить все метрики.
        
        ВНИМАНИЕ: Эта операция удаляет все собранные данные!
        Используйте только для тестирования или обслуживания.
        
        Returns:
            Dict[str, str]: Результат сброса метрик
        """
        url = f"{self.endpoint}/metrics/reset"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка сброса метрик: {str(e)}")
    
    async def get_real_time_metrics(self) -> Dict[str, Any]:
        """
        Получить метрики в реальном времени.
        
        Returns:
            Dict[str, Any]: Текущие метрики в реальном времени
        """
        url = f"{self.endpoint}/metrics/realtime"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения метрик в реальном времени: {str(e)}")
    
    async def get_alert_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Получить историю алертов.
        
        Args:
            hours: Количество часов назад для получения алертов
            
        Returns:
            List[Dict[str, Any]]: История алертов
        """
        url = f"{self.endpoint}/alerts/history"
        params = {"hours": hours}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            alerts_data = response.json()
            return alerts_data.get("alerts", [])
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения истории алертов: {str(e)}")
    
    async def acknowledge_alert(self, alert_id: str) -> StatusResponse:
        """
        Подтвердить получение алерта.
        
        Args:
            alert_id: ID алерта для подтверждения
            
        Returns:
            StatusResponse: Результат подтверждения
        """
        url = f"{self.endpoint}/alerts/{alert_id}/acknowledge"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка подтверждения алерта: {str(e)}")
    
    async def get_performance_trends(self, days: int = 7) -> Dict[str, Any]:
        """
        Получить тренды производительности.
        
        Args:
            days: Количество дней для анализа трендов
            
        Returns:
            Dict[str, Any]: Тренды производительности
        """
        url = f"{self.endpoint}/performance/trends"
        params = {"days": days}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения трендов производительности: {str(e)}")
    
    async def get_resource_usage(self) -> Dict[str, Any]:
        """
        Получить информацию об использовании ресурсов.
        
        Returns:
            Dict[str, Any]: Информация об использовании ресурсов
        """
        url = f"{self.endpoint}/resources/usage"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения информации об использовании ресурсов: {str(e)}")
    
    async def get_api_performance(self) -> Dict[str, Any]:
        """
        Получить статистику производительности API.
        
        Returns:
            Dict[str, Any]: Статистика API
        """
        url = f"{self.endpoint}/api/performance"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения статистики API: {str(e)}")
    
    async def get_websocket_connections(self) -> Dict[str, Any]:
        """
        Получить информацию о WebSocket соединениях.
        
        Returns:
            Dict[str, Any]: Информация о WebSocket соединениях
        """
        url = f"{self.endpoint}/websocket/connections"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения информации о WebSocket соединениях: {str(e)}")
    
    async def subscribe_to_metrics_updates(self, metrics_types: List[str]) -> StatusResponse:
        """
        Подписаться на обновления метрик.
        
        Args:
            metrics_types: Список типов метрик для подписки
            
        Returns:
            StatusResponse: Результат подписки
        """
        url = f"{self.endpoint}/metrics/subscribe"
        payload = {"metrics_types": metrics_types}
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка подписки на обновления метрик: {str(e)}")
    
    async def unsubscribe_from_metrics_updates(self, metrics_types: List[str]) -> StatusResponse:
        """
        Отписаться от обновлений метрик.
        
        Args:
            metrics_types: Список типов метрик для отписки
            
        Returns:
            StatusResponse: Результат отписки
        """
        url = f"{self.endpoint}/metrics/unsubscribe"
        payload = {"metrics_types": metrics_types}
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка отписки от обновлений метрик: {str(e)}")
    
    async def get_custom_metrics(self, metric_names: List[str]) -> Dict[str, Any]:
        """
        Получить пользовательские метрики.
        
        Args:
            metric_names: Список имен пользовательских метрик
            
        Returns:
            Dict[str, Any]: Значения пользовательских метрик
        """
        url = f"{self.endpoint}/metrics/custom"
        params = {"metric_names": ",".join(metric_names)}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения пользовательских метрик: {str(e)}")
    
    async def set_custom_metric(self, metric_name: str, value: Any, tags: Optional[Dict[str, str]] = None) -> StatusResponse:
        """
        Установить значение пользовательской метрики.
        
        Args:
            metric_name: Имя метрики
            value: Значение метрики
            tags: Дополнительные теги для метрики
            
        Returns:
            StatusResponse: Результат установки метрики
        """
        url = f"{self.endpoint}/metrics/custom"
        payload = {
            "metric_name": metric_name,
            "value": value
        }
        
        if tags:
            payload["tags"] = tags
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка установки пользовательской метрики: {str(e)}")
