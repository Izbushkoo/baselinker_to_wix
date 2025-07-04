import os
import requests
from typing import List
from bs4 import BeautifulSoup
from app.schemas.baselinker_models import DetailedProduct
from app.schemas.wix_models import WixImportFileModel
import csv


def process_description(html: str) -> (str, List[str]):
    """
    Обрабатывает HTML-описание:
      - извлекает все ссылки на изображения,
      - удаляет блоки с изображениями (например, элементы с классом "image-item").
    """
    soup = BeautifulSoup(html, "html.parser")
    image_links = []

    # Извлекаем все ссылки из <img> тегов
    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            image_links.append(src)

    # Удаляем блоки с изображениями. В данном примере — элементы с классом "image-item"
    for image_block in soup.find_all(class_="image-item"):
        image_block.decompose()

    processed_html = str(soup)
    return processed_html, image_links


# # Пример Pydantic-модели для продукта
# class DetailedProduct(BaseModel):
#     ean: str
#     sku: str
#     weight: float
#     stock: int  # Например, можно преобразовать словарь в список кортежей (ключ, значение)
#     name: str
#     description: str
#     brand: str
#     images: List[str]
#     price: float


def transform_product(server_product: dict, lang_code: str = "en") -> DetailedProduct:
    """
    Преобразует данные продукта из ответа сервера в модель DetailedProduct,
    обрабатывая поле "description|en" в text_fields.
    """
    ean = server_product.get("ean", "")
    sku = server_product.get("sku", "")
    # Преобразуем словарь stock в список пар [(key, value), ...]
    # stock = list(server_product.get("stock", {}).items())
    stock = next(iter(server_product.get("stock", {}).values()), 0)

    text_fields = server_product.get("text_fields", {})
    images_dict = server_product.get("images", {})
    images = list(images_dict.values())
    prices = server_product.get("prices", {})
    price = get_max_price(prices)


    # Обработка поля "description|en" — извлекаем описание, удаляем блоки с изображениями и сохраняем ссылки
    description_html = text_fields.get(f"description", "")

    # if not description_html:
    #     lang_code = "pl"

    processed_description, extracted_image_links = process_description(description_html)
    description = processed_description
    features = text_fields.get(f"features")
    
    name = text_fields.get(f"name", "")
    weight = server_product.get("weight", 0)
    if weight == 0:
        weight = features.get("Weight (with packaging)", 0)
    brand = features.get("Marka", "")
    # Если нужно, можно добавить извлечённые ссылки в список изображений
    images.extend(extracted_image_links)

    # Удаляем дубликаты изображений
    images = list(set(images))

    # Ограничиваем количество изображений до 15
    images = images[:15]


    return DetailedProduct(
        ean=ean,
        sku=sku,
        name=name,
        weight=weight,
        stock=stock,
        description=description,
        brand=brand,
        images=images,
        price=price
    )

def transform_product_for_shoper(server_product: dict, lang_code: str = "en") -> DetailedProduct:
    """
    Преобразует данные продукта из ответа сервера в модель DetailedProduct,
    обрабатывая поле "description|en" в text_fields.
    """
    ean = server_product.get("ean", "")
    sku = server_product.get("sku", "")
    # Преобразуем словарь stock в список пар [(key, value), ...]
    # stock = list(server_product.get("stock", {}).items())
    stock = next(iter(server_product.get("stock", {}).values()), 0)

    text_fields = server_product.get("text_fields", {})
    images_dict = server_product.get("images", {})
    images = list(images_dict.values())
    prices = server_product.get("prices", {})
    price = get_max_price(prices)


    # Обработка поля "description|en" — извлекаем описание, удаляем блоки с изображениями и сохраняем ссылки
    description_html = text_fields.get(f"description", "")

    # if not description_html:
    #     lang_code = "pl"

    processed_description, extracted_image_links = process_description(description_html)
    description = processed_description
    
    name = text_fields.get(f"name", "")
    weight = server_product.get("weight", 0)

    brand = "a1mate"
    # Если нужно, можно добавить извлечённые ссылки в список изображений
    images.extend(extracted_image_links)

    # Удаляем дубликаты изображений
    images = list(set(images))

    # Ограничиваем количество изображений до 15
    images = images[:15]


    return DetailedProduct(
        ean=ean,
        sku=sku,
        name=name,
        weight=weight,
        stock=stock,
        description=description,
        brand=brand,
        images=images,
        price=price
    )

def first_value(data: dict):
    """
    Возвращает первое значение из словаря.
    Если словарь пустой, возвращает None.
    """
    if not data:
        return None
    return next(iter(data.values()))


def get_first_stock(stock_dict: dict) -> int:
    value = first_value(stock_dict)
    return value if value is not None else 0

def get_first_price(prices_dict: dict) -> float:
    value = first_value(prices_dict)
    return value if value is not None else 0.0

def get_max_price(prices_dict: dict) -> float:
    """
    Возвращает максимальное значение цены из словаря.
    Если словарь пустой, возвращает 0.0.
    """
    if not prices_dict:
        return 0.0
    return max(prices_dict.values())



# Пример использования
if __name__ == "__main__":
    ...