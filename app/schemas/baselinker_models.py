from typing import List, Dict

from pydantic import BaseModel


class Inventory(BaseModel):
    inventory_id: int
    name: str
    description: str
    languages: List[str]
    default_language: str


class Product(BaseModel):
    id: int
    ean: str
    sku: str
    name: str


class DetailedProduct(BaseModel):
    ean: str
    sku: str
    weight: float
    stock: int  # Например, можно преобразовать словарь в список кортежей (ключ, значение)
    name: str
    description: str
    brand: str
    images: List[str]
    price: float
