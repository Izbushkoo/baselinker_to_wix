from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request, File, UploadFile, Form
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse, JSONResponse
import io
import pandas as pd
import base64
from sqlalchemy import or_, text, bindparam
from fastapi.templating import Jinja2Templates
from app.api import deps
from app.models.warehouse import Product, Stock, Sale, Transfer
from app.models.user import User
from app.services.warehouse.manager import Warehouses
from app.services.operations_service import OperationsService, OperationType, get_operations_service
from app.schemas.product import ProductUpdate, ProductEditForm, ProductResponse
from PIL import Image
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
web_router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@web_router.get("/catalog")
async def catalog(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    stock_filter: Optional[int] = None,
    min_stock_filter: Optional[int] = None,
    sort_order: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Универсальный роут для отображения каталога товаров.
    Поддерживает как HTML, так и JSON ответы в зависимости от заголовка Accept.
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/catalog", status_code=302)

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

    # Фильтр по максимальному количеству
    if stock_filter is not None and stock_filter >= 0:
        base_query = base_query.having(
            func.coalesce(func.sum(Stock.quantity), 0) < stock_filter
        )

    # Фильтр по минимальному количеству
    if min_stock_filter is not None and min_stock_filter >= 0:
        base_query = base_query.having(
            func.coalesce(func.sum(Stock.quantity), 0) >= min_stock_filter
        )

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

    # Проверяем, является ли запрос AJAX-запросом
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    accept = request.headers.get("accept", "")

    # Если это AJAX-запрос или клиент ожидает JSON
    if is_ajax or "application/json" in accept:
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

    # Для обычных запросов возвращаем HTML-страницу
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

@web_router.get("/products/{sku}/edit", response_class=HTMLResponse)
async def edit_product_form(
    request: Request,
    sku: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """Отображает форму редактирования товара."""
    # Проверяем права доступа
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для редактирования товара"
        )
    
    # Получаем товар из базы данных
    product_query = select(Product).where(Product.sku == sku)
    result = await db.exec(product_query)
    product = result.first()
    
    if not product:
        raise HTTPException(
            status_code=404,
            detail="Товар не найден"
        )
    
    # Подготавливаем данные для формы
    product_data = {
        "sku": product.sku,
        "name": product.name,
        "ean": ", ".join(product.eans) if product.eans else "",
        "current_image": base64.b64encode(product.image).decode('utf-8') if product.image else None
    }
    
    return templates.TemplateResponse(
        "edit_product.html",
        {
            "request": request,
            "user": current_user,
            "product": product_data
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
    current_user: User = Depends(deps.get_current_user_optional),
    operations_service: OperationsService = Depends(get_operations_service)
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
            # Проверяем размер файла (5MB максимум)
            MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB в байтах
            file_size = 0
            image_data = bytearray()
            
            while chunk := await image.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail="Размер файла превышает 5MB"
                    )
                image_data.extend(chunk)
            
            if file_size:
                # Открываем изображение с помощью PIL
                img = Image.open(io.BytesIO(image_data))
                
                # Изменяем размер изображения до 100x100 с сохранением пропорций
                img.thumbnail((100, 100), Image.Resampling.LANCZOS)
                
                # Конвертируем в RGB если изображение в режиме RGBA
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Сохраняем изображение в буфер в формате WebP с максимальным сжатием
                output_buffer = io.BytesIO()
                img.save(output_buffer, format='WEBP', quality=30, method=6)
                image_data = output_buffer.getvalue()
                logger.info(f"Размер обработанного изображения: {len(image_data) / 1024:.2f} КБ")

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
        
        # Создаем запись операции
        operations_service.create_product_operation(
            sku=sku,
            name=name,
            warehouse_id=warehouse,
            initial_quantity=quantity,
            user_email=current_user.email
        )
        
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
    current_user: User = Depends(deps.get_current_user_optional),
    operations_service: OperationsService = Depends(get_operations_service)
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

        # Получаем информацию о товаре перед удалением
        product_info = {
            "sku": product.sku,
            "name": product.name,
            "eans": product.eans
        }

        # Сначала удаляем все связанные перемещения
        transfer_query = select(Transfer).where(Transfer.sku == sku)
        transfers = await db.exec(transfer_query)
        for transfer in transfers:
            await db.delete(transfer)
        
        # Применяем удаление перемещений
        await db.flush()

        # Затем удаляем все связанные продажи
        sales_query = select(Sale).where(Sale.sku == sku)
        sales = await db.exec(sales_query)
        for sale in sales:
            await db.delete(sale)
        
        # Применяем удаление продаж
        await db.flush()

        # Затем удаляем все связанные остатки
        stocks_query = select(Stock).where(Stock.sku == sku)
        stocks = await db.exec(stocks_query)
        for stock in stocks:
            await db.delete(stock)
        
        # Применяем удаление остатков
        await db.flush()
            
        # В конце удаляем сам товар
        await db.delete(product)
        await db.commit()
        
        # Создаем запись операции
        operations_service.create_product_delete_operation(
            sku=sku,
            user_email=current_user.email
        )
        
        return {"message": "Товар успешно удален"}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось удалить товар: {str(e)}"
        )

@router.put("/{sku}")
async def update_product(
    sku: str,
    request: Request,
    name: Optional[str] = Form(None),
    new_sku: Optional[str] = Form(None),
    ean: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional),
    operations_service: OperationsService = Depends(get_operations_service)
):
    """Обновляет товар по его SKU"""
    # Проверяем права доступа
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для редактирования товара"
        )
    
    try:
        # Получаем текущий товар
        product_query = select(Product).where(Product.sku == sku)
        result = await db.exec(product_query)
        product = result.first()
        
        if not product:
            raise HTTPException(
                status_code=404,
                detail="Товар не найден"
            )
        
        # Сохраняем старые значения для логирования
        old_values = {
            "sku": product.sku,
            "name": product.name,
            "eans": product.eans.copy() if product.eans else []
        }
        
        # Проверяем уникальность нового SKU, если он изменяется
        if new_sku and new_sku != sku:
            existing_product_query = select(Product).where(Product.sku == new_sku)
            existing_result = await db.exec(existing_product_query)
            if existing_result.first():
                raise HTTPException(
                    status_code=400,
                    detail=f"Товар с SKU '{new_sku}' уже существует"
                )
        
        # Обновляем поля товара
        if name is not None:
            product.name = name
        
        if new_sku is not None:
            product.sku = new_sku
        
        if ean is not None:
            # Разбиваем строку EAN по запятой и очищаем от пробелов
            eans = [e.strip() for e in ean.split(',')] if ean else []
            product.eans = eans
        
        # Обрабатываем новое изображение, если оно загружено
        if image:
            # Проверяем размер файла (5MB максимум)
            MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB в байтах
            file_size = 0
            image_data = bytearray()
            
            while chunk := await image.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail="Размер файла превышает 5MB"
                    )
                image_data.extend(chunk)
            
            if file_size:
                # Открываем изображение с помощью PIL
                img = Image.open(io.BytesIO(image_data))
                
                # Изменяем размер изображения до 100x100 с сохранением пропорций
                img.thumbnail((100, 100), Image.Resampling.LANCZOS)
                
                # Конвертируем в RGB если изображение в режиме RGBA
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Сохраняем изображение в буфер в формате WebP с максимальным сжатием
                output_buffer = io.BytesIO()
                img.save(output_buffer, format='WEBP', quality=30, method=6)
                image_data = output_buffer.getvalue()
                logger.info(f"Размер обработанного изображения: {len(image_data) / 1024:.2f} КБ")
                
                product.image = bytes(image_data)
        
        # Сохраняем изменения
        await db.commit()
        await db.refresh(product)
        
        # Подготавливаем новые значения для логирования
        new_values = {
            "sku": product.sku,
            "name": product.name,
            "eans": product.eans.copy() if product.eans else []
        }
        
        # Создаем запись операции
        operations_service.create_product_edit_operation(
            sku=old_values["sku"],
            old_values=old_values,
            new_values=new_values,
            user_email=current_user.email
        )
        
        return {"success": True, "message": "Товар успешно обновлен", "sku": product.sku}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось обновить товар: {str(e)}"
        )
