from pydantic import BaseModel
from typing import Optional


class ExternalStockUpdateRequest(BaseModel):
    """
    Модель для запроса обновления запаса по external_id
    """
    external_id: str
    stock: int
    
    class Config:
        from_attributes = True


class OfferResponse(BaseModel):
    """
    Модель ответа от Allegro API с информацией об оффере
    """
    id: str
    name: Optional[str] = None
    external_id: Optional[str] = None
    status: Optional[str] = None
    stock: Optional[dict] = None
    price: Optional[dict] = None
    
    class Config:
        from_attributes = True