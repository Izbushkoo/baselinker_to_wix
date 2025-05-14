from fastapi import APIRouter, Request, HTTPException, Depends, Body, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, Dict, Any
from app.core.config import settings
from app.models.user import User
from app.api import deps
from app.services.telegram_service import telegram_service
import logging
import json
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote_plus
from app.services.warehouse import manager
from app.services.operations_service import get_operations_service
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.warehouse import Product, Stock
from sqlmodel import select, or_, func
import base64
from app.services.warehouse.manager import Warehouses
from app.services.user import get_user_by_tg_nickname, create_user
from app.schemas.user import UserCreate
from app.core.security import create_access_token
import uuid

# Хранилище для отслеживания обработанных update_id
processed_updates = set()

class InitPayload(BaseModel):
    initData: str

router = APIRouter(prefix="/tg", tags=["telegram"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

@router.post("/validate_init")
async def validate_init(
    init_data: str = Body(..., media_type="text/plain"),
    db: AsyncSession = Depends(deps.get_async_session)
):
    """
    Валидация initData от Telegram Web App
    """
    try:
        logger.info(f"Received initData for validation: {init_data}")
        
        # Проверяем валидность initData
        if not telegram_service.validate_init_data(init_data):
            logger.error("Invalid Telegram initData")
            raise HTTPException(
                status_code=400,
                detail="Invalid Telegram initData"
            )
            
        # Парсим данные пользователя
        data_dict = {}
        for pair in init_data.lstrip('?').split('&'):
            if '=' not in pair:
                continue
            k, v = pair.split('=', 1)
            if k == 'user':
                try:
                    data_dict[k] = json.loads(unquote_plus(v))
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse user data: {v}")
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid user data format"
                    )

        tg_user = data_dict.get('user', {})
        tg_username = tg_user.get('username')

        if not tg_username:
            raise HTTPException(
                status_code=400,
                detail="Telegram username not found"
            )

        # Проверяем существует ли пользователь
        user = await get_user_by_tg_nickname(db, tg_username)

        if not user:
            # Создаем нового пользователя
            random_password = str(uuid.uuid4())
            user_create = UserCreate(
                email=f"{tg_username}@telegram.user",
                password=random_password,
                full_name=tg_user.get('first_name', '') + ' ' + tg_user.get('last_name', ''),
                tg_nickname=tg_username
            )
            user = await create_user(db, user_create)

        # Создаем access token
        access_token = create_access_token(
            subject=str(user.id),
            expires_delta=timedelta(minutes=3600)
        )

        response = JSONResponse({
            "status": "success",
            "user": data_dict.get('user'),
            "access_token": access_token
        })

        # Устанавливаем cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=True,
            max_age=3600,
            expires=3600,
        )
        logger.info(f"Access token: {access_token}")
        return response
        
    except Exception as e:
        logger.error(f"Error validating initData: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

@router.get("/webapp", response_class=HTMLResponse)
async def telegram_webapp(
    request: Request,
    current_user: Optional[User] = Depends(deps.get_current_user_optional),
    inventory_manager: manager.InventoryManager = Depends(manager.get_manager)
):
    """
    Обработчик для Telegram Web App
    """
    try:

        logger.info(f"Current user: {current_user}")

        total_products = await inventory_manager.count_products()
        low_stock = await inventory_manager.get_low_stock_products()
        operations_service = get_operations_service()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now()
        today_stats = operations_service.get_operations_stats(today_start, today_end)
        today_ops = today_stats["total"] if isinstance(today_stats, dict) and "total" in today_stats else 0

        return templates.TemplateResponse(
            "tg_main.html",
            {
                "request": request,
                "user": current_user,
                "webapp_url": settings.TELEGRAM_WEBAPP_URL,
                "total_products": total_products,
                "low_stock": low_stock,
                "today_ops": today_ops
            }
        )
    except Exception as e:
        logger.error(f"Error in telegram webapp: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Обработчик вебхуков от Telegram
    """
    try:
        update = await request.json()
        update_id = update.get("update_id")
        
        # Проверяем, не обрабатывали ли мы уже это обновление
        if update_id in processed_updates:
            logger.info(f"Duplicate update_id {update_id}, skipping")
            return {"status": "ok", "message": "Duplicate update"}
            
        # Добавляем update_id в обработанные
        processed_updates.add(update_id)
        
        # Очищаем старые update_id (оставляем только последние 1000)
        if len(processed_updates) > 1000:
            processed_updates.clear()
        
        logger.info(f"Processing Telegram update: {update}")
        
        # Обработка различных типов обновлений
        if "message" in update:
            message = update["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text", "")
            
            # Обработка команд
            if text.startswith("/"):
                command = text.split()[0][1:]
                if command == "start":
                    # Создаем клавиатуру с кнопкой для Web App
                    keyboard = {
                        "inline_keyboard": [[
                            {
                                "text": "Открыть приложение",
                                "web_app": {"url": settings.TELEGRAM_WEBAPP_URL}
                            }
                        ]]
                    }
                    
                    await telegram_service.send_message(
                        chat_id,
                        "Добро пожаловать! Нажмите кнопку ниже, чтобы открыть приложение.",
                        reply_markup=keyboard
                    )
                elif command == "help":
                    await telegram_service.send_message(
                        chat_id,
                        "Список доступных команд:\n/start - Начать работу\n/help - Показать помощь"
                    )
        
        elif "callback_query" in update:
            callback_query = update["callback_query"]
            callback_id = callback_query["id"]
            data = callback_query.get("data", "")
            
            # Обработка callback query
            await telegram_service.answer_callback_query(
                callback_id,
                f"Обработка: {data}",
                show_alert=True
            )
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error in telegram webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/setup")
async def setup_webhook():
    """
    Установка вебхука для бота
    """
    try:
        # Сначала удалим старый вебхук
        client = await telegram_service.get_client()
        await client.post("/deleteWebhook")
        
        # Установим новый вебхук
        success = await telegram_service.set_webhook()
        if success:
            # Проверим, что вебхук установлен
            response = await client.get("/getWebhookInfo")
            webhook_info = response.json()
            logger.info(f"Webhook info: {webhook_info}")
            
            return {
                "status": "ok",
                "message": "Webhook установлен успешно",
                "webhook_info": webhook_info
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to set webhook")
    except Exception as e:
        logger.error(f"Error setting up webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/webhook_info")
async def get_webhook_info():
    """
    Получение информации о текущем вебхуке
    """
    try:
        client = await telegram_service.get_client()
        response = await client.get("/getWebhookInfo")
        webhook_info = response.json()
        return webhook_info
    except Exception as e:
        logger.error(f"Error getting webhook info: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/catalog")
async def tg_catalog(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    search: Optional[str] = None,
    stock_filter: Optional[int] = None,
    min_stock_filter: Optional[int] = None,
    sort_order: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    Каталог для Telegram WebApp. Повторяет логику обычного каталога, но возвращает tg_catalog.html и карточки tg_product_card.html.
    """
    #   # Базовый запрос для товаров с подсчетом остатков
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
            html = templates.get_template("tg_product_card.html").render(
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
        "tg_catalog.html",
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

@router.get("/add_product", response_class=HTMLResponse)
async def tg_add_product(
    request: Request,
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """Отображает форму добавления нового товара в Telegram WebApp."""
    # Получаем список складов из перечисления
    warehouses = [w.value for w in Warehouses]
    
    return templates.TemplateResponse(
        "tg_add_product.html",
        {
            "request": request,
            "current_user": current_user,
            "warehouses": warehouses
        }
    )

