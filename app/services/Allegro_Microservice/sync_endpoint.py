import requests
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

from app.core.config import settings
from app.services.Allegro_Microservice.base import BaseClient


class SyncClient(BaseClient):
    """
    Клиент для работы с API синхронизации заказов.
    """
    def __init__(
        self,
        jwt_token: str,
        base_url: Optional[str] = None,
        timeout: Optional[int] = 10
    ):
        super().__init__(jwt_token, base_url, timeout)
        self.sync_url = f"{self.base_url}/api/v1/sync"

    def start_sync(
        self,
        token_id: UUID,
        sync_from_date: Optional[datetime] = None,
        force_full_sync: bool = False
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "token_id": str(token_id),
            "force_full_sync": force_full_sync
        }
        if sync_from_date:
            payload["sync_from_date"] = sync_from_date.isoformat()

        resp = requests.post(
            f"{self.sync_url}/start",
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_sync_history(
        self,
        page: int = 1,
        per_page: int = 10,
        token_id: Optional[UUID] = None,
        status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        if token_id:
            params["token_id"] = str(token_id)
        if status:
            params["status"] = status
        if date_from:
            params["date_from"] = date_from.isoformat()
        if date_to:
            params["date_to"] = date_to.isoformat()

        resp = requests.get(
            f"{self.sync_url}/history",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_sync_status(self, sync_id: UUID) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.sync_url}/status/{sync_id}",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_sync(self, sync_id: UUID) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.sync_url}/cancel/{sync_id}",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_sync_stats(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from.isoformat()
        if date_to:
            params["date_to"] = date_to.isoformat()

        resp = requests.get(
            f"{self.sync_url}/stats",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_running_syncs(self) -> List[Dict[str, Any]]:
        resp = requests.get(
            f"{self.sync_url}/running",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.sync_url}/task/{task_id}",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_tasks_history(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if task_type:
            params["task_type"] = task_type

        resp = requests.get(
            f"{self.sync_url}/tasks/history",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_active_tasks(self) -> List[Dict[str, Any]]:
        resp = requests.get(
            f"{self.sync_url}/tasks/active",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_task_details(self, task_id: str) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.sync_url}/tasks/{task_id}",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def revoke_task(self, task_id: str) -> Dict[str, Any]:
        payload = {"task_id": task_id}
        resp = requests.post(
            f"{self.sync_url}/tasks/revoke",
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.sync_url}/tasks/{task_id}/result",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def activate_sync(self, token_id: UUID, interval_minutes: int) -> Dict[str, Any]:
        payload = {"token_id": str(token_id), "interval_minutes": interval_minutes}
        resp = requests.post(
            f"{self.sync_url}/activate",
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def deactivate_sync(self, token_id: UUID) -> Dict[str, Any]:
        payload = {"token_id": str(token_id)}
        resp = requests.post(
            f"{self.sync_url}/deactivate",
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_active_syncs(self) -> List[Dict[str, Any]]:
        resp = requests.get(
            f"{self.sync_url}/active",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def get_token_sync_status(self, token_id: UUID) -> Dict[str, Any]:
        """
        Получить статус автосинхронизации для конкретного токена.
        """
        resp = requests.get(
            f"{self.sync_url}/status/{token_id}",
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()
