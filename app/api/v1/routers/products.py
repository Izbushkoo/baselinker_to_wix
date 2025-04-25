from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request, File, UploadFile, Form
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
import io
import pandas as pd
import base64
from sqlalchemy import or_, text, bindparam
from fastapi.templating import Jinja2Templates
from app.api import deps
from app.models.warehouse import Product, Stock
from app.models.user import User
from app.services.warehouse.manager import Warehouses

router = APIRouter()
web_router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@web_router.get("/catalog")
async def catalog(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Отображение каталога товаров с пагинацией
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/catalog", status_code=302)

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
        total_stock = row[1] or 0  # Получаем total_stock, используем 0 если None
        
        # Получаем остатки для продукта
        stocks_query = select(Stock).where(Stock.sku == product.sku)
        result = await db.exec(stocks_query)
        stocks = result.all()
        
        # Создаем словарь с данными продукта
        product_data = {
            "id": product.sku,
            "sku": product.sku,
            "name": product.name,
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

    # Используем список складов из перечисления
    warehouses = [w.value for w in Warehouses]

    return templates.TemplateResponse(
        "catalog.html",
        {
            "request": request,
            "user": current_user,
            "products": products_with_stocks,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "warehouses": warehouses,
            "current_user": current_user
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
            "total_stock": total_stock or 0,
            "stocks": {}
        }
        
        # Инициализируем остатки для всех складов как 0
        for warehouse in Warehouses:
            product_data["stocks"][warehouse.value] = 0
            
        # Заполняем фактические остатки
        for stock in stocks:
            product_data["stocks"][stock.warehouse] = stock.quantity
        
        # Генерируем HTML для карточки товара
        html = templates.get_template("components/product_card.html").render(
            product=product_data,
            selected_products=[],
            current_user=current_user
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

@web_router.get("/products/add", response_class=HTMLResponse)
async def add_product_form(
    request: Request,
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """Отображает форму добавления нового товара."""
    # Получаем список складов из перечисления
    warehouses = [w.value for w in Warehouses]
    
    return templates.TemplateResponse(
        "add_product.html",
        {
            "request": request,
            "user": current_user,
            "warehouses": warehouses
        }
    )

@router.post("")
async def create_product(
    request: Request,
    name: str = Form(...),
    sku: str = Form(...),
    ean: Optional[str] = Form(None),
    warehouse: str = Form(...),
    quantity: int = Form(...),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """Создает новый товар в базе данных."""
    try:
        # Проверяем, что выбран допустимый склад
        if warehouse not in [w.value for w in Warehouses]:
            raise HTTPException(
                status_code=400,
                detail="Выбран недопустимый склад"
            )

        # Читаем изображение, если оно было загружено
        image_data = None
        if image:
            # Проверяем размер файла (1MB максимум)
            MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB в байтах
            file_size = 0
            image_data = bytearray()
            
            while chunk := await image.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail="Размер файла превышает 1MB"
                    )
                image_data.extend(chunk)
            
            if not file_size:
                image_data = None

        # Разбиваем строку EAN по запятой и очищаем от пробелов
        eans = [e.strip() for e in ean.split(',')] if ean else []

        # Создаем новый товар
        new_product = Product(
            sku=sku,
            name=name,
            eans=eans,
            image=bytes(image_data) if image_data else None
        )
        
        # Добавляем начальные остатки
        if quantity:
            stock = Stock(
                sku=new_product.sku,
                warehouse=warehouse,  # Используем выбранный склад
                quantity=quantity
            )
            db.add(stock)
        
        db.add(new_product)
        await db.commit()
        await db.refresh(new_product)
        
        return {"success": True, "sku": new_product.sku}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось создать товар: {str(e)}"
        )

@router.delete("/{sku}")
async def delete_product(
    sku: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """
    Удаляет товар по его SKU
    """
    # Проверяем права доступа
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для удаления товара"
        )
    
    try:
        # Проверяем существование товара
        product_query = select(Product).where(Product.sku == sku)
        product = await db.exec(product_query)
        product = product.first()
        
        if not product:
            raise HTTPException(
                status_code=404,
                detail="Товар не найден"
            )

        # Сначала удаляем все связанные остатки
        stocks_query = select(Stock).where(Stock.sku == sku)
        stocks = await db.exec(stocks_query)
        for stock in stocks:
            await db.delete(stock)
        
        # Применяем удаление остатков
        await db.flush()
            
        # Затем удаляем сам товар
        await db.delete(product)
        await db.commit()
        
        return {"message": "Товар успешно удален"}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось удалить товар: {str(e)}"
        )