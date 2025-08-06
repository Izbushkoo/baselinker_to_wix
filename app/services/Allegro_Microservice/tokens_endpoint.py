import requests
from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime
from app.services.Allegro_Microservice.base import BaseClient
from app.services.Allegro_Microservice.models import (
    TokenResponse,
    AuthInitializeResponse,
    AuthStatusResponse,
    TaskStatusResponse,
    GenericResponse,
    GenericListResponse
)


class AllegroTokenMicroserviceClient(BaseClient):
    """
    Клиент для работы с API управления токенами Allegro.
    """
    def __init__(self, jwt_token, **kwargs):
        super().__init__(jwt_token, **kwargs)
        self.prefix = "/api/v1/tokens"
        self.base_url += self.prefix

    def create_token(
        self,
        account_name: str,
        allegro_token: str,
        refresh_token: str,
        expires_at: datetime
    ) -> TokenResponse:
        """
        Создать новый токен Allegro для указанного аккаунта.
        """
        url = f"{self.base_url}" + "/"
        payload = {
            "account_name": account_name,
            "allegro_token": allegro_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat()
        }
        resp = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return TokenResponse(**data)

    def get_tokens(
        self,
        page: int = 1,
        per_page: int = 10,
        active_only: bool = True
    ) -> GenericListResponse:
        """
        Получить список токенов текущего пользователя с пагинацией.
        """
        params = {"page": page, "per_page": per_page, "active_only": str(active_only).lower()}
        url = f"{self.base_url}/"
        resp = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        tokens = data.get("tokens", [])
        return GenericListResponse(items=tokens, total=data.get("total"), page=data.get("page"), per_page=data.get("per_page"))
     

    def get_token(self, token_id: UUID) -> TokenResponse:
        """
        Получить конкретный токен по ID.
        """
        url = f"{self.base_url}/{token_id}"
        resp = requests.get(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return TokenResponse(**data)

    def update_token(
        self,
        token_id: UUID,
        account_name: Optional[str] = None,
        allegro_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        is_active: Optional[bool] = None
    ) -> TokenResponse:
        """
        Обновить существующий токен.
        """
        url = f"{self.base_url}/{token_id}"
        payload: Dict[str, object] = {}
        if account_name is not None:
            payload['account_name'] = account_name
        if allegro_token is not None:
            payload['allegro_token'] = allegro_token
        if refresh_token is not None:
            payload['refresh_token'] = refresh_token
        if expires_at is not None:
            payload['expires_at'] = expires_at.isoformat()
        if is_active is not None:
            payload['is_active'] = is_active
        resp = requests.put(url, json=payload, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return TokenResponse(**data)

    def delete_token(self, token_id: UUID) -> GenericResponse:
        """
        Удалить (деактивировать) токен.
        """
        url = f"{self.base_url}/{token_id}"
        resp = requests.delete(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return GenericResponse(data=data)

    def refresh_token(
        self,
        token_id: UUID
    ) -> TokenResponse:
        """
        Обновить access token используя refresh token.
        """
        url = f"{self.base_url}/{token_id}/refresh"
        resp = requests.post(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return TokenResponse(**data)

    def get_user_tokens(
        self,
        user_id: str,
        active_only: bool = True
    ) -> GenericListResponse:
        """
        Получить все токены пользователя (только для администраторов).
        """
        params = {"active_only": str(active_only).lower()}
        url = f"{self.base_url}/user/{user_id}"
        resp = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return GenericListResponse(items=data if isinstance(data, list) else [data])

    # Device Code Flow
    def initialize_auth(
        self,
        account_name: str
    ) -> AuthInitializeResponse:
        """
        Инициализировать процесс авторизации Device Code Flow для указанного аккаунта.
        """
        url = f"{self.base_url}/auth/initialize"
        payload = {"account_name": account_name}
        resp = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return AuthInitializeResponse(**data)

    def check_auth_status(
        self,
        device_code: str,
        account_name: str
    ) -> AuthStatusResponse:
        """
        Проверить статус авторизации Device Code Flow.
        """
        url = f"{self.base_url}/auth/status"
        payload = {"device_code": device_code, "account_name": account_name}
        resp = requests.post(url, json=payload, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return AuthStatusResponse(**data)

    def validate_and_refresh_token(
        self,
        token_id: UUID
    ) -> TokenResponse:
        """
        Проверить и при необходимости обновить токен.
        """
        url = f"{self.base_url}/{token_id}/validate"
        resp = requests.post(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return TokenResponse(**data)

    def get_auth_task_status(
        self,
        task_id: str
    ) -> TaskStatusResponse:
        """
        Получить статус задачи Celery по ID.
        """
        url = f"{self.base_url}/auth/task/{task_id}"
        resp = requests.get(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return TaskStatusResponse(**data)
