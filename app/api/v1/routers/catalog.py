"""
 * @file: catalog.py
 * @description: Роутер для нового каталога товаров
 * @dependencies: models, services, templates
 * @created: 2024-12-19
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import or_, and_
from fastapi.templating import Jinja2Templates
from app.api import deps
from app.models.warehouse import Product, Stock
from app.models.user import User
from app.services.warehouse.manager import Warehouses
from app.services.prices_service import prices_service
import logging
import base64

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
async def catalog_page(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    stock_filter: Optional[int] = None,
    min_stock_filter: Optional[int] = None,
    brand_filter: Optional[str] = None,
    sort_order: Optional[str] = None,
    operation_skus: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Главная страница нового каталога товаров
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/catalog", status_code=302)

    # Логирование параметров запроса
    logger.info(f"New catalog request: search={search}, stock_filter={stock_filter}, min_stock_filter={min_stock_filter}, brand_filter={brand_filter}")

    # Валидация и автоматическая коррекция фильтров
    if (stock_filter is not None and min_stock_filter is not None and 
        stock_filter < min_stock_filter):
        stock_filter, min_stock_filter = min_stock_filter, stock_filter

    # Базовый запрос для товаров с подсчетом остатков
    base_query = (
        select(
            Product,
            func.sum(Stock.quantity).label('total_stock')
        )
        .outerjoin(Stock, Stock.sku == Product.sku)
        .group_by(Product.sku)
    )
    
    # Поиск по названию, SKU или EAN
    if search:
        name_sku_search = f"%{search}%"
        base_query = base_query.where(
            or_(
                Product.name.ilike(name_sku_search),
                Product.sku.ilike(name_sku_search),
                Product.eans.contains([search])
            )
        )

    # Фильтр по SKU операции (приоритетный фильтр)
    if operation_skus:
        sku_list = [sku.strip() for sku in operation_skus.split(',') if sku.strip()]
        if sku_list:
            base_query = base_query.where(Product.sku.in_(sku_list))

    # Собираем условия фильтров по количеству
    having_conditions = []

    # Фильтр по максимальному количеству
    if stock_filter is not None:
        having_conditions.append(func.coalesce(func.sum(Stock.quantity), 0) < stock_filter)

    # Фильтр по минимальному количеству
    if min_stock_filter is not None:
        having_conditions.append(func.coalesce(func.sum(Stock.quantity), 0) >= min_stock_filter)

    # Применяем условия, если они есть
    if having_conditions:
        base_query = base_query.having(and_(*having_conditions))

    # Фильтр по бренду
    if brand_filter:
        base_query = base_query.where(Product.brand == brand_filter)

    # Создаем подзапрос для корректного подсчета общего количества
    subquery = base_query.subquery()
    
    # Получаем общее количество товаров для пагинации
    total_count_query = select(func.count()).select_from(subquery)
    result = await db.exec(total_count_query)
    total_count = result.first()
    total_pages = (total_count + page_size - 1) // page_size

    # Основной запрос с сортировкой
    query = (
        select(Product, subquery.c.total_stock)
        .join(subquery, Product.sku == subquery.c.sku)
    )

    # Применяем сортировку
    if sort_order == 'desc':
        query = query.order_by(func.coalesce(subquery.c.total_stock, 0).desc(), Product.sku.asc())
    else:
        # По умолчанию и для sort_order == 'asc' сортируем по возрастанию остатков
        query = query.order_by(func.coalesce(subquery.c.total_stock, 0).asc(), Product.sku.asc())

    # Применяем пагинацию
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    # Получаем товары
    result = await db.exec(query)
    products = result.all()

    # Создаем список продуктов с их остатками
    products_with_stocks = []
    for row in products:
        product = row[0]  # Получаем объект Product
        total_stock = row[1] or 0  # Получаем total_stock
        
        # Получаем остатки для продукта
        stocks_query = select(Stock).where(Stock.sku == product.sku)
        result = await db.exec(stocks_query)
        stocks = result.all()
        
        # Создаем словарь с данными продукта
        product_data = {
            "id": product.sku,
            "sku": product.sku,
            "name": product.name,
            "brand": product.brand,
            "eans": product.eans,
            "ean": product.eans[0] if product.eans else None,
            "image": base64.b64encode(product.image).decode('utf-8') if product.image else None,
            "total_stock": total_stock,
            "stocks": {}
        }
        
        # Инициализируем остатки для всех складов как 0
        for warehouse in Warehouses:
            product_data["stocks"][warehouse.value] = 0
            
        # Заполняем фактические остатки
        for stock in stocks:
            product_data["stocks"][stock.warehouse] = stock.quantity
        
        products_with_stocks.append(product_data)

    # Обогащаем данные о товарах ценами из удаленной БД
    if prices_service.is_available() and products_with_stocks:
        try:
            # Получаем все SKU товаров
            skus = [product["sku"] for product in products_with_stocks]
            
            # Получаем цены для всех SKU одним запросом
            prices_data = prices_service.get_prices_by_skus(skus)
            
            # Добавляем цены к данным товаров
            for product_data in products_with_stocks:
                sku = product_data["sku"]
                price_info = prices_data.get(sku)
                if price_info:
                    product_data["min_price"] = price_info.min_price
                else:
                    product_data["min_price"] = None
        except Exception as e:
            logger.error(f"Error getting prices: {str(e)}")
            # Если не удалось получить цены, добавляем пустые значения
            for product_data in products_with_stocks:
                product_data["min_price"] = None

    # Для обычных запросов возвращаем HTML-страницу
    warehouses = [w.value for w in Warehouses]
    
    return templates.TemplateResponse(
        "catalog_new.html",
        {
            "request": request,
            "user": current_user,
            "products": products_with_stocks,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "warehouses": warehouses,
            "current_user": current_user,
            "filters": {
                "search": search or "",
                "stock_filter": stock_filter,
                "min_stock_filter": min_stock_filter,
                "brand_filter": brand_filter or "",
                "sort_order": sort_order or "",
                "page_size": page_size
            }
        }
    )

@router.get("/api/products")
async def get_products_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    stock_filter: Optional[int] = None,
    min_stock_filter: Optional[int] = None,
    brand_filter: Optional[str] = None,
    sort_order: Optional[str] = None,
    operation_skus: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    API эндпоинт для получения товаров в формате JSON
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")

    # Логирование параметров запроса
    logger.info(f"Catalog API request: search={search}, stock_filter={stock_filter}, min_stock_filter={min_stock_filter}, brand_filter={brand_filter}")

    # Валидация и автоматическая коррекция фильтров
    if (stock_filter is not None and min_stock_filter is not None and 
        stock_filter < min_stock_filter):
        stock_filter, min_stock_filter = min_stock_filter, stock_filter

    # Базовый запрос для товаров с подсчетом остатков
    base_query = (
        select(
            Product,
            func.sum(Stock.quantity).label('total_stock')
        )
        .outerjoin(Stock, Stock.sku == Product.sku)
        .group_by(Product.sku)
    )
    
    # Поиск по названию, SKU или EAN
    if search:
        name_sku_search = f"%{search}%"
        base_query = base_query.where(
            or_(
                Product.name.ilike(name_sku_search),
                Product.sku.ilike(name_sku_search),
                Product.eans.contains([search])
            )
        )

    # Фильтр по SKU операции (приоритетный фильтр)
    if operation_skus:
        sku_list = [sku.strip() for sku in operation_skus.split(',') if sku.strip()]
        if sku_list:
            base_query = base_query.where(Product.sku.in_(sku_list))

    # Собираем условия фильтров по количеству
    having_conditions = []

    # Фильтр по максимальному количеству
    if stock_filter is not None:
        having_conditions.append(func.coalesce(func.sum(Stock.quantity), 0) < stock_filter)

    # Фильтр по минимальному количеству
    if min_stock_filter is not None:
        having_conditions.append(func.coalesce(func.sum(Stock.quantity), 0) >= min_stock_filter)

    # Применяем условия, если они есть
    if having_conditions:
        base_query = base_query.having(and_(*having_conditions))

    # Фильтр по бренду
    if brand_filter:
        base_query = base_query.where(Product.brand == brand_filter)

    # Создаем подзапрос для корректного подсчета общего количества
    subquery = base_query.subquery()
    
    # Получаем общее количество товаров для пагинации
    total_count_query = select(func.count()).select_from(subquery)
    result = await db.exec(total_count_query)
    total_count = result.first()
    total_pages = (total_count + page_size - 1) // page_size

    # Основной запрос с сортировкой
    query = (
        select(Product, subquery.c.total_stock)
        .join(subquery, Product.sku == subquery.c.sku)
    )

    # Применяем сортировку
    if sort_order == 'desc':
        query = query.order_by(func.coalesce(subquery.c.total_stock, 0).desc(), Product.sku.asc())
    else:
        # По умолчанию и для sort_order == 'asc' сортируем по возрастанию остатков
        query = query.order_by(func.coalesce(subquery.c.total_stock, 0).asc(), Product.sku.asc())

    # Применяем пагинацию
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    # Получаем товары
    result = await db.exec(query)
    products = result.all()

    # Создаем список продуктов с их остатками
    products_with_stocks = []
    for row in products:
        product = row[0]  # Получаем объект Product
        total_stock = row[1] or 0  # Получаем total_stock
        
        # Получаем остатки для продукта
        stocks_query = select(Stock).where(Stock.sku == product.sku)
        result = await db.exec(stocks_query)
        stocks = result.all()
        
        # Создаем словарь с данными продукта
        product_data = {
            "id": product.sku,
            "sku": product.sku,
            "name": product.name,
            "brand": product.brand,
            "eans": product.eans,
            "ean": product.eans[0] if product.eans else None,
            "image": base64.b64encode(product.image).decode('utf-8') if product.image else None,
            "total_stock": total_stock,
            "stocks": {}
        }
        
        # Инициализируем остатки для всех складов как 0
        for warehouse in Warehouses:
            product_data["stocks"][warehouse.value] = 0
            
        # Заполняем фактические остатки
        for stock in stocks:
            product_data["stocks"][stock.warehouse] = stock.quantity
        
        products_with_stocks.append(product_data)

    # Обогащаем данные о товарах ценами из удаленной БД
    if prices_service.is_available() and products_with_stocks:
        try:
            # Получаем все SKU товаров
            skus = [product["sku"] for product in products_with_stocks]
            
            # Получаем цены для всех SKU одним запросом
            prices_data = prices_service.get_prices_by_skus(skus)
            
            # Добавляем цены к данным товаров
            for product_data in products_with_stocks:
                sku = product_data["sku"]
                price_info = prices_data.get(sku)
                if price_info:
                    product_data["min_price"] = price_info.min_price
                else:
                    product_data["min_price"] = None
        except Exception as e:
            logger.error(f"Error getting prices: {str(e)}")
            # Если не удалось получить цены, добавляем пустые значения
            for product_data in products_with_stocks:
                product_data["min_price"] = None

    # Для AJAX-запросов генерируем HTML для каждой карточки
    products_response = []
    for product_data in products_with_stocks:
        html = templates.get_template("components/product_card.html").render(
            product=product_data,
            selected_products=[],
            current_user=current_user
        )
        products_response.append({
            "data": product_data,
            "html": html
        })

    return {
        "products": products_response,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

@router.get("/api/brands")
async def get_brands_api(
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    API эндпоинт для получения списка брендов
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    try:
        # Получаем уникальные бренды, исключая NULL значения
        query = select(Product.brand).where(Product.brand.is_not(None)).distinct().order_by(Product.brand)
        result = await db.exec(query)
        brands = result.all()
        
        # Возвращаем список брендов
        return {"brands": [brand for brand in brands if brand and brand.strip()]}
    except Exception as e:
        logger.error(f"Ошибка при получении списка брендов: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось получить список брендов: {str(e)}"
        )
