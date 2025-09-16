from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request, File, UploadFile, Form, Body
from pydantic import BaseModel
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse, JSONResponse, Response
import io
import pandas as pd
import base64
from sqlalchemy import or_, text, bindparam
from fastapi.templating import Jinja2Templates
from app.api import deps
from app.models.warehouse import Product, Stock, Sale, Transfer
from app.models.user import User
from app.models.allegro_token import AllegroToken
from app.models.product_allegro_sync_settings import ProductAllegroSyncSettings
from app.services.warehouse.manager import Warehouses, InventoryManager, get_manager
from app.services.operations_service import OperationsService, OperationType, get_operations_service
from app.services.prices_service import prices_service
from app.celery_app import celery
from PIL import Image
import logging
from datetime import datetime
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.services.Allegro_Microservice.offers_endpoint import AllegroOffersMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()
web_router = APIRouter()
catalog_router = APIRouter()  # Отдельный роутер для каталога

templates = Jinja2Templates(directory="app/templates")

def modify_card_for_workspace(html: str, sku: str) -> str:
    """
    Модифицирует HTML карточки товара для отображения в воркспейсе:
    1. Удаляет onclick="addToWorkspaceFromCard(event, this)" с главного div
    2. Добавляет кнопку удаления (крестик) в левый верхний угол
    3. Обеспечивает корректную работу поля "Количество в заявку"
    """
    import re
    
    # Удаляем onclick с главного div
    html = re.sub(r'\s+onclick="addToWorkspaceFromCard\(event, this\)"', '', html)
    
    # Добавляем кнопку удаления после открывающего тега div
    delete_button = f'''
    <!-- Кнопка удаления из воркспейса (левый верхний угол) -->
    <button type="button"
            data-sku="{sku}"
            class="absolute top-2 left-2 z-30 p-1 bg-red-500 hover:bg-red-600 text-white rounded-full shadow-md transition-colors duration-200"
            title="Удалить из воркспейса">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
    </button>'''
    
    # Вставляем кнопку после открывающего тега div с классом product-card
    html = re.sub(
        r'(<div class="product-card[^"]*"[^>]*>)',
        r'\1' + delete_button,
        html
    )
    
    # Убеждаемся, что поля "Количество в заявку" и "Комментарий" работают корректно в воркспейсе
    # Добавляем обработчики для сохранения значений при изменении
    html = html.replace(
        'data-field="request_quantity"',
        f'data-field="request_quantity" data-workspace-sku="{sku}" onchange="saveRequestQuantity(this)"'
    )
    html = html.replace(
        'data-field="request_comment"',
        f'data-field="request_comment" data-workspace-sku="{sku}" onchange="saveRequestComment(this)"'
    )
    
    return html

# Модели для API
class BulkDeleteRequest(BaseModel):
    skus: List[str]

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
    operation_skus: Optional[str] = None,
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
    logger.info(f"Catalog request: search={search}, stock_filter={stock_filter}, min_stock_filter={min_stock_filter}, brand_filter={brand_filter}")

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
            "has_image": bool(product.original_image),  # Проверяем наличие оригинального изображения
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
                if price_info and price_info.min_price:
                    # Конвертируем Decimal в float для JSON сериализации
                    product_data["min_price"] = float(price_info.min_price)
                else:
                    product_data["min_price"] = None
        except Exception as e:
            logger.error(f"Error getting prices: {str(e)}")
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

@web_router.get("/quick_edit", response_class=HTMLResponse)
async def quick_edit(
    request: Request,
    operation_skus: Optional[str] = Query(None),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    if not current_user:
        return RedirectResponse(url=f"/login?next=/products/quick_edit?operation_skus={operation_skus}", status_code=302)
    
    skus = [s.strip() for s in operation_skus.split(",")] if operation_skus else []
    
    # Формируем запрос к БД
    base_query = (
        select(Product, func.sum(Stock.quantity).label("total_stock"))
        .outerjoin(Stock, Stock.sku == Product.sku)
        .where(Product.sku.in_(skus))
        .group_by(Product.sku)
    )
    result = await db.exec(base_query)
    rows = result.all()
    
    products_with_stocks = []
    for prod, total in rows:
        total_stock = total or 0
        stocks_res = await db.exec(select(Stock).where(Stock.sku == prod.sku))
        stocks = stocks_res.all()
        product_data = {
            "sku": prod.sku,
            "name": prod.name,
            "brand": prod.brand,
            "eans": prod.eans,
            "ean": prod.eans[0] if prod.eans else None,
            "image": base64.b64encode(prod.image).decode("utf-8") if prod.image else None,
            "total_stock": total_stock,
            "stocks": {w.value: 0 for w in Warehouses}
        }
        for st in stocks:
            product_data["stocks"][st.warehouse] = st.quantity
        price_info = prices_service.get_price_by_sku(prod.sku)
        product_data["min_price"] = float(price_info.min_price) if price_info and price_info.min_price else None
        products_with_stocks.append(product_data)
    
    # Check if this is a JSON request (from AJAX)
    if request.headers.get("Accept") == "application/json":
        # Рендерим каждый товар через шаблон product_card.html
        products_html = []
        for product in products_with_stocks:
            product_html = templates.get_template("components/product_card.html").render(
                request=request,
                product=product,
                current_user=current_user
            )
            products_html.append(product_html)
        
        return JSONResponse(content={
            "products_html": products_html, 
            "current_user": {"is_admin": current_user.is_admin}
        })
    
    # Otherwise return HTML response (not used anymore, but kept for compatibility)
    return templates.TemplateResponse(
        "quick_edit_panel.html",
        {"request": request, "products": products_with_stocks, "current_user": current_user}
    )

@web_router.get("/add", response_class=HTMLResponse)
async def add_product_form(
    request: Request,
    sku: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    quantity: Optional[int] = Query(None),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    """Отображает форму добавления нового товара."""
    # Получаем список складов из перечисления
    warehouses = [w.value for w in Warehouses]
    
    # Подготавливаем данные для предзаполнения
    prefill_data = {}
    if sku:
        prefill_data['sku'] = sku
    if name:
        prefill_data['name'] = name
    if quantity is not None:
        prefill_data['quantity'] = quantity
    
    return templates.TemplateResponse(
        "add_product.html",
        {
            "request": request,
            "user": current_user,
            "warehouses": warehouses,
            "prefill_data": prefill_data
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
        "name_eng": product.name_eng or "",
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

@catalog_router.post("/workspace-cards")
async def get_workspace_cards(
    request: Request,
    skus: List[str] = Body(...),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Получение массива карточек товаров для воркспейса одним запросом
    """
    if not skus:
        return JSONResponse(content={"html": "", "count": 0})
    
    try:
        # Базовый запрос для товаров с подсчетом остатков (как в каталоге)
        base_query = (
            select(
                Product,
                func.sum(Stock.quantity).label('total_stock')
            )
            .outerjoin(Stock, Stock.sku == Product.sku)
            .where(Product.sku.in_(skus))
            .group_by(Product.sku)
        )
        
        # Получаем товары с остатками
        result = await db.exec(base_query)
        products_with_stocks = result.all()
        
        if not products_with_stocks:
            return JSONResponse(content={"html": "", "count": 0})
        
        # Создаем список продуктов с их остатками (как в каталоге)
        products_data = []
        for row in products_with_stocks:
            product = row[0]  # Получаем объект Product
            total_stock = row[1] or 0  # Получаем total_stock
            
            # Получаем остатки для продукта
            stocks_query = select(Stock).where(Stock.sku == product.sku)
            stocks_result = await db.exec(stocks_query)
            stocks = stocks_result.all()
            
            # Создаем словарь с данными продукта (как в каталоге)
            product_data = {
                "id": product.sku,
                "sku": product.sku,
                "name": product.name,
                "name_eng": product.name_eng,  # Добавляем английское название
                "brand": product.brand,
                "eans": product.eans,
                "ean": product.eans[0] if product.eans else None,
                "image": base64.b64encode(product.image).decode('utf-8') if product.image else None,
                "has_image": bool(product.original_image),  # Проверяем наличие оригинального изображения
                "total_stock": total_stock,
                "stocks": {}
            }
            
            # Инициализируем остатки для всех складов как 0
            for warehouse in Warehouses:
                product_data["stocks"][warehouse.value] = 0
                
            # Заполняем фактические остатки
            for stock in stocks:
                product_data["stocks"][stock.warehouse] = stock.quantity
            
            products_data.append(product_data)
        
        # Обогащаем данные о товарах ценами из удаленной БД (как в каталоге)
        if prices_service.is_available() and products_data:
            try:
                # Получаем все SKU товаров
                product_skus = [product["sku"] for product in products_data]
                
                # Получаем цены для всех SKU одним запросом
                prices_data = prices_service.get_prices_by_skus(product_skus)
                
                # Добавляем цены к данным товаров
                for product_data in products_data:
                    sku = product_data["sku"]
                    price_info = prices_data.get(sku)
                    if price_info and price_info.min_price:
                        # Конвертируем Decimal в float для JSON сериализации
                        product_data["min_price"] = float(price_info.min_price)
                    else:
                        product_data["min_price"] = None
            except Exception as e:
                logger.error(f"Error getting prices: {str(e)}")
                # Если не удалось получить цены, добавляем пустые значения
                for product_data in products_data:
                    product_data["min_price"] = None
        
        # Рендерим карточки для воркспейса используя унифицированный шаблон
        cards_html = []
        for product_data in products_data:
            # Используем унифицированный шаблон
            card_html = templates.get_template("catalog_new_blocks/product_card.html").render(
                product=product_data,
                selected_products=[],
                current_user=current_user,
                context="workspace"
            )
            # Модифицируем для воркспейса
            card_html = modify_card_for_workspace(card_html, product_data['sku'])
            cards_html.append(card_html)
        
        return JSONResponse(content={
            "html": "".join(cards_html),
            "count": len(cards_html)
        })
        
    except Exception as e:
        logger.error(f"Ошибка при получении карточек воркспейса: {e}")
        return JSONResponse(content={"html": "", "count": 0})

@catalog_router.get("/{sku}/card")
async def get_product_card(
    request: Request,
    sku: str,
    context: str = Query("catalog", description="Контекст отображения: catalog, workspace"),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Получить HTML карточки товара по SKU для обновления на странице
    context: catalog - для каталога (с возможностью добавления в воркспейс)
             workspace - для воркспейса (с кнопкой удаления)
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    # Получаем товар с остатками
    product_query = (
        select(
            Product,
            func.sum(Stock.quantity).label('total_stock')
        )
        .outerjoin(Stock, Stock.sku == Product.sku)
        .where(Product.sku == sku)
        .group_by(Product.sku)
    )
    
    result = await db.exec(product_query)
    product_row = result.first()
    
    if not product_row:
        raise HTTPException(status_code=404, detail="Товар не найден")
    
    product = product_row[0]
    total_stock = product_row[1] or 0
    
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
        "has_image": bool(product.original_image),  # Проверяем наличие оригинального изображения
        "total_stock": total_stock,
        "stocks": {}
    }
    
    # Инициализируем остатки для всех складов как 0
    for warehouse in Warehouses:
        product_data["stocks"][warehouse.value] = 0
        
    # Заполняем фактические остатки
    for stock in stocks:
        product_data["stocks"][stock.warehouse] = stock.quantity
    
    # Получаем цену если доступен сервис цен
    if prices_service.is_available():
        try:
            price_info = prices_service.get_price_by_sku(product.sku)
            product_data["min_price"] = float(price_info.min_price) if price_info and price_info.min_price else None
        except Exception as e:
            logger.error(f"Ошибка получения цены для SKU {sku}: {str(e)}")
            product_data["min_price"] = None
    else:
        product_data["min_price"] = None
    
    # Генерируем HTML карточки товара
    html = templates.get_template("catalog_new_blocks/product_card.html").render(
        product=product_data,
        selected_products=[],
        current_user=current_user,
        context=context
    )
    
    # Модифицируем HTML в зависимости от контекста
    if context == "workspace":
        # Для воркспейса: удаляем onclick и добавляем кнопку удаления
        html = modify_card_for_workspace(html, sku)
    # Для каталога оставляем как есть (с onclick для добавления в воркспейс)
    
    return JSONResponse(content={
        "html": html,
        "data": product_data
    })

@catalog_router.post("/cards")
async def get_product_cards(
    request: Request,
    skus: List[str] = Body(...),
    context: str = Body("catalog", description="Контекст отображения: catalog, workspace"),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Получить HTML карточки товаров по массиву SKU для обновления на странице
    context: catalog - для каталога (с возможностью добавления в воркспейс)
             workspace - для воркспейса (с кнопкой удаления)
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    if not skus:
        return JSONResponse(content={"html": "", "count": 0})
    
    try:
        # Получаем товары с остатками
        product_query = (
            select(
                Product,
                func.sum(Stock.quantity).label('total_stock')
            )
            .outerjoin(Stock, Stock.sku == Product.sku)
            .where(Product.sku.in_(skus))
            .group_by(Product.sku)
        )
        
        result = await db.exec(product_query)
        products_with_stocks = result.all()
        
        if not products_with_stocks:
            return JSONResponse(content={"html": "", "count": 0})
        
        # Создаем список продуктов с их остатками
        products_data = []
        for row in products_with_stocks:
            product = row[0]
            total_stock = row[1] or 0
            
            # Получаем остатки для продукта
            stocks_query = select(Stock).where(Stock.sku == product.sku)
            stocks_result = await db.exec(stocks_query)
            stocks = stocks_result.all()
            
            # Создаем словарь с данными продукта
            product_data = {
                "id": product.sku,
                "sku": product.sku,
                "name": product.name,
                "brand": product.brand,
                "eans": product.eans,
                "ean": product.eans[0] if product.eans else None,
                "image": base64.b64encode(product.image).decode('utf-8') if product.image else None,
                "has_image": bool(product.original_image),  # Проверяем наличие оригинального изображения
                "total_stock": total_stock,
                "stocks": {}
            }
            
            # Инициализируем остатки для всех складов как 0
            for warehouse in Warehouses:
                product_data["stocks"][warehouse.value] = 0
                
            # Заполняем фактические остатки
            for stock in stocks:
                product_data["stocks"][stock.warehouse] = stock.quantity
            
            # Получаем цену если доступен сервис цен
            if prices_service.is_available():
                try:
                    price_info = prices_service.get_price_by_sku(product.sku)
                    product_data["min_price"] = float(price_info.min_price) if price_info and price_info.min_price else None
                except Exception as e:
                    logger.error(f"Ошибка получения цены для SKU {product.sku}: {str(e)}")
                    product_data["min_price"] = None
            else:
                product_data["min_price"] = None
            
            products_data.append(product_data)
        
        # Рендерим карточки используя унифицированный шаблон
        cards_html = []
        for product_data in products_data:
            # Используем унифицированный шаблон
            card_html = templates.get_template("catalog_new_blocks/product_card.html").render(
                product=product_data,
                selected_products=[],
                current_user=current_user,
                context=context
            )
            
            # Модифицируем HTML в зависимости от контекста
            if context == "workspace":
                card_html = modify_card_for_workspace(card_html, product_data['sku'])
            # Для каталога оставляем как есть (с onclick для добавления в воркспейс)
            
            cards_html.append(card_html)
        
        return JSONResponse(content={
            "html": "".join(cards_html),
            "count": len(cards_html),
            "context": context
        })
        
    except Exception as e:
        logger.error(f"Ошибка при получении карточек товаров: {e}")
        return JSONResponse(content={"html": "", "count": 0})

@router.post("")
async def create_product(
    request: Request,
    name: str = Form(...),
    name_eng: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    sku: str = Form(...),
    ean: Optional[str] = Form(None),
    warehouse: str = Form(...),
    quantity: int = Form(...),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional),
    operations_service: OperationsService = Depends(get_operations_service),
    manager: InventoryManager = Depends(get_manager)
):
    """Создает новый товар в базе данных."""
    logger.info(f"Creating product: SKU={sku}, name={name}")
    
    try:
        # Проверяем, что выбран допустимый склад
        valid_warehouses = [w.value for w in Warehouses]
        
        if warehouse not in valid_warehouses:
            error_msg = f"Выбран недопустимый склад: {warehouse}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )

        # Обработка изображения
        compressed_image = None
        original_image = None
        image_url = None
        
        if image:
            # Проверяем размер файла (5MB максимум)
            MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB в байтах
            file_size = 0
            raw_image_data = bytearray()
            
            while chunk := await image.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    error_msg = f"Размер файла превышает 5MB"
                    logger.error(error_msg)
                    raise HTTPException(
                        status_code=400,
                        detail=error_msg
                    )
                raw_image_data.extend(chunk)
            
            if file_size:
                # Получаем base_url из запроса для формирования полных ссылок
                scheme = request.headers.get('x-forwarded-proto', 'https' if request.url.scheme == 'https' else 'http')
                host = request.headers.get('host', str(request.base_url.hostname))
                base_url = f"{scheme}://{host}"
                
                # Используем метод compress_image из InventoryManager для правильной обработки
                try:
                    compressed_image, original_image, image_url = manager.compress_image(
                        bytes(raw_image_data), sku, base_url
                    )
                except Exception as img_error:
                    logger.error(f"Ошибка при обработке изображения: {img_error}")
                    compressed_image = None
                    original_image = None
                    image_url = None

        # Разбиваем строку EAN по запятой и очищаем от пробелов
        eans = [e.strip() for e in ean.split(',')] if ean else []

        # Создаем новый товар с сохранением как сжатого, так и оригинального изображения
        new_product = Product(
            sku=sku,
            name=name,
            name_eng=name_eng,
            brand=brand,
            eans=eans,
            image=compressed_image,
            original_image=original_image,
            image_url=image_url
        )
        
        # Добавляем начальные остатки
        if quantity:
            stock = Stock(
                sku=new_product.sku,
                warehouse=warehouse,
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
        
        logger.info(f"Product created successfully: SKU={sku}")
        return {"success": True, "sku": new_product.sku}
        
    except Exception as e:
        logger.error(f"Error creating product: {str(e)}")
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
        
        logger.info(f"Product deleted: SKU={sku}")
        return {"message": "Товар успешно удален"}
        
    except Exception as e:
        logger.error(f"Error deleting product: {str(e)}")
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
    name_eng: Optional[str] = Form(None),
    new_sku: Optional[str] = Form(None),
    brand: Optional[str] = Form(None),
    ean: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional),
    operations_service: OperationsService = Depends(get_operations_service),
    manager: InventoryManager = Depends(get_manager)
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
            "name_eng": product.name_eng,
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
        
        if name_eng is not None:
            product.name_eng = name_eng if name_eng.strip() else None
        
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
            raw_image_data = bytearray()
            
            while chunk := await image.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail="Размер файла превышает 5MB"
                    )
                raw_image_data.extend(chunk)
            
            if file_size:
                # Используем актуальный SKU для генерации URL
                current_sku = new_sku if new_sku else sku
                # Получаем base_url из запроса для формирования полных ссылок
                # Проверяем заголовки прокси для определения правильной схемы
                scheme = request.headers.get('x-forwarded-proto', 'https' if request.url.scheme == 'https' else 'http')
                host = request.headers.get('host', str(request.base_url.hostname))
                base_url = f"{scheme}://{host}"
                
                # Используем метод compress_image из InventoryManager для правильной обработки
                compressed_image, original_image, image_url = manager.compress_image(
                    bytes(raw_image_data), current_sku, base_url
                )
                
                if compressed_image:
                    # Обновляем все поля изображения
                    product.image = compressed_image
                    product.original_image = original_image
                    product.image_url = image_url
                    
                    logger.info(f"Размер сжатого изображения: {len(compressed_image) / 1024:.2f} КБ")
                    logger.info(f"Размер оригинального изображения: {len(original_image) / 1024:.2f} КБ")
                else:
                    logger.warning("Не удалось обработать изображение")
        
        # Сохраняем изменения
        await db.commit()
        await db.refresh(product)
        
        # Подготавливаем новые значения для логирования
        new_values = {
            "sku": product.sku,
            "name": product.name,
            "name_eng": product.name_eng,
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


@router.post("/sync-settings/{account_name}/sync-stocks")
async def sync_all_stocks_for_account(
    account_name: str,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Запустить синхронизацию остатков для всех товаров конкретного аккаунта Allegro.
    Синхронизирует только товары с включенной синхронизацией остатков для данного аккаунта.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    # Получаем токены из микросервиса Allegro
    try:
        # Создаем JWT токен для аутентификации с микросервисом
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        
        # Получаем активные токены из микросервиса
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token
        )
        
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if tokens_response.total == 0 or not tokens_response.items:
            raise HTTPException(status_code=404, detail="Активные токены Allegro не найдены")
        
        # Ищем токен по имени аккаунта
        target_token = None
        for token in tokens_response.items:
            if token['account_name'] == account_name:
                target_token = token
                break
        
        if not target_token:
            raise HTTPException(status_code=404, detail=f"Аккаунт Allegro '{account_name}' не найден")
        
        # Запускаем задачу синхронизации остатков для всех товаров аккаунта
        task = celery.send_task(
            'app.services.allegro.sync_tasks.sync_allegro_stock_single_account',
            args=[target_token['id'], []]  # Пустой список SKU означает синхронизацию всех товаров аккаунта
        )
        
        return {
            "success": True,
            "message": f"Синхронизация остатков всех товаров для аккаунта {account_name} запущена",
            "task_id": task.id,
            "account_name": account_name,
            "token_id": str(target_token['id'])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при запуске синхронизации остатков для аккаунта {account_name}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации остатков: {str(e)}"
        )


@router.post("/sync-settings/{account_name}/sync-all")
async def sync_all_offers_for_account(
    account_name: str,
    request: Request,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Запустить синхронизацию цен для всех товаров конкретного аккаунта Allegro.
    Игнорирует флаг price_sync_enabled и синхронизирует все товары с настройками для данного аккаунта.
    Если передан custom_multiplier, то обновляет мультипликатор для всех товаров аккаунта.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    # Получаем токены из микросервиса Allegro для проверки существования аккаунта
    try:
        # Создаем JWT токен для аутентификации с микросервисом
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        
        # Получаем активные токены из микросервиса
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token
        )
        
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if tokens_response.total == 0 or not tokens_response.items:
            raise HTTPException(status_code=404, detail="Активные токены Allegro не найдены")
        
        # Ищем токен по имени аккаунта
        target_token = None
        for token in tokens_response.items:
            if token['account_name'] == account_name:
                target_token = token
                break
        
        if not target_token:
            raise HTTPException(status_code=404, detail=f"Аккаунт Allegro '{account_name}' не найден")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении токенов из микросервиса для аккаунта {account_name}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при проверке аккаунта Allegro: {str(e)}"
        )
    
    # Получаем данные из запроса
    try:
        body = await request.json()
        custom_multiplier = body.get("custom_multiplier")
    except:
        custom_multiplier = None
    
    # Если передан кастомный мультипликатор, обновляем настройки всех товаров для этого аккаунта
    if custom_multiplier is not None:
        if custom_multiplier <= 0 or custom_multiplier > 10:
            raise HTTPException(
                status_code=400,
                detail="Мультипликатор должен быть положительным числом от 0.1 до 10"
            )
        
        try:
            # Получаем все настройки синхронизации для данного аккаунта
            settings_query = select(ProductAllegroSyncSettings).where(
                ProductAllegroSyncSettings.allegro_account_name == account_name
            )
            settings_result = await db.exec(settings_query)
            all_settings = settings_result.all()
            
            # Обновляем мультипликатор для всех найденных настроек
            updated_count = 0
            for settings_item in all_settings:
                settings_item.price_multiplier = custom_multiplier
                settings_item.updated_at = datetime.utcnow()
                updated_count += 1
            
            # Если есть товары без настроек синхронизации, создаём для них новые с кастомным мультипликатором
            # Получаем все товары
            products_query = select(Product)
            products_result = await db.exec(products_query)
            all_products = products_result.all()
            
            # Получаем SKU товаров, которые уже имеют настройки для данного аккаунта
            existing_skus = {settings_item.product_sku for settings_item in all_settings}
            
            # Создаём настройки для товаров без настроек
            created_count = 0
            for product in all_products:
                if product.sku not in existing_skus:
                    new_settings = ProductAllegroSyncSettings(
                        product_sku=product.sku,
                        allegro_account_name=account_name,
                        stock_sync_enabled=False,
                        price_sync_enabled=False,
                        price_multiplier=custom_multiplier
                    )
                    db.add(new_settings)
                    created_count += 1
            
            await db.commit()
            
            logger.info(f"Обновлен мультипликатор {custom_multiplier} для {updated_count} товаров и создано {created_count} новых настроек для аккаунта {account_name}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Ошибка при обновлении мультипликатора для аккаунта {account_name}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при обновлении мультипликатора: {str(e)}"
            )
    
    # Запускаем задачу синхронизации для всех товаров аккаунта
    try:
        task = celery.send_task(
            'app.services.allegro.sync_tasks.sync_all_offers_for_account',
            args=[account_name]
        )
        
        message = f"Синхронизация всех товаров для аккаунта {account_name} запущена"
        if custom_multiplier is not None:
            message += f" с установкой мультипликатора {custom_multiplier} для всех товаров"
        
        return {
            "success": True,
            "message": message,
            "task_id": task.id,
            "account_name": account_name,
            "custom_multiplier_applied": custom_multiplier is not None,
            "custom_multiplier": custom_multiplier
        }
    except Exception as e:
        logger.error(f"Ошибка при запуске массовой синхронизации для аккаунта {account_name}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации: {str(e)}"
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
    
    # Проверяем существование аккаунта Allegro через микросервис
    try:
        # Создаем JWT токен для аутентификации с микросервисом
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        
        # Получаем активные токены из микросервиса
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token
        )
        
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if tokens_response.total == 0 or not tokens_response.items:
            raise HTTPException(status_code=404, detail="Активные токены Allegro не найдены")
        
        # Ищем токен по имени аккаунта
        target_token = None
        for token in tokens_response.items:
            if token['account_name'] == account_name:
                target_token = token
                break
        
        if not target_token:
            raise HTTPException(status_code=404, detail=f"Аккаунт Allegro '{account_name}' не найден")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении токенов из микросервиса для аккаунта {account_name}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при проверке аккаунта Allegro: {str(e)}"
        )
    
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
    
    # Проверяем существование аккаунта Allegro через микросервис
    try:
        # Создаем JWT токен для аутентификации с микросервисом
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        
        # Получаем активные токены из микросервиса
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token
        )
        
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if tokens_response.total == 0 or not tokens_response.items:
            raise HTTPException(status_code=404, detail="Активные токены Allegro не найдены")
        
        # Ищем токен по имени аккаунта
        target_token = None
        for token in tokens_response.items:
            if token['account_name'] == account_name:
                target_token = token
                break
        
        if not target_token:
            raise HTTPException(status_code=404, detail=f"Аккаунт Allegro '{account_name}' не найден")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении токенов из микросервиса для аккаунта {account_name}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при проверке аккаунта Allegro: {str(e)}"
        )
    
    # Получаем настройки синхронизации (создаем если нет)
    settings_query = select(ProductAllegroSyncSettings).where(
        ProductAllegroSyncSettings.product_sku == sku,
        ProductAllegroSyncSettings.allegro_account_name == account_name
    )
    settings_result = await db.exec(settings_query)
    settings = settings_result.first()
    
    sync_was_disabled = False
    if not settings:
        # Создаем новые настройки с включенной синхронизацией цены
        settings = ProductAllegroSyncSettings(
            product_sku=sku,
            allegro_account_name=account_name,
            stock_sync_enabled=False,
            price_sync_enabled=True,
            price_multiplier=1.0
        )
        db.add(settings)
        sync_was_disabled = True
    elif not settings.price_sync_enabled:
        # Автоматически включаем синхронизацию цены
        settings.price_sync_enabled = True
        settings.updated_at = datetime.utcnow()
        sync_was_disabled = True
    
    await db.commit()
    await db.refresh(settings)
    
    # Получаем цену товара из сервиса цен
    price_data = prices_service.get_price_by_sku(sku)
    if not price_data or price_data.min_price is None or price_data.min_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="У товара не указана корректная минимальная цена. Установите цену больше 0."
        )
    
    # Запускаем задачу синхронизации цены принудительно (независимо от настроек)
    try:
        task = celery.send_task(
            'app.services.allegro.sync_tasks.sync_allegro_price_single_product_account',
            args=[sku, account_name]
        )
        
        message = f"Синхронизация цены для товара {sku} и аккаунта {account_name} запущена"
        if sync_was_disabled:
            message += " (автоматическая синхронизация включена)"
        
        return {
            "success": True,
            "message": message,
            "task_id": task.id,
            "sku": sku,
            "account_name": account_name,
            "price_sync_enabled": True,
            "sync_was_auto_enabled": sync_was_disabled
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

    # Получаем все токены Allegro через микросервис
    try:
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token
        )
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if tokens_response.total == 0 or not tokens_response.items:
            allegro_tokens = []
        else:
            allegro_tokens = tokens_response.items
    except Exception as e:
        logger.error(f"Ошибка при получении токенов из микросервиса: {str(e)}")
        allegro_tokens = []

    
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
            if price_info and price_info.min_price:
                product_data['min_price'] = float(price_info.min_price)
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
    for token in allegro_tokens:
        account_name = token.get('account_name') or f"Account {str(token.get('id', ''))[:8]}"
        
        # Получаем существующие настройки или создаем дефолтные
        sync_settings = settings_by_account.get(account_name)
        if sync_settings:
            token_data = {
                'token_id': str(token.get('id', '')),
                'account_name': account_name,
                'stock_sync_enabled': sync_settings.stock_sync_enabled,
                'price_sync_enabled': sync_settings.price_sync_enabled,
                'price_multiplier': float(sync_settings.price_multiplier),
                'last_stock_sync_at': sync_settings.last_stock_sync_at,
                'last_price_sync_at': sync_settings.last_price_sync_at,
                'has_settings': True
            }
        else:
            # Дефолтные настройки для токена без настроек
            token_data = {
                'token_id': str(token.get('id', '')),
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
    Получает список оферт для товара в конкретном аккаунте Allegro через микросервис.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    try:
        logger.info(f"[OFFERS] Запрос оферт для SKU {sku} в аккаунте {account_name}")
        
        # Получаем токен аккаунта через микросервис
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        token_client = AllegroTokenMicroserviceClient(
            jwt_token=jwt_token
        )
        tokens_response = token_client.get_tokens(per_page=100, active_only=True)
        
        if tokens_response.total == 0 or not tokens_response.items:
            raise HTTPException(status_code=404, detail="Активные токены Allegro не найдены")
        
        all_tokens = tokens_response.items
        
        # Ищем нужный токен по account_name
        token = None
        for t in all_tokens:
            if t['account_name'] == account_name:
                token = t
                break

        if not token:
            logger.error(f"[OFFERS] Токен для аккаунта {account_name} не найден")
            raise HTTPException(status_code=404, detail="Аккаунт Allegro не найден")
        
        token_id = token['id']
        if not token_id:
            logger.error(f"[OFFERS] ID токена отсутствует для аккаунта {account_name}")
            raise HTTPException(status_code=500, detail="Некорректные данные токена")
        
        logger.info(f"[OFFERS] Токен найден для аккаунта {account_name}, ID: {token_id}")
        
        # Проверяем существование товара
        product_query = select(Product).where(Product.sku == sku)
        product_result = await db.exec(product_query)
        product = product_result.first()
        
        if not product:
            logger.error(f"[OFFERS] Товар с SKU {sku} не найден")
            raise HTTPException(status_code=404, detail="Товар не найден")
        
        logger.info(f"[OFFERS] Товар найден: {product.name}")
        
        # Создаем клиент микросервиса для работы с офферами
        offers_client = AllegroOffersMicroserviceClient(
            jwt_token=jwt_token
        )
        
        # Получаем оферты через микросервис, используя SKU как external_id
        logger.info(f"[OFFERS] Запрос к микросервису офферов для external_id={sku}")
        offers_response = offers_client.get_offers_by_external_id(
            token_ids=[token_id],
            external_id=sku
        )
        
        # Получаем данные из OfferListResponse.offers
        offers_data = offers_response.offers
        
        logger.info(f"[OFFERS] Получен ответ от микросервиса: {len(offers_data) if offers_data else 0} результатов")
        
        # Обрабатываем ответ микросервиса
        processed_offers = []
        total_count = 0
        
        # Ищем результат для нашего токена
        token_result = None
        for result in offers_data:
            if result.get("token_id") == str(token_id):
                token_result = result
                break
        
        if token_result and not token_result.get("error"):
            offers_list = token_result.get("offers", [])
            total_count = token_result.get("offers_count", 0)
            logger.info(f"[OFFERS] Количество оферт в ответе: {len(offers_list)}")
            
            # Обрабатываем каждую оферту для совместимости с фронтендом
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
        elif token_result and token_result.get("error"):
            logger.error(f"[OFFERS] Ошибка от микросервиса: {token_result.get('error')}")
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка получения оферт: {token_result.get('error')}"
            )
        else:
            logger.warning(f"[OFFERS] Результат для токена {token_id} не найден")
        
        logger.info(f"[OFFERS] Обработано оферт: {len(processed_offers)}")
        
        return {
            "success": True,
            "offers": processed_offers,
            "count": len(processed_offers),
            "total_count": total_count,
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


@router.get("/{sku}/image/original")
async def get_original_image(
    sku: str,
    db: AsyncSession = Depends(deps.get_async_session),
):
    """
    Возвращает оригинальное изображение товара по SKU.
    """
    # Получаем товар из базы данных
    product_query = select(Product).where(Product.sku == sku)
    result = await db.exec(product_query)
    product = result.first()
    
    if not product:
        raise HTTPException(
            status_code=404,
            detail="Товар не найден"
        )
    
    if not product.original_image:
        raise HTTPException(
            status_code=404,
            detail="Оригинальное изображение отсутствует"
        )
    
    # Определяем MIME тип по первым байтам изображения
    image_data = product.original_image
    if image_data.startswith(b'\xff\xd8\xff'):
        media_type = "image/jpeg"
    elif image_data.startswith(b'\x89PNG\r\n\x1a\n'):
        media_type = "image/png"
    elif image_data.startswith(b'RIFF') and b'WEBP' in image_data[:12]:
        media_type = "image/webp"
    elif image_data.startswith(b'GIF87a') or image_data.startswith(b'GIF89a'):
        media_type = "image/gif"
    else:
        # По умолчанию считаем JPEG
        media_type = "image/jpeg"
    
    return Response(
        content=image_data,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400",  # Кэшируем на сутки
            "Content-Disposition": f"inline; filename={sku}_original.jpg"
        }
    )

@router.get("/{sku}/exists")
async def check_product_exists(
    sku: str,
    db: AsyncSession = Depends(deps.get_async_session)
):
    """
    Проверяет существование товара по SKU.
    Возвращает простой ответ без требований авторизации.
    """
    try:
        # Получаем товар из базы данных
        product_query = select(Product).where(Product.sku == sku)
        result = await db.exec(product_query)
        product = result.first()
        
        if product:
            return {"exists": True, "sku": sku, "name": product.name}
        else:
            return {"exists": False, "sku": sku}
            
    except Exception as e:
        logger.error(f"Ошибка при проверке существования товара {sku}: {e}")
        # В случае ошибки возвращаем False для безопасности
        return {"exists": False, "sku": sku, "error": "Database error"}

@router.post("/bulk-delete")
async def bulk_delete_products(
    request: BulkDeleteRequest,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional),
    operations_service: OperationsService = Depends(get_operations_service)
):
    """
    Массовое удаление товаров по списку SKU
    """
    skus = request.skus
    logger.info(f"Bulk delete request received. SKUs: {skus}")
    logger.info(f"Current user: {current_user.email if current_user else 'None'}")
    
    # Проверяем права доступа
    if not current_user:
        logger.error("No current user found")
        raise HTTPException(
            status_code=401,
            detail="Пользователь не авторизован"
        )
    
    if not current_user.is_admin:
        logger.error(f"User {current_user.email} is not admin")
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для удаления товаров"
        )
    
    if not skus:
        logger.error("Empty SKUs list received")
        raise HTTPException(
            status_code=400,
            detail="Список SKU не может быть пустым"
        )
    
    logger.info(f"Starting bulk delete for {len(skus)} products")
    
    try:
        deleted_products = []
        failed_deletions = []
        
        for sku in skus:
            try:
                # Проверяем существование товара
                product_query = select(Product).where(Product.sku == sku)
                product = await db.exec(product_query)
                product = product.first()
                
                if not product:
                    failed_deletions.append({"sku": sku, "error": "Товар не найден"})
                    continue

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
                
                # Создаем запись операции
                operations_service.create_product_delete_operation(
                    sku=sku,
                    user_email=current_user.email
                )
                
                deleted_products.append(product_info)
                logger.info(f"Product deleted: SKU={sku}")
                
            except Exception as e:
                logger.error(f"Error deleting product {sku}: {str(e)}")
                failed_deletions.append({"sku": sku, "error": str(e)})
                continue
        
        # Применяем все изменения
        await db.commit()
        
        return {
            "success": True,
            "message": f"Удалено товаров: {len(deleted_products)}, ошибок: {len(failed_deletions)}",
            "deleted_products": deleted_products,
            "failed_deletions": failed_deletions,
            "total_requested": len(skus),
            "total_deleted": len(deleted_products),
            "total_failed": len(failed_deletions)
        }
        
    except Exception as e:
        logger.error(f"Error in bulk delete: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при массовом удалении товаров: {str(e)}"
        )


@router.post("/sync-all-accounts/stocks")
async def sync_all_accounts_stocks(
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Запустить синхронизацию остатков для всех аккаунтов Allegro.
    
    Эта функция запускает массовую синхронизацию остатков по всем активным аккаунтам Allegro.
    Для каждого аккаунта синхронизируются только те товары, для которых включена 
    синхронизация остатков в настройках ProductAllegroSyncSettings.
    
    Returns:
        Dict: Результат запуска задачи с информацией о количестве аккаунтов
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    try:
        # Запускаем задачу синхронизации остатков для всех аккаунтов
        task = celery.send_task(
            'app.services.allegro.sync_tasks.sync_allegro_stock_all_accounts'
        )
        
        logger.info(f"Запущена массовая синхронизация остатков для всех аккаунтов. Task ID: {task.id}")
        
        return {
            "success": True,
            "message": "Синхронизация остатков для всех аккаунтов Allegro запущена",
            "task_id": task.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Ошибка при запуске массовой синхронизации остатков: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске синхронизации: {str(e)}"
        )


@router.post("/sync-all-accounts/stocks/force")
async def sync_all_accounts_stocks_force(
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Запустить ПРИНУДИТЕЛЬНУЮ синхронизацию остатков для всех аккаунтов Allegro.
    
    ВНИМАНИЕ: Эта функция ИГНОРИРУЕТ флаг включения синхронизации остатков в настройках
    ProductAllegroSyncSettings и синхронизирует ВСЕ товары для всех активных аккаунтов.
    
    Эта функция может быть ресурсоемкой и должна использоваться только в исключительных случаях,
    например, при восстановлении после сбоев или при необходимости полной пересинхронизации.
    
    Returns:
        Dict: Результат запуска задачи с информацией о количестве аккаунтов
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора")
    
    try:
        # Запускаем принудительную задачу синхронизации остатков для всех аккаунтов
        task = celery.send_task(
            'app.services.allegro.sync_tasks.sync_allegro_stock_all_accounts_force'
        )
        
        logger.warning(f"Запущена ПРИНУДИТЕЛЬНАЯ массовая синхронизация остатков для всех аккаунтов. Task ID: {task.id}")
        logger.warning("ВНИМАНИЕ: Игнорируется флаг включения синхронизации остатков!")
        
        return {
            "success": True,
            "message": "ПРИНУДИТЕЛЬНАЯ синхронизация остатков для всех аккаунтов Allegro запущена",
            "task_id": task.id,
            "timestamp": datetime.utcnow().isoformat(),
            "force_mode": True,
            "warning": "Игнорируется флаг включения синхронизации остатков"
        }
        
    except Exception as e:
        logger.error(f"Ошибка при запуске принудительной массовой синхронизации остатков: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при запуске принудительной синхронизации: {str(e)}"
        )
