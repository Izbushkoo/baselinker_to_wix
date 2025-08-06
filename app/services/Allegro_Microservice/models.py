from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, RootModel

# Orders microservice models
class OrderStatistics(BaseModel):
    period_days: int
    total_orders: int
    recent_orders: int
    status_distribution: Dict[str, int]
    financial: Dict[str, Any]
    top_buyers: List[Dict[str, Any]]
    generated_at: str

class SyncResult(BaseModel):
    success: bool
    order_id: str
    action: str
    message: str

class SyncHistory(BaseModel):
    history: List[Dict[str, Any]]
    total_records: int

class DataQualityReport(BaseModel):
    health_metrics: Dict[str, Any]
    quality_report: Dict[str, Any]
    generated_at: str

class OrderEventsResponse(BaseModel):
    events: List[Dict[str, Any]]
    total_count: int
    has_more: bool
    error: Optional[str] = None

class Pagination(BaseModel):
    total: int
    offset: int
    limit: int

class OrdersListResponse(BaseModel):
    orders: List[Dict[str, Any]]
    pagination: Pagination

class OrderDetailResponse(BaseModel):
    order: Dict[str, Any]

class OrderTechnicalFlags(BaseModel):
    order_id: str
    technical_flags: Dict[str, Any]

class TechnicalFlagsSummary(BaseModel):
    token_id: str
    summary: Dict[str, Any]
    generated_at: str

class OrderStatusUpdate(BaseModel):
    success: bool
    order_id: str
    is_stock_updated: bool
    updated_at: str
    message: str

class InvoiceStatusUpdate(BaseModel):
    success: bool
    order_id: str
    has_invoice_created: bool
    invoice_id: Optional[str] = None
    updated_at: str
    message: str

# Sync microservice models
class SyncTrigger(BaseModel):
    token_id: UUID
    sync_from_date: Optional[datetime]
    force_full_sync: bool = False

class SyncResponse(BaseModel):
    id: UUID
    token_id: UUID
    sync_started_at: datetime
    sync_completed_at: Optional[datetime]
    sync_status: str
    orders_processed: int
    orders_added: int
    orders_updated: int
    error_message: Optional[str] = None
    sync_from_date: Optional[datetime] = None
    sync_to_date: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class SyncListResponse(BaseModel):
    syncs: List[SyncResponse]
    total: int
    page: int
    per_page: int

class SyncStats(BaseModel):
    total_syncs: int
    successful_syncs: int
    failed_syncs: int
    running_syncs: int
    total_orders_processed: int
    total_orders_added: int
    total_orders_updated: int
    last_sync_date: Optional[datetime] = None
    average_sync_duration: Optional[float] = None

class SyncTaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    started_at: datetime

class TaskHistoryRead(BaseModel):
    id: UUID
    task_id: str
    user_id: str
    task_type: str
    status: str
    params: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    updated_at: datetime
    description: Optional[str] = None
    progress: Optional[float] = None
    parent_task_id: Optional[str] = None

    class Config:
        from_attributes = True

class ActivateSyncRequest(BaseModel):
    token_id: UUID
    interval_minutes: int

class DeactivateSyncRequest(BaseModel):
    token_id: UUID

class TokenSyncStatusResponse(BaseModel):
    token_id: str
    is_active: bool
    interval_minutes: Optional[int] = None
    status: Optional[str] = None
    task_name: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# Tokens microservice models
class TokenCreate(BaseModel):
    account_name: str
    allegro_token: str
    refresh_token: str
    expires_at: datetime

class TokenResponse(BaseModel):
    id: UUID
    user_id: str
    account_name: str
    expires_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

class TokenUpdate(BaseModel):
    account_name: Optional[str] = None
    allegro_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None

class TokenListResponse(BaseModel):
    tokens: List[TokenResponse]
    total: int
    page: int
    per_page: int

class AuthInitializeRequest(BaseModel):
    account_name: str

class AuthInitializeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    expires_in: int
    interval: int
    task_id: str

class AuthStatusRequest(BaseModel):
    device_code: str
    account_name: str

class AuthStatusResponse(BaseModel):
    status: str
    message: Optional[str] = None

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    progress: Optional[Dict[str, Any]] = None

# Offers microservice models
class OfferListResponse(BaseModel):
    offers: List[Dict[str, Any]]
    total_count: Optional[int] = None
    success: bool = True
    error: Optional[str] = None

class MicroserviceOfferResponse(BaseModel):
    offer: Dict[str, Any]
    success: bool = True
    error: Optional[str] = None

# Generic response models
class GenericResponse(BaseModel):
    data: Dict[str, Any]
    success: bool = True
    message: Optional[str] = None

class GenericListResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: Optional[int] = None
    page: Optional[int] = None
    per_page: Optional[int] = None
    success: bool = True