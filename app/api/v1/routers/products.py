from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import StreamingResponse
import io
import pandas as pd
import base64
from sqlalchemy import or_, text, bindparam
from fastapi.templating import Jinja2Templates
from app.api import deps
from app.models.werehouse import Product, Stock
from app.models.user import User

router = APIRouter()
web_router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@web_router.get("/catalog")
async def catalog(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    # Получаем общее количество товаров
    total_count_query = select(func.count()).select_from(Product)
    result = await db.exec(total_count_query)
    total_products = result.first()
    total_pages = (total_products + page_size - 1) // page_size

    # Получаем товары с пагинацией, сортируя по остаткам
    subquery = (
        select(
            Product,
            func.sum(Stock.quantity).label('total_stock')
        )
        .outerjoin(Stock, Stock.sku == Product.sku)
        .group_by(Product.sku)
        .subquery()
    )
    
    products_query = (
        select(Product, subquery.c.total_stock)
        .join(subquery, Product.sku == subquery.c.sku)
        .order_by(subquery.c.total_stock)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    result = await db.exec(products_query)
    products = result.all()

    # Создаем список продуктов с их остатками
    products_with_stocks = []
    for row in products:
        product = row[0]  # Получаем объект Product
        total_stock = row[1]  # Получаем total_stock
        
        # Получаем остатки для продукта
        stocks_query = select(Stock).where(Stock.sku == product.sku)
        result = await db.exec(stocks_query)
        stocks = result.all()
        
        # Создаем словарь с данными продукта
        product_data = {
            "id": product.sku,  # используем SKU как ID
            "sku": product.sku,
            "name": product.name,
            "eans": product.eans,
            "ean": product.eans[0] if product.eans else None,
            "image": base64.b64encode(product.image).decode('utf-8') if product.image else None,
            "warehouse": next((s.warehouse for s in stocks if s.quantity > 0), None),
            "total_stock": total_stock or 0
        }
        products_with_stocks.append(product_data)

    # Получаем список уникальных складов
    warehouses_query = select(Stock.warehouse).distinct()
    result = await db.exec(warehouses_query)
    warehouses = [w[0] for w in result.all()]

    return templates.TemplateResponse(
        "catalog.html",
        {
            "request": request,
            "user": current_user,
            "products": products_with_stocks,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "warehouses": warehouses
        }
    )

@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """
    Получение списка товаров с фильтрацией и пагинацией
    """
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

    # Создаем подзапрос для корректного подсчета общего количества
    subquery = base_query.subquery()
    
    # Получаем общее количество товаров для пагинации
    total_count_query = select(func.count()).select_from(subquery)
    result = await db.exec(total_count_query)
    total_count = result.first()

    # Применяем сортировку по остаткам и пагинацию
    query = (
        select(Product, subquery.c.total_stock)
        .join(subquery, Product.sku == subquery.c.sku)
        .order_by(subquery.c.total_stock)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    # Получаем товары
    result = await db.exec(query)
    products = result.all()

    # Создаем список продуктов с их остатками
    products_with_stocks = []
    for row in products:
        product = row[0]  # Получаем объект Product
        total_stock = row[1]  # Получаем total_stock
        
        # Получаем остатки для продукта
        stocks_query = select(Stock).where(Stock.sku == product.sku)
        result = await db.exec(stocks_query)
        stocks = result.all()
        
        # Создаем словарь с данными продукта
        product_data = {
            "id": product.sku,
            "sku": product.sku,
            "name": product.name,
            "ean": product.eans[0] if product.eans else None,
            "image": base64.b64encode(product.image).decode('utf-8') if product.image else None,
            "warehouse": next((s.warehouse for s in stocks if s.quantity > 0), None),
            "total_stock": total_stock or 0
        }
        
        # Генерируем HTML для карточки товара
        html = templates.get_template("components/product_card.html").render(
            product=product_data,
            selected_products=[]
        )
        
        products_with_stocks.append({
            "data": product_data,
            "html": html
        })

    return {
        "products": products_with_stocks,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }

@router.post("/export")
async def export_products(
    skus: List[str],
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """
    Экспорт выбранных товаров в Excel
    """
    # Получаем товары
    query = select(Product).where(Product.sku.in_(skus))
    result = await db.exec(query)
    products = result.all()

    # Получаем остатки
    for product in products:
        stock_query = select(Stock).where(Stock.sku == product.sku)
        result = await db.exec(stock_query)
        product.stocks = result.all()

    # Создаем DataFrame
    data = []
    for product in products:
        row = {
            'SKU': product.sku,
            'Название': product.name,
            'EAN': ', '.join(product.eans),
        }
        # Добавляем остатки по складам
        for stock in product.stocks:
            row[f'Остаток {stock.warehouse}'] = stock.quantity
        data.append(row)

    df = pd.DataFrame(data)

    # Создаем Excel файл
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=products_export.xlsx'}
    )