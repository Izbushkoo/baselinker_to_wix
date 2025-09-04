"""
 * @file: templates_endpoint.py
 * @description: Интерфейс для работы с микросервисом шаблонов конфигурации переноса
 * @dependencies: base.py, models.py, requests
 * @created: 2024-12-19
"""

import requests
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime

from .base import BaseClient
from .models import (
    TransferTemplate,
    StatusResponse,
    PricingRuleDTO,
    MarketPricingRule
)


class TemplatesClient(BaseClient):
    """Клиент для работы с микросервисом шаблонов"""
    
    def __init__(self, jwt_token: str, base_url: str = None, timeout: Optional[int] = 30):
        super().__init__(jwt_token, base_url, timeout)
        self.endpoint = f"{self.base_url}/api/v1/templates"
    
    async def get_user_templates(self, active_only: bool = True) -> List[TransferTemplate]:
        """
        Получить список всех шаблонов пользователя.
        
        Шаблоны возвращаются отсортированными по частоте использования
        и дате последнего обновления.
        
        Args:
            active_only: Только активные шаблоны
            
        Returns:
            List[TransferTemplate]: Список шаблонов пользователя
        """
        url = f"{self.endpoint}/"
        params = {"active_only": active_only}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            templates_data = response.json()
            return [TransferTemplate(**template) for template in templates_data]
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения шаблонов: {str(e)}")
    
    async def create_template(
        self, 
        name: str, 
        markets: List[str], 
        pricing_rules: List[PricingRuleDTO],
        description: Optional[str] = None,
        filter_settings: Optional[Dict[str, Any]] = None,
        transfer_settings: Optional[Dict[str, Any]] = None
    ) -> TransferTemplate:
        """
        Создать новый шаблон конфигурации переноса.
        
        Шаблон сохраняет настройки рынков, правил ценообразования
        и других параметров для повторного использования.
        
        Args:
            name: Название шаблона
            markets: Целевые рынки
            pricing_rules: Правила ценообразования
            description: Описание шаблона
            filter_settings: Настройки фильтрации
            transfer_settings: Настройки переноса
            
        Returns:
            TransferTemplate: Созданный шаблон
        """
        url = f"{self.endpoint}/"
        payload = {
            "name": name,
            "markets": markets,
            "pricing_rules": pricing_rules
        }
        
        if description:
            payload["description"] = description
        if filter_settings:
            payload["filter_settings"] = filter_settings
        if transfer_settings:
            payload["transfer_settings"] = transfer_settings
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка создания шаблона: {str(e)}")
    
    async def get_template_by_id(self, template_id: UUID) -> Optional[TransferTemplate]:
        """
        Получить шаблон по ID.
        
        Args:
            template_id: ID шаблона
            
        Returns:
            Optional[TransferTemplate]: Шаблон или None, если не найден
        """
        url = f"{self.endpoint}/{template_id}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            if response.status_code == 404:
                return None
            raise Exception(f"Ошибка получения шаблона: {str(e)}")
    
    async def update_template(
        self, 
        template_id: UUID, 
        name: Optional[str] = None,
        markets: Optional[List[str]] = None,
        pricing_rules: Optional[List[PricingRuleDTO]] = None,
        description: Optional[str] = None,
        filter_settings: Optional[Dict[str, Any]] = None,
        transfer_settings: Optional[Dict[str, Any]] = None
    ) -> Optional[TransferTemplate]:
        """
        Обновить существующий шаблон.
        
        Можно обновить любые поля шаблона. Неуказанные поля
        останутся без изменений.
        
        Args:
            template_id: ID шаблона для обновления
            name: Новое название шаблона
            markets: Новые целевые рынки
            pricing_rules: Новые правила ценообразования
            description: Новое описание шаблона
            filter_settings: Новые настройки фильтрации
            transfer_settings: Новые настройки переноса
            
        Returns:
            Optional[TransferTemplate]: Обновленный шаблон или None, если не найден
        """
        url = f"{self.endpoint}/{template_id}"
        payload = {}
        
        if name is not None:
            payload["name"] = name
        if markets is not None:
            payload["markets"] = markets
        if pricing_rules is not None:
            payload["pricing_rules"] = pricing_rules
        if description is not None:
            payload["description"] = description
        if filter_settings is not None:
            payload["filter_settings"] = filter_settings
        if transfer_settings is not None:
            payload["transfer_settings"] = transfer_settings
        
        try:
            response = requests.put(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            if response.status_code == 404:
                return None
            raise Exception(f"Ошибка обновления шаблона: {str(e)}")
    
    async def delete_template(self, template_id: UUID) -> bool:
        """
        Удалить шаблон.
        
        Удаленные шаблоны не могут быть восстановлены.
        
        Args:
            template_id: ID шаблона для удаления
            
        Returns:
            bool: True, если шаблон успешно удален, False, если не найден
        """
        url = f"{self.endpoint}/{template_id}"
        
        try:
            response = requests.delete(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            if response.status_code == 404:
                return False
            raise Exception(f"Ошибка удаления шаблона: {str(e)}")
    
    async def apply_template(self, template_id: UUID) -> Dict[str, Any]:
        """
        Применить шаблон - получить его конфигурацию.
        
        Увеличивает счетчик использований шаблона.
        
        Args:
            template_id: ID шаблона для применения
            
        Returns:
            Dict[str, Any]: Конфигурация шаблона
        """
        url = f"{self.endpoint}/{template_id}/apply"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка применения шаблона: {str(e)}")
    
    async def duplicate_template(self, template_id: UUID, new_name: str) -> TransferTemplate:
        """
        Дублировать существующий шаблон.
        
        Создает точную копию шаблона с новым именем.
        
        Args:
            template_id: ID шаблона для дублирования
            new_name: Новое название для копии
            
        Returns:
            TransferTemplate: Новый дублированный шаблон
        """
        url = f"{self.endpoint}/{template_id}/duplicate"
        payload = {"new_name": new_name}
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка дублирования шаблона: {str(e)}")
    
    async def set_default_template(self, template_id: UUID) -> bool:
        """
        Установить шаблон как шаблон по умолчанию.
        
        Args:
            template_id: ID шаблона для установки по умолчанию
            
        Returns:
            bool: True, если шаблон успешно установлен по умолчанию, False, если не найден
        """
        url = f"{self.endpoint}/{template_id}/set-default"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            if response.status_code == 404:
                return False
            raise Exception(f"Ошибка установки шаблона по умолчанию: {str(e)}")
    
    async def search_templates(
        self, 
        search_query: str, 
        markets: Optional[List[str]] = None
    ) -> List[TransferTemplate]:
        """
        Поиск шаблонов по названию и описанию.
        
        Можно дополнительно фильтровать по рынкам.
        
        Args:
            search_query: Поисковый запрос
            markets: Фильтр по рынкам
            
        Returns:
            List[TransferTemplate]: Список найденных шаблонов
        """
        url = f"{self.endpoint}/search"
        params = {"q": search_query}
        
        if markets:
            params["markets"] = markets
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            templates_data = response.json()
            return [TransferTemplate(**template) for template in templates_data]
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка поиска шаблонов: {str(e)}")
    
    async def get_template_statistics(self, template_id: UUID) -> Dict[str, Any]:
        """
        Получить статистику использования шаблона.
        
        Args:
            template_id: ID шаблона
            
        Returns:
            Dict[str, Any]: Статистика использования шаблона
        """
        url = f"{self.endpoint}/{template_id}/statistics"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения статистики шаблона: {str(e)}")
    
    async def export_template(self, template_id: UUID, format: str = "json") -> Dict[str, Any]:
        """
        Экспортировать шаблон в указанном формате.
        
        Args:
            template_id: ID шаблона для экспорта
            format: Формат экспорта (json, yaml, xml)
            
        Returns:
            Dict[str, Any]: Экспортированный шаблон
        """
        if format not in ["json", "yaml", "xml"]:
            raise ValueError("Формат должен быть 'json', 'yaml' или 'xml'")
        
        url = f"{self.endpoint}/{template_id}/export"
        params = {"format": format}
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка экспорта шаблона: {str(e)}")
    
    async def import_template(
        self, 
        template_data: Dict[str, Any], 
        overwrite: bool = False
    ) -> TransferTemplate:
        """
        Импортировать шаблон из данных.
        
        Args:
            template_data: Данные шаблона для импорта
            overwrite: Перезаписать существующий шаблон с таким же именем
            
        Returns:
            TransferTemplate: Импортированный шаблон
        """
        url = f"{self.endpoint}/import"
        payload = {
            "template_data": template_data,
            "overwrite": overwrite
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка импорта шаблона: {str(e)}")
    
    async def get_template_categories(self) -> List[Dict[str, Any]]:
        """
        Получить список категорий шаблонов.
        
        Returns:
            List[Dict[str, Any]]: Список категорий шаблонов
        """
        url = f"{self.endpoint}/categories"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения категорий шаблонов: {str(e)}")
    
    async def get_templates_by_category(self, category: str) -> List[TransferTemplate]:
        """
        Получить шаблоны по категории.
        
        Args:
            category: Название категории
            
        Returns:
            List[TransferTemplate]: Список шаблонов в указанной категории
        """
        url = f"{self.endpoint}/category/{category}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            templates_data = response.json()
            return [TransferTemplate(**template) for template in templates_data]
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения шаблонов по категории: {str(e)}")
    
    async def share_template(self, template_id: UUID, user_ids: List[int]) -> StatusResponse:
        """
        Поделиться шаблоном с другими пользователями.
        
        Args:
            template_id: ID шаблона для совместного использования
            user_ids: Список ID пользователей для совместного использования
            
        Returns:
            StatusResponse: Результат операции совместного использования
        """
        url = f"{self.endpoint}/{template_id}/share"
        payload = {"user_ids": user_ids}
        
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return StatusResponse(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка совместного использования шаблона: {str(e)}")
    
    async def get_shared_templates(self) -> List[TransferTemplate]:
        """
        Получить шаблоны, которыми поделились с текущим пользователем.
        
        Returns:
            List[TransferTemplate]: Список общих шаблонов
        """
        url = f"{self.endpoint}/shared"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            templates_data = response.json()
            return [TransferTemplate(**template) for template in templates_data]
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения общих шаблонов: {str(e)}")
    
    async def validate_template(self, template_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Валидировать данные шаблона без сохранения.
        
        Args:
            template_data: Данные шаблона для валидации
            
        Returns:
            Dict[str, Any]: Результат валидации
        """
        url = f"{self.endpoint}/validate"
        
        try:
            response = requests.post(url, json=template_data, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка валидации шаблона: {str(e)}")
    
    async def get_template_version_history(self, template_id: UUID) -> List[Dict[str, Any]]:
        """
        Получить историю версий шаблона.
        
        Args:
            template_id: ID шаблона
            
        Returns:
            List[Dict[str, Any]]: История версий шаблона
        """
        url = f"{self.endpoint}/{template_id}/versions"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json().get("versions", [])
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка получения истории версий шаблона: {str(e)}")
    
    async def restore_template_version(self, template_id: UUID, version_id: str) -> TransferTemplate:
        """
        Восстановить определенную версию шаблона.
        
        Args:
            template_id: ID шаблона
            version_id: ID версии для восстановления
            
        Returns:
            TransferTemplate: Восстановленный шаблон
        """
        url = f"{self.endpoint}/{template_id}/versions/{version_id}/restore"
        
        try:
            response = requests.post(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return TransferTemplate(**response.json())
        except requests.exceptions.RequestException as e:
            raise Exception(f"Ошибка восстановления версии шаблона: {str(e)}")
