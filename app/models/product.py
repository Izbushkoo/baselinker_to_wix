from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    sku: str = Field(..., min_length=1, max_length=50)
    ean: Optional[str] = Field(None, max_length=13)
    price: Decimal = Field(..., ge=0)
    quantity: int = Field(..., ge=0)
    description: Optional[str] = None

class ProductResponse(ProductCreate):
    id: int
    class Config:
        from_attributes = True 