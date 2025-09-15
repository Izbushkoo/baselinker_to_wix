from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID


class ExternalStockUpdateRequest(BaseModel):
    """
    Модель для запроса обновления запаса по external_id
    """
    external_id: str
    stock: int
    
    class Config:
        from_attributes = True


class SingleTokenStockUpdateRequest(BaseModel):
    """
    Модель для запроса обновления запаса оффера для конкретного токена
    """
    token_id: str = Field(..., description="ID токена для обновления запаса")
    external_id: str = Field(..., description="External ID оффера (SKU)")
    stock: int = Field(..., ge=0, description="Новый запас товара")
    
    class Config:
        from_attributes = True


class OfferUpdateResult(BaseModel):
    """
    Результат обновления одного оффера
    """
    offer_id: str = Field(..., description="ID оффера")
    updated: bool = Field(..., description="Был ли оффер обновлен")
    old_stock: Optional[int] = Field(None, description="Старый запас")
    new_stock: Optional[int] = Field(None, description="Новый запас")
    note: Optional[str] = Field(None, description="Примечание")
    error: Optional[str] = Field(None, description="Ошибка при обновлении")
    result: Optional[dict] = Field(None, description="Результат обновления")


class SingleTokenStockUpdateResponse(BaseModel):
    """
    Модель ответа на запрос обновления запаса оффера для конкретного токена
    """
    token_id: str = Field(..., description="ID токена")
    account_name: str = Field(..., description="Название аккаунта")
    external_id: str = Field(..., description="External ID оффера")
    requested_stock: int = Field(..., description="Запрашиваемый запас")
    offers: List[OfferUpdateResult] = Field(..., description="Результаты обновления офферов")
    total_offers: int = Field(..., description="Общее количество офферов")
    updated_offers: int = Field(..., description="Количество обновленных офферов")
    success: bool = Field(True, description="Успешность операции")
    
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