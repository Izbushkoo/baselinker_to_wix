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
from app.api.v1.routers.allegro_sync import get_sync_status
from app.models.warehouse import Product, Stock, Sale, Transfer
from app.models.user import User
from app.models.allegro_token import AllegroToken
from app.models.product_allegro_sync_settings import ProductAllegroSyncSettings
from app.services.warehouse.manager import Warehouses
from app.services.operations_service import OperationsService, OperationType, get_operations_service
from app.services.prices_service import prices_service
from app.schemas.product import ProductUpdate, ProductEditForm, ProductResponse
from app.celery_app import celery
from PIL import Image
import logging
from datetime import datetime
from app.services.allegro.allegro_api_service import SyncAllegroApiService
from app.services.allegro.tokens import get_token
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
web_router = APIRouter()
catalog_router = APIRouter()  # Отдельный роутер для каталога

templates = Jinja2Templates(directory="app/templates")

@catalog_router.get("/catalog")
async def catalog(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    stock_filter: Optional[int] = None,
    min_stock_filter: Optional[int] = None,
    brand_filter: Optional[str] = None,
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

    # Логирование параметров запроса
    logger.info(f"Catalog request parameters: search={search}, stock_filter={stock_filter}, min_stock_filter={min_stock_filter}, brand_filter={brand_filter}, sort_order={sort_order}")

    # Валидация и автоматическая коррекция фильтров
    if (stock_filter is not None and min_stock_filter is not None and 
        stock_filter < min_stock_filter):
        logger.warning(f"Некорректные значения фильтров: stock_filter={stock_filter} < min_stock_filter={min_stock_filter}. Меняю местами.")
        stock_filter, min_stock_filter = min_stock_filter, stock_filter
        logger.info(f"Исправленные параметры: stock_filter={stock_filter}, min_stock_filter={min_stock_filter}")

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
        from sqlalchemy import and_
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
    logger.info(f"[CATALOG] prices_service.is_available(): {prices_service.is_available()}")
    logger.info(f"[CATALOG] products_with_stocks count: {len(products_with_stocks)}")
    
    if prices_service.is_available() and products_with_stocks:
        try:
            # Получаем все SKU товаров
            skus = [product["sku"] for product in products_with_stocks]
            logger.info(f"[CATALOG] SKUs для получения цен: {skus}")
            
            # Получаем цены для всех SKU одним запросом
            prices_data = prices_service.get_prices_by_skus(skus)
            logger.info(f"[CATALOG] Полученные цены от сервиса: {prices_data}")
            
            # Добавляем цены к данным товаров
            for product_data in products_with_stocks:
                sku = product_data["sku"]
                price_info = prices_data.get(sku)
                logger.info(f"[CATALOG] SKU {sku}: price_info={price_info}")
                if price_info:
                    product_data["min_price"] = price_info.min_price
                    logger.info(f"[CATALOG] SKU {sku}: установлена min_price={price_info.min_price}")
                else:
                    product_data["min_price"] = None
                    logger.info(f"[CATALOG] SKU {sku}: min_price установлена в None")
        except Exception as e:
            logger.error(f"[CATALOG] Error getting prices: {str(e)}")
            # Если не удалось получить цены, добавляем пустые значения
            for product_data in products_with_stocks:
                product_data["min_price"] = None

    # Проверяем, является ли запрос AJAX-запросом
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    accept = request.headers.get("accept", "")

    # Если это AJAX-запрос или клиент ожидает JSON
    if is_ajax or "application/json" in accept:
        # Для AJAX-запросов генерируем HTML для каждой карточки
        products_response = []
        for product_data in products_with_stocks:
            logger.info(f"[CATALOG] AJAX: product_data для SKU {product_data.get('sku')}: min_price={product_data.get('min_price')}")
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
    
    # Логируем данные товаров перед отправкой в шаблон
    for product_data in products_with_stocks:
        logger.info(f"[CATALOG] HTML: product_data для SKU {product_data.get('sku')}: min_price={product_data.get('min_price')}")
    
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

@web_router.get("/add", response_class=HTMLResponse)
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

@web_router.get("/{sku}/edit", response_class=HTMLResponse)
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
        "brand": product.brand or "",
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
    brand: Optional[str] = Form(None),
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
            "brand": product.brand,
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
        
        if brand is not None:
            product.brand = brand if brand.strip() else None
        
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
            "brand": product.brand,
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


@router.post("/{sku}/sync-settings")
async def update_sync_settings(
    sku: str,
    account_name: str = Form(...),
    stock_sync_enabled: bool = Form(...),
    price_sync_enabled: bool = Form(...),
    price_multiplier: float = Form(default=1.0),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Создать или обновить настройки синхронизации для товара и аккаунта Allegro.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    # Проверяем существование товара
    product_query = select(Product).where(Product.sku == sku)
    product_result = await db.exec(product_query)
    product = product_result.first()
    
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    # Проверяем существование аккаунта Allegro
    token_query = select(AllegroToken).where(AllegroToken.account_name == account_name)
    token_result = await db.exec(token_query)
    token = token_result.first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Аккаунт Allegro не найден")
    
    # Получаем или создаем настройки синхронизации
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku,
        ProductAllegroSyncSettings.allegro_account_name == account_name
    )
    settings_result = await db.exec(settings_query)
    settings = settings_result.first()
    
    if settings:
        # Обновляем существующие настройки
        settings.stock_sync_enabled = stock_sync_enabled
        settings.price_sync_enabled = price_sync_enabled
        settings.price_multiplier = price_multiplier
        settings.updated_at = datetime.utcnow()
    else:
        # Создаем новые настройки
        settings = ProductAllegroSyncSettings(
            product_sku=sku,
            allegro_account_name=account_name,
            stock_sync_enabled=stock_sync_enabled,
            price_sync_enabled=price_sync_enabled,
            price_multiplier=price_multiplier
        )
        db.add(settings)
    
    await db.commit()
    await db.refresh(settings)
    
    return {
        "success": True,
        "message": f"Настройки синхронизации для аккаунта {account_name} обновлены",
        "settings": {
            "product_sku": settings.product_sku,
            "allegro_account_name": settings.allegro_account_name,
            "stock_sync_enabled": settings.stock_sync_enabled,
            "price_sync_enabled": settings.price_sync_enabled,
            "price_multiplier": float(settings.price_multiplier),
            "updated_at": settings.updated_at.isoformat()
        }
    }


@router.get("/{sku}/sync-settings")
async def get_sync_settings(
    sku: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Получить все настройки синхронизации для товара.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    # Проверяем существование товара
    product_query = select(Product).where(Product.sku == sku)
    product_result = await db.exec(product_query)
    product = product_result.first()
    
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    # Получаем настройки синхронизации
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku
    )
    settings_result = await db.exec(settings_query)
    settings_list = settings_result.all()
    
    # Формируем ответ
    settings_data = []
    for settings in settings_list:
        settings_data.append({
            "product_sku": settings.product_sku,
            "allegro_account_name": settings.allegro_account_name,
            "stock_sync_enabled": settings.stock_sync_enabled,
            "price_sync_enabled": settings.price_sync_enabled,
            "price_multiplier": float(settings.price_multiplier),
            "last_stock_sync_at": settings.last_stock_sync_at.isoformat() if settings.last_stock_sync_at else None,
            "last_price_sync_at": settings.last_price_sync_at.isoformat() if settings.last_price_sync_at else None,
            "created_at": settings.created_at.isoformat(),
            "updated_at": settings.updated_at.isoformat()
        })
    
    return {
        "success": True,
        "product_sku": sku,
        "settings": settings_data
    }


@router.post("/{sku}/sync-settings/{account_name}/toggle-stock")
async def toggle_stock_sync(
    sku: str,
    account_name: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Переключить синхронизацию остатков для товара и аккаунта.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    # Получаем или создаем настройки
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku,
        ProductAllegroSyncSettings.allegro_account_name == account_name
    )
    settings_result = await db.exec(settings_query)
    settings = settings_result.first()
    
    if not settings:
        # Создаем новые настройки с включенной синхронизацией остатков
        settings = ProductAllegroSyncSettings(
            product_sku=sku,
            allegro_account_name=account_name,
            stock_sync_enabled=True,
            price_sync_enabled=False,
            price_multiplier=1.0
        )
        db.add(settings)
        new_status = True
    else:
        # Переключаем статус
        settings.stock_sync_enabled = not settings.stock_sync_enabled
        settings.updated_at = datetime.utcnow()
        new_status = settings.stock_sync_enabled
    
    await db.commit()
    await db.refresh(settings)
    
    # Если синхронизация включена, запускаем автоматическую синхронизацию остатков
    if new_status:
        try:
            celery.send_task(
                'app.services.allegro.sync_tasks.sync_allegro_stock_single_product_account',
                args=[sku, account_name]
            )
        except Exception as e:
            # Не прерываем выполнение, если задача не удалась
            import logging
            logger = logging.getLogger("allegro.sync")
            logger.error(f"Ошибка при запуске синхронизации остатков для товара {sku} и аккаунта {account_name}: {str(e)}")
    
    return {
        "success": True,
        "message": f"Синхронизация остатков для аккаунта {account_name} {'включена' if new_status else 'отключена'}",
        "stock_sync_enabled": new_status
    }


@router.post("/{sku}/sync-settings/{account_name}/toggle-price")
async def toggle_price_sync(
    sku: str,
    account_name: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Переключить синхронизацию цен для товара и аккаунта.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    # Получаем или создаем настройки
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku,
        ProductAllegroSyncSettings.allegro_account_name == account_name
    )
    settings_result = await db.exec(settings_query)
    settings = settings_result.first()
    
    if not settings:
        # Создаем новые настройки с включенной синхронизацией цен
        settings = ProductAllegroSyncSettings(
            product_sku=sku,
            allegro_account_name=account_name,
            stock_sync_enabled=True,
            price_sync_enabled=True,
            price_multiplier=1.0
        )
        db.add(settings)
        new_status = True
    else:
        # Переключаем статус
        settings.price_sync_enabled = not settings.price_sync_enabled
        settings.updated_at = datetime.utcnow()
        new_status = settings.price_sync_enabled
    
    await db.commit()
    await db.refresh(settings)
    
    # Если синхронизация включена, запускаем автоматическую синхронизацию цен
    if new_status:
        try:
            celery.send_task(
                'app.services.allegro.sync_tasks.sync_allegro_price_single_product_account',
                args=[sku, account_name]
            )
        except Exception as e:
            # Не прерываем выполнение, если задача не удалась
            import logging
            logger = logging.getLogger("allegro.sync")
            logger.error(f"Ошибка при запуске синхронизации цен для товара {sku} и аккаунта {account_name}: {str(e)}")
    
    return {
        "success": True,
        "message": f"Синхронизация цен для аккаунта {account_name} {'включена' if new_status else 'отключена'}",
        "price_sync_enabled": new_status
    }


@router.post("/{sku}/sync-settings/{account_name}/update-multiplier")
async def update_price_multiplier(
    sku: str,
    account_name: str,
    multiplier: float = Form(...),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Обновить мультипликатор цены для товара и аккаунта.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    if multiplier <= 0:
        raise HTTPException(status_code=400, detail="Мультипликатор цены должен быть положительным числом")
    
    # Получаем или создаем настройки
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku,
        ProductAllegroSyncSettings.allegro_account_name == account_name
    )
    settings_result = await db.exec(settings_query)
    settings = settings_result.first()
    
    if not settings:
        # Создаем новые настройки с указанным мультипликатором
        settings = ProductAllegroSyncSettings(
            product_sku=sku,
            allegro_account_name=account_name,
            stock_sync_enabled=True,
            price_sync_enabled=False,
            price_multiplier=multiplier
        )
        db.add(settings)
    else:
        # Обновляем мультипликатор
        settings.price_multiplier = multiplier
        settings.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(settings)
    
    # Если синхронизация цен включена, запускаем автоматическую синхронизацию
    if settings.price_sync_enabled:
        try:
            celery.send_task(
                'app.services.allegro.sync_tasks.sync_allegro_price_single_product_account',
                args=[sku, account_name]
            )
        except Exception as e:
            # Не прерываем выполнение, если задача не удалась
            import logging
            logger = logging.getLogger("allegro.sync")
            logger.error(f"Ошибка при запуске синхронизации цен для товара {sku} и аккаунта {account_name}: {str(e)}")
    
    return {
        "success": True,
        "message": f"Мультипликатор цены для аккаунта {account_name} обновлен",
        "price_multiplier": float(settings.price_multiplier)
    }


@router.post("/{sku}/sync-settings/{account_name}/sync-price")
async def sync_price_single_product_account(
    sku: str,
    account_name: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Запустить синхронизацию цены для конкретного товара и аккаунта Allegro.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    # Проверяем существование товара
    product_query = select(Product).where(Product.sku == sku)
    product_result = await db.exec(product_query)
    product = product_result.first()
    
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    # Проверяем существование аккаунта Allegro
    token_query = select(AllegroToken).where(AllegroToken.account_name == account_name)
    token_result = await db.exec(token_query)
    token = token_result.first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Аккаунт Allegro не найден")
    
    # Проверяем настройки синхронизации
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku,
        ProductAllegroSyncSettings.allegro_account_name == account_name
    )
    settings_result = await db.exec(settings_query)
    settings = settings_result.first()
    
    if not settings or not settings.price_sync_enabled:
        raise HTTPException(
            status_code=400, 
            detail="Синхронизация цен для этого товара и аккаунта не включена"
        )
    
    # Получаем цену товара из сервиса цен
    price_data = prices_service.get_price_by_sku(sku)
    if not price_data or price_data.min_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="У товара не указана минимальная цена"
        )
    
    # Запускаем задачу синхронизации цены
    try:
        task = celery.send_task(
            'app.services.allegro.sync_tasks.sync_allegro_price_single_product_account',
            args=[sku, account_name]
        )
        
        return {
            "success": True,
            "message": f"Синхронизация цены для товара {sku} и аккаунта {account_name} запущена",
            "task_id": task.id,
            "sku": sku,
            "account_name": account_name
        }
    except Exception as e:
        import logging
        logger = logging.getLogger("allegro.sync")
        logger.error(f"Ошибка при запуске синхронизации цены для товара {sku} и аккаунта {account_name}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации цены: {str(e)}"
        )

