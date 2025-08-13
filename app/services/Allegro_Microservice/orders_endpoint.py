import requests
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime

from app.core.config import settings
from app.services.Allegro_Microservice.base import BaseClient
from app.services.Allegro_Microservice.models import (
    OrdersListResponse,
    OrderStatistics,
    OrderEventsResponse,
    SyncHistory,
    SyncResult,
    DataQualityReport,
    OrderTechnicalFlags,
    TechnicalFlagsSummary,
    OrderStatusUpdate,
    InvoiceStatusUpdate,
    GenericResponse
)

class OrdersClient(BaseClient):
    """
    Клиент для работы с API заказов Allegro.
    """
    def __init__(
        self,
        jwt_token: str,
        base_url: Optional[str] = None,
        timeout: Optional[int] = 10
    ):
        super().__init__(jwt_token, base_url, timeout)
        self.orders_url = f"{self.base_url}/api/v1/orders"

    def get_orders(
        self,
        token_id: UUID,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        stock_updated: Optional[bool] = None,
        invoice_created: Optional[bool] = None,
        invoice_id: Optional[str] = None
    ) -> OrdersListResponse:
        params: Dict[str, Any] = {"token_id": str(token_id), "limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if from_date:
            params["from_date"] = from_date.isoformat()
        if to_date:
            params["to_date"] = to_date.isoformat()
        if stock_updated is not None:
            params["stock_updated"] = stock_updated
        if invoice_created is not None:
            params["invoice_created"] = invoice_created
        if invoice_id:
            params["invoice_id"] = invoice_id
        resp = requests.get(
            f"{self.orders_url}/",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrdersListResponse(**data)

    def search_orders(
        self,
        token_id: UUID,
        query: str,
        limit: int = 50,
        stock_updated: Optional[bool] = None,
        invoice_created: Optional[bool] = None,
        invoice_id: Optional[str] = None
    ) -> OrdersListResponse:
        params = {"token_id": str(token_id), "query": query, "limit": limit}
        if stock_updated is not None:
            params["stock_updated"] = stock_updated
        if invoice_created is not None:
            params["invoice_created"] = invoice_created
        if invoice_id:
            params["invoice_id"] = invoice_id
        resp = requests.get(
            f"{self.orders_url}/search",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrdersListResponse(**data)

    def get_orders_statistics(
        self,
        token_id: UUID,
        days: int = 30
    ) -> OrderStatistics:
        params = {"token_id": str(token_id), "days": days}
        resp = requests.get(
            f"{self.orders_url}/statistics",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderStatistics(**data)

    def get_order_events(
        self,
        token_id: UUID,
        limit: int = 100,
        from_timestamp: Optional[datetime] = None
    ) -> OrderEventsResponse:
        params: Dict[str, Any] = {"token_id": str(token_id), "limit": limit}
        if from_timestamp:
            params["from_timestamp"] = from_timestamp.isoformat()
        resp = requests.get(
            f"{self.orders_url}/events",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderEventsResponse(**data)

    def get_sync_history(
        self,
        token_id: UUID,
        limit: int = 50
    ) -> SyncHistory:
        params = {"token_id": str(token_id), "limit": limit}
        resp = requests.get(
            f"{self.orders_url}/sync/history",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return SyncHistory(**data)

    def get_data_quality_report(
        self,
        token_id: UUID
    ) -> DataQualityReport:
        params = {"token_id": str(token_id)}
        resp = requests.get(
            f"{self.orders_url}/data-quality",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return DataQualityReport(**data)

    def get_order_by_id(
        self,
        token_id: UUID,
        order_id: str
    ) -> OrdersListResponse:
        params = {"token_id": str(token_id)}
        resp = requests.get(
            f"{self.orders_url}/{order_id}",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrdersListResponse(**data)

    def sync_single_order(
        self,
        token_id: UUID,
        order_id: str
    ) -> SyncResult:
        params = {"token_id": str(token_id)}
        resp = requests.post(
            f"{self.orders_url}/{order_id}/sync",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return SyncResult(**data)

    def get_available_statuses(
        self,
        token_id: UUID
    ) -> GenericResponse:
        params = {"token_id": str(token_id)}
        resp = requests.get(
            f"{self.orders_url}/debug/statuses",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return GenericResponse(data=data)

    def get_orders_health(
        self,
        token_id: UUID
    ) -> GenericResponse:
        params = {"token_id": str(token_id)}
        resp = requests.get(
            f"{self.orders_url}/debug/health",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return GenericResponse(data=data)

    def update_stock_status(
        self,
        token_id: UUID,
        order_id: str,
        is_stock_updated: bool
    ) -> OrderStatusUpdate:
        params = {"token_id": str(token_id)}
        payload = {"is_stock_updated": is_stock_updated}
        resp = requests.patch(
            f"{self.orders_url}/{order_id}/stock-status",
            params=params,
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderStatusUpdate(**data)

    def update_invoice_status(
        self,
        token_id: UUID,
        order_id: str,
        has_invoice_created: bool,
        invoice_id: Optional[str] = None
    ) -> InvoiceStatusUpdate:
        params = {"token_id": str(token_id)}
        payload: Dict[str, Any] = {"has_invoice_created": has_invoice_created}
        if invoice_id is not None:
            payload["invoice_id"] = invoice_id
        resp = requests.patch(
            f"{self.orders_url}/{order_id}/invoice-status",
            params=params,
            json=payload,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return InvoiceStatusUpdate(**data)

    def get_order_technical_flags(
        self,
        token_id: UUID,
        order_id: str
    ) -> OrderTechnicalFlags:
        params = {"token_id": str(token_id)}
        resp = requests.get(
            f"{self.orders_url}/{order_id}/technical-flags",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return OrderTechnicalFlags(**data)

    def get_technical_flags_summary(
        self,
        token_id: UUID
    ) -> TechnicalFlagsSummary:
        params = {"token_id": str(token_id)}
        resp = requests.get(
            f"{self.orders_url}/technical-flags/summary",
            params=params,
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return TechnicalFlagsSummary(**data)