@router.get("/brands")
async def get_brands(
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """
    Получение списка уникальных брендов товаров
    """
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

@web_router.get("/{sku}/manage")
async def manage_product(
    request: Request,
    sku: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Страница управления товаром с настройками синхронизации Allegro.
    Показывает детальную информацию о товаре и настройки синхронизации для каждого аккаунта.
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/products/{sku}/manage", status_code=302)
    
    # Получаем товар
    product_query = select(Product).where(Product.sku == sku)
    product_result = await db.exec(product_query)
    product = product_result.first()
    
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    # Получаем остатки товара по складам
    stock_query = select(Stock).where(Stock.sku == sku)
    stock_result = await db.exec(stock_query)
    stocks = stock_result.all()
    
    # Формируем словарь остатков по складам с учетом всех складов
    stock_by_warehouse = {warehouse.value: 0 for warehouse in Warehouses}
    for stock in stocks:
        stock_by_warehouse[stock.warehouse] = stock.quantity
    total_stock = sum(stock_by_warehouse.values())
    
    # Получаем все токены Allegro
    # tokens_query = select(AllegroToken)
    # tokens_result = await db.exec(tokens_query)
    # allegro_tokens = tokens_result.all()

    token = get_token(account_name)
    token_client = AllegroTokenMicroserviceClient(
        jwt_token=create_access_token(user_id=settings.PROJECT_NAME),
        
    )
    tokens = token_client.get_tokens(per_page=50)

    
    # Получаем настройки синхронизации для товара
    sync_settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku
    )
    sync_settings_result = await db.exec(sync_settings_query)
    existing_settings = sync_settings_result.all()
    
    # Создаем словарь настроек по аккаунтам
    settings_by_account = {setting.allegro_account_name: setting for setting in existing_settings}
    
    # Подготавливаем данные для шаблона
    product_data = {
        'sku': product.sku,
        'name': product.name,
        'brand': product.brand,
        'image': base64.b64encode(product.image).decode('utf-8') if product.image else None,
        'eans': product.eans,
        'stocks': stock_by_warehouse,
        'total_stock': total_stock,
    }
    
    # Получаем данные о цене из удаленной БД
    logger.info(f"[MANAGE] prices_service.is_available(): {prices_service.is_available()}")
    if prices_service.is_available():
        try:
            logger.info(f"[MANAGE] Получаем цену для SKU: {sku}")
            price_info = prices_service.get_price_by_sku(sku)
            logger.info(f"[MANAGE] Полученная цена от сервиса: {price_info}")
            if price_info:
                product_data['min_price'] = price_info.min_price
                logger.info(f"[MANAGE] SKU {sku}: установлена min_price={price_info.min_price}")
            else:
                product_data['min_price'] = None
                logger.info(f"[MANAGE] SKU {sku}: min_price установлена в None (price_info is None)")
        except Exception as e:
            logger.error(f"[MANAGE] Error getting price for SKU {sku}: {str(e)}")
            product_data['min_price'] = None
    else:
        product_data['min_price'] = None
        logger.info(f"[MANAGE] SKU {sku}: min_price установлена в None (prices_service не доступен)")
    
    # Подготавливаем данные о токенах с настройками
    token_settings = []
    for token in tokens:
        account_name = token.account_name or f"Account {token.id[:8]}"
        
        # Получаем существующие настройки или создаем дефолтные
        settings = settings_by_account.get(account_name)
        if settings:
            token_data = {
                'token_id': token.id,
                'account_name': account_name,
                'stock_sync_enabled': settings.stock_sync_enabled,
                'price_sync_enabled': settings.price_sync_enabled,
                'price_multiplier': float(settings.price_multiplier),
                'last_stock_sync_at': settings.last_stock_sync_at,
                'last_price_sync_at': settings.last_price_sync_at,
                'has_settings': True
            }
        else:
            # Дефолтные настройки для токена без настроек
            token_data = {
                'token_id': token.id_,
                'account_name': account_name,
                'stock_sync_enabled': False,  # По умолчанию включено
                'price_sync_enabled': False,  # По умолчанию выключено
                'price_multiplier': 1.0,
                'last_stock_sync_at': None,
                'last_price_sync_at': None,
                'has_settings': False
            }
        
        token_settings.append(token_data)
    
    # Логируем данные товара перед отправкой в шаблон
    logger.info(f"[MANAGE] Данные товара для шаблона: SKU={product_data.get('sku')}, min_price={product_data.get('min_price')}")
    
    return templates.TemplateResponse(
        "product_manage.html",
        {
            "request": request,
            "user": current_user,
            "product": product_data,
            "allegro_tokens": token_settings
        }
    )

@router.get("/{sku}/offers/{account_name}")
async def get_product_offers(
    sku: str,
    account_name: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Получает список оферт для товара в конкретном аккаунте Allegro.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    try:
        logger.info(f"[OFFERS] Запрос оферт для SKU {sku} в аккаунте {account_name}")
        
        # Получаем токен аккаунта
        token = get_token(account_name)
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=create_access_token(user_id=settings.PROJECT_NAME),
            
        )
        token = token_client.get_tokens(per_page=50)

        if not token:
            logger.error(f"[OFFERS] Токен для аккаунта {account_name} не найден")
            raise HTTPException(status_code=404, detail="Аккаунт Allegro не найден")
        
        # Проверяем валидность токена
        if not token.access_token:
            logger.error(f"[OFFERS] Access token отсутствует для аккаунта {account_name}")
            raise HTTPException(status_code=500, detail="Токен доступа недействителен")
        
        logger.info(f"[OFFERS] Токен найден для аккаунта {account_name}")
        
        # Проверяем существование товара
        product_query = select(Product).where(Product.sku == sku)
        product_result = await db.exec(product_query)
        product = product_result.first()
        
        if not product:
            logger.error(f"[OFFERS] Товар с SKU {sku} не найден")
            raise HTTPException(status_code=404, detail="Товар не найден")
        
        logger.info(f"[OFFERS] Товар найден: {product.name}")
        
        # Создаем API сервис для работы с Allegro
        api_service = SyncAllegroApiService()
        logger.info(f"[OFFERS] Сервис API создан")
        
        # Получаем оферты, используя SKU как external_id
        logger.info(f"[OFFERS] Запрос к API Allegro для external_id={sku}")
        offers_data = api_service.get_offers(
            token=token.access_token,
            external_ids=[sku],
            limit=50
        )
        
        logger.info(f"[OFFERS] Получен ответ от API: {offers_data.keys() if offers_data else 'None'}")
        
        # Обрабатываем данные оферт для фронтенда
        processed_offers = []
        offers_list = offers_data.get("offers", [])
        logger.info(f"[OFFERS] Количество оферт в ответе: {len(offers_list)}")
        
        for offer in offers_list:
            logger.debug(f"[OFFERS] Обработка оферты: {offer.get('id')}")
            
            # Получаем цену из saleInfo.currentPrice, если доступно, иначе из sellingMode.price
            sale_info = offer.get("saleInfo", {})
            selling_mode = offer.get("sellingMode", {})
            current_price = sale_info.get("currentPrice") or {}
            selling_price = selling_mode.get("price") or {}
            
            # Приоритет: saleInfo.currentPrice > sellingMode.price
            price_amount = current_price.get("amount") or selling_price.get("amount")
            price_currency = current_price.get("currency") or selling_price.get("currency")
            
            # Извлекаем основные данные оферты
            offer_info = {
                "id": offer.get("id"),
                "name": offer.get("name"),
                "status": offer.get("publication", {}).get("status"),
                
                # Текущая цена (приоритет saleInfo.currentPrice)
                "price": {
                    "amount": price_amount,
                    "currency": price_currency
                },
                
                # Остатки
                "stock": offer.get("stock", {}),
                
                # Статус публикации
                "publication": offer.get("publication", {}),
                
                # Детальная информация (для развернутого блока)
                "details": {
                    "category": offer.get("category", {}),
                    "primaryImage": offer.get("primaryImage", {}),
                    "sellingMode": selling_mode,
                    "saleInfo": sale_info,
                    "stock": offer.get("stock", {}),
                    "stats": offer.get("stats", {}),
                    "publication": offer.get("publication", {}),
                    "delivery": offer.get("delivery", {}),
                    "external": offer.get("external", {}),
                    "afterSalesServices": offer.get("afterSalesServices", {}),
                    "additionalServices": offer.get("additionalServices", {}),
                    "b2b": offer.get("b2b", {}),
                    "fundraisingCampaign": offer.get("fundraisingCampaign", {})
                }
            }
            processed_offers.append(offer_info)
        
        logger.info(f"[OFFERS] Обработано оферт: {len(processed_offers)}")
        
        return {
            "success": True,
            "offers": processed_offers,
            "count": len(processed_offers),
            "total_count": offers_data.get("totalCount", 0),
            "sku": sku,
            "account_name": account_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[OFFERS] Ошибка при получении оферт для SKU {sku} в аккаунте {account_name}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении оферт: {str(e)}"
        )
