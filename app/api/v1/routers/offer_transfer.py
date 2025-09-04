"""
 * @file: offer_transfer.py
 * @description: Роутер для фронтенда системы переноса офферов Allegro
 * @dependencies: FastAPI, Jinja2, HTMX
 * @created: 2024-12-19
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import os   
import jwt
from uuid import UUID
from app.core.config import settings
from app.api.deps import get_current_user_from_cookie
from app.models.user import User as UserModel
from app.services.Allegro_Microservice import create_factory
import logging

logger = logging.getLogger(__name__)

# Создаем alias для удобства
CurrentUser = UserModel
CurrentUserDep = Depends(get_current_user_from_cookie)

# Создаем роутер
router = APIRouter()

# Настраиваем шаблоны
templates = Jinja2Templates(directory="app/templates")

# Базовый путь для шаблонов
TEMPLATES_DIR = "app/templates/offer_transfer"

@router.get("/", response_class=HTMLResponse)
async def offer_transfer_index(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Главная страница системы переноса офферов
    """
    logger.info("=== ЗАГРУЗКА ГЛАВНОЙ СТРАНИЦЫ СИСТЕМЫ ПЕРЕНОСА ОФФЕРОВ ===")
    logger.info(f"Пользователь: {current_user.email if current_user else 'Неизвестен'}")
    logger.info(f"ID пользователя: {current_user.id if current_user else 'Неизвестен'}")
    logger.info(f"Админ: {current_user.is_admin if current_user else 'Неизвестен'}")
    logger.info(f"Запрос: {request.method} {request.url}")
    
    try:
        logger.info("=== ПОПЫТКА ПОЛУЧЕНИЯ ТОКЕНОВ ЧЕРЕЗ МИКРОСЕРВИС ===")
        
        # Получаем токены пользователя через микросервис
        logger.info("Создание фабрики микросервиса...")
        factory = get_microservice_client()
        logger.info("Фабрика микросервиса создана успешно")
        
        logger.info("Создание клиента токенов...")
        tokens_client = factory.create_tokens_client()
        logger.info("Клиент токенов создан успешно")
        
        logger.info(f"Вызов get_user_tokens с параметрами:")
        logger.info(f"  - user_id: {settings.PROJECT_NAME}")
        logger.info(f"  - active_only: True")
        
        tokens_response = tokens_client.get_user_tokens(settings.PROJECT_NAME, active_only=True)
        logger.info(f"=== ОТВЕТ ОТ МИКРОСЕРВИСА ПОЛУЧЕН ===")
        logger.info(f"Тип ответа: {type(tokens_response)}")
        logger.info(f"Содержимое ответа: {tokens_response}")
        
        # Преобразуем токены в аккаунты для отображения
        accounts = []
        if hasattr(tokens_response, 'items') and tokens_response.items:
            logger.info(f"Найдено токенов: {len(tokens_response.items)}")
            for i, token in enumerate(tokens_response.items):
                logger.info(f"Обработка токена {i+1}: {token}")
                logger.info(f"Тип токена: {type(token)}")
                logger.info(f"Доступные поля: {dir(token) if hasattr(token, '__dict__') else 'Нет атрибутов'}")
                
                try:
                    account_data = {
                        "id": str(token.get("id") if hasattr(token, 'get') else getattr(token, 'id', f"token_{i}")),
                        "name": f"{token.get('account_name', 'Неизвестный аккаунт') if hasattr(token, 'get') else getattr(token, 'account_name', 'Неизвестный аккаунт')} ({token.get('country_code', 'XX') if hasattr(token, 'get') else getattr(token, 'country_code', 'XX')})",
                        "country_code": token.get('country_code', 'XX') if hasattr(token, 'get') else getattr(token, 'country_code', 'XX')
                    }
                    accounts.append(account_data)
                    logger.info(f"Токен {i+1} обработан: {account_data}")
                except Exception as token_error:
                    logger.error(f"Ошибка при обработке токена {i+1}: {token_error}")
                    # Добавляем fallback данные для этого токена
                    accounts.append({
                        "id": f"error_token_{i}",
                        "name": f"Ошибка загрузки токена {i+1}",
                        "country_code": "XX"
                    })
        else:
            logger.warning("Токены не найдены или пустой ответ")
            logger.info(f"Проверка структуры ответа:")
            logger.info(f"  - hasattr(tokens_response, 'items'): {hasattr(tokens_response, 'items')}")
            if hasattr(tokens_response, 'items'):
                logger.info(f"  - tokens_response.items: {tokens_response.items}")
                logger.info(f"  - len(tokens_response.items): {len(tokens_response.items) if tokens_response.items else 'None'}")
            
        logger.info(f"=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ===")
        logger.info(f"Сформировано аккаунтов: {len(accounts)}")
        logger.info(f"Аккаунты: {accounts}")
            
    except Exception as e:
        logger.error(f"Ошибка при получении токенов: {str(e)}", exc_info=True)
        
        # В случае ошибки используем mock данные
        accounts = [
            {"id": "1", "name": "Аккаунт 1 (PL)", "country_code": "PL"},
            {"id": "2", "name": "Аккаунт 2 (CZ)", "country_code": "CZ"},
            {"id": "3", "name": "Аккаунт 3 (SK)", "country_code": "SK"},
            {"id": "4", "name": "Аккаунт 4 (HU)", "country_code": "HU"},
        ]
        logger.info(f"Используются mock данные: {accounts}")
    
    return templates.TemplateResponse(
        "offer_transfer/index.html",
        {
            "request": request,
            "accounts": accounts,
            "user": current_user  # Передаем пользователя для проверки на админа
        }
    )



@router.get("/markets", response_class=HTMLResponse)
async def offer_transfer_markets(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Страница выбора рынков
    """
    logger.info("=== ЗАГРУЗКА СТРАНИЦЫ РЫНКОВ ===")
    logger.info(f"Пользователь: {current_user.email if current_user else 'Неизвестен'}")
    logger.info(f"Запрос: {request.method} {request.url}")
    
    try:
        logger.info("Попытка получения рынков через микросервис...")
        
        # Получаем рынки через микросервис
        factory = get_microservice_client()
        logger.info("Фабрика микросервиса создана")
        
        client = factory.create_markets_client()
        logger.info("Клиент рынков создан")
        
        logger.info("Вызов get_available_markets...")
        markets_response = await client.get_available_markets()
        logger.info(f"Ответ от микросервиса: {markets_response}")
        
        # Преобразуем данные в формат для шаблона
        markets = []
        for market in markets_response.markets:
            market_data = market.dict()
            # Добавляем fallback для флага, если его нет
            if not market_data.get('flag'):
                market_data['flag'] = '🏳️'  # Дефолтный флаг
            markets.append(market_data)
        logger.info(f"Рынки обработаны: {markets}")
        
    except Exception as e:
        logger.error(f"=== ОШИБКА ПРИ ПОЛУЧЕНИИ РЫНКОВ ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        # В случае ошибки используем mock данные
        logger.info("Использование mock данных для рынков")
        markets = [
            {"code": "PL", "name": "Польша", "currency": "PLN", "flag": "🇵🇱"},
            {"code": "CZ", "name": "Чехия", "currency": "CZK", "flag": "🇨🇿"},
            {"code": "SK", "name": "Словакия", "currency": "EUR", "flag": "🇸🇰"},
            {"code": "HU", "name": "Венгрия", "currency": "HUF", "flag": "🇭🇺"}
        ]
        logger.info(f"Mock рынки: {markets}")
    
    logger.info(f"=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ РЫНКОВ ===")
    logger.info(f"Количество рынков: {len(markets)}")
    
    return templates.TemplateResponse(
        "offer_transfer/markets.html",
        {
            "request": request,
            "markets": markets,
            "user": current_user
        }
    )

@router.get("/pricing", response_class=HTMLResponse)
async def offer_transfer_pricing(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Страница настройки цен
    """
    logger.info("=== ЗАГРУЗКА СТРАНИЦЫ ЦЕН ===")
    logger.info(f"Пользователь: {current_user.email if current_user else 'Неизвестен'}")
    logger.info(f"Запрос: {request.method} {request.url}")
    
    try:
        logger.info("Попытка получения курсов валют через микросервис...")
        
        # Получаем курсы валют через микросервис
        factory = get_microservice_client()
        logger.info("Фабрика микросервиса создана")
        
        client = factory.create_markets_client()
        logger.info("Клиент рынков создан")
        
        logger.info("Вызов get_currency_rates...")
        rates_response = await client.get_currency_rates()
        logger.info(f"Ответ от микросервиса: {rates_response}")
        
        # Преобразуем данные в формат для шаблона
        currency_rates = {
            "rates": rates_response.rates,
            "base_currency": rates_response.base_currency,
            "last_updated": rates_response.last_updated.isoformat() if hasattr(rates_response.last_updated, 'isoformat') else str(rates_response.last_updated)
        }
        logger.info(f"Курсы валют обработаны: {currency_rates}")
        
    except Exception as e:
        logger.error(f"=== ОШИБКА ПРИ ПОЛУЧЕНИИ КУРСОВ ВАЛЮТ ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        # В случае ошибки используем mock данные
        logger.info("Использование mock данных для курсов валют")
        currency_rates = {
            "rates": {
                "PLN": 1.0,
                "CZK": 5.8,
                "EUR": 0.23,
                "HUF": 85.0
            },
            "base_currency": "PLN",
            "last_updated": datetime.utcnow().isoformat()
        }
        logger.info(f"Mock курсы валют: {currency_rates}")
    
    logger.info(f"=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ЦЕН ===")
    logger.info(f"Количество валют: {len(currency_rates.get('rates', {}))}")
    
    return templates.TemplateResponse(
        "offer_transfer/pricing.html",
        {
            "request": request,
            "currency_rates": currency_rates,
            "user": current_user
        }
    )

@router.get("/monitoring", response_class=HTMLResponse)
async def offer_transfer_monitoring(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Страница мониторинга
    """
    # Для мониторинга используем WebSocket и AJAX запросы, 
    # поэтому здесь просто отдаем базовую страницу
    return templates.TemplateResponse(
        "offer_transfer/monitoring.html",
        {
            "request": request,
            "user": current_user
        }
    )

@router.get("/templates", response_class=HTMLResponse)
async def offer_transfer_templates(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Страница управления шаблонами
    """
    logger.info("=== ЗАГРУЗКА СТРАНИЦЫ ШАБЛОНОВ ===")
    logger.info(f"Пользователь: {current_user.email if current_user else 'Неизвестен'}")
    logger.info(f"Запрос: {request.method} {request.url}")
    
    try:
        logger.info("Попытка получения шаблонов через микросервис...")
        
        # Получаем шаблоны через микросервис
        factory = get_microservice_client()
        logger.info("Фабрика микросервиса создана")
        
        client = factory.create_templates_client()
        logger.info("Клиент шаблонов создан")
        
        logger.info("Вызов get_user_templates...")
        templates_list = await client.get_user_templates()
        logger.info(f"Ответ от микросервиса: {templates_list}")
        
        # Преобразуем данные в формат для шаблона
        templates_data = []
        for template in templates_list:
            template_data = template.dict()
            # Добавляем fallback для created_at, если его нет
            if not template_data.get('created_at'):
                template_data['created_at'] = datetime.utcnow().isoformat()
            templates_data.append(template_data)
        logger.info(f"Шаблоны обработаны: {templates_data}")
        
    except Exception as e:
        logger.error(f"=== ОШИБКА ПРИ ПОЛУЧЕНИИ ШАБЛОНОВ ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        # В случае ошибки используем mock данные
        logger.info("Использование mock данных для шаблонов")
        templates_data = [
            {
                "id": "1",
                "name": "Шаблон для Европы",
                "description": "Базовые настройки для европейских рынков",
                "created_at": "2024-12-19T10:00:00Z",
                "is_default": True
            },
            {
                "id": "2", 
                "name": "Электроника +20%",
                "description": "Наценка 20% для электроники",
                "created_at": "2024-12-18T15:30:00Z",
                "is_default": False
            }
        ]
        logger.info(f"Mock шаблоны: {templates_data}")
    
    logger.info(f"=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ШАБЛОНОВ ===")
    logger.info(f"Количество шаблонов: {len(templates_data)}")
    
    return templates.TemplateResponse(
        "offer_transfer/templates.html",
        {
            "request": request,
            "templates": templates_data,
            "user": current_user
        }
    )

@router.get("/metrics", response_class=HTMLResponse)
async def offer_transfer_metrics(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Страница метрик
    """
    logger.info("=== ЗАГРУЗКА СТРАНИЦЫ МЕТРИК ===")
    logger.info(f"Пользователь: {current_user.email if current_user else 'Неизвестен'}")
    logger.info(f"Запрос: {request.method} {request.url}")
    
    try:
        logger.info("Попытка получения метрик через микросервис...")
        
        # Получаем метрики через микросервис
        factory = get_microservice_client()
        logger.info("Фабрика микросервиса создана")
        
        client = factory.create_monitoring_client()
        logger.info("Клиент мониторинга создан")
        
        logger.info("Вызов get_current_metrics...")
        metrics_response = await client.get_current_metrics()
        logger.info(f"Ответ от микросервиса: {metrics_response}")
        
        # Преобразуем данные в формат для шаблона с безопасной обработкой
        try:
            success_rate = (metrics_response.successful_offers / max(metrics_response.total_offers_processed, 1)) * 100
        except (AttributeError, ZeroDivisionError):
            success_rate = 0.0
            
        try:
            avg_time = metrics_response.avg_processing_time_ms / 1000
        except AttributeError:
            avg_time = 0.0
            
        try:
            market_dist = [
                {"market": k, "count": v, "percentage": (v / max(sum(metrics_response.market_distribution.values()), 1)) * 100}
                for k, v in metrics_response.market_distribution.items()
            ]
        except AttributeError:
            market_dist = []
            
        try:
            top_errors = metrics_response.top_errors
        except AttributeError:
            top_errors = []
        
        metrics = {
            "active_sessions": getattr(metrics_response, 'active_sessions', 0),
            "total_processed_offers": getattr(metrics_response, 'total_offers_processed', 0),
            "success_rate": success_rate,
            "average_processing_time": avg_time,
            "market_distribution": market_dist,
            "top_errors": top_errors
        }
        logger.info(f"Метрики обработаны: {metrics}")
    except Exception as e:
        logger.error(f"=== ОШИБКА ПРИ ПОЛУЧЕНИИ МЕТРИК ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        # В случае ошибки используем mock данные
        logger.info("Использование mock данных для метрик")
        metrics = {
            "active_sessions": 3,
            "total_processed_offers": 1247,
            "success_rate": 87.5,
            "average_processing_time": 2.3,
            "market_distribution": [
                {"market": "PL", "count": 450, "percentage": 36.1},
                {"market": "CZ", "count": 320, "percentage": 25.7},
                {"market": "SK", "count": 280, "percentage": 22.5},
                {"market": "HU", "count": 197, "percentage": 15.8}
            ],
            "top_errors": [
                {"error": "Недостаточно остатков", "count": 45, "percentage": 12.3},
                {"error": "Неверная категория", "count": 32, "percentage": 8.7},
                {"error": "Ошибка API Allegro", "count": 28, "percentage": 7.6}
            ]
        }
    
    return templates.TemplateResponse(
        "offer_transfer/metrics.html",
        {
            "request": request,
            "metrics": metrics,
            "user": current_user
        }
    )

# API эндпоинты для HTMX
@router.post("/compare-offers")
async def compare_offers(request: Request, current_user: CurrentUser = CurrentUserDep):
    """
    Сравнение офферов между аккаунтами (HTMX)
    """
    logger.info("=== НАЧАЛО СРАВНЕНИЯ ОФФЕРОВ ===")
    logger.info(f"Пользователь: {current_user.email if current_user else 'Неизвестен'}")
    
    # Получаем данные из формы
    form_data = await request.form()
    source_account = form_data.get("source_account")
    target_account = form_data.get("target_account")
    
    logger.info(f"Данные формы: source_account={source_account}, target_account={target_account}")
    logger.info(f"Типы данных: source_account={type(source_account)}, target_account={type(target_account)}")
    
    # Проверяем, что аккаунты выбраны
    if not source_account or not target_account:
        logger.warning("Не выбраны оба аккаунта")
        raise HTTPException(status_code=400, detail="Необходимо выбрать оба аккаунта")
    
    if source_account == target_account:
        logger.warning("Исходный и целевой аккаунты одинаковые")
        raise HTTPException(status_code=400, detail="Исходный и целевой аккаунты должны быть разными")
    
    try:
        logger.info("=== ПОПЫТКА ПОЛУЧЕНИЯ ОФФЕРОВ ЧЕРЕЗ МИКРОСЕРВИС ===")
        
        # Получаем офферы через микросервис
        logger.info("Создание фабрики микросервиса...")
        factory = get_microservice_client()
        logger.info("Фабрика создана успешно")
        
        logger.info("Создание клиента для переноса офферов...")
        client = factory.create_offer_transfer_client()
        logger.info("Клиент создан успешно")
        
        logger.info(f"Вызов compare_offers с параметрами:")
        logger.info(f"  - source_token_id: {source_account} (тип: {type(source_account)})")
        logger.info(f"  - target_token_id: {target_account} (тип: {type(target_account)})")
        
        # Конвертируем в int для безопасности
        source_token_id = int(source_account)
        target_token_id = int(target_account)
        
        logger.info(f"Конвертированные ID: source={source_token_id}, target={target_token_id}")
        
        result = await client.compare_offers(
            source_token_id=source_token_id,
            target_token_id=target_token_id
        )
        
        logger.info(f"=== ОТВЕТ ОТ МИКРОСЕРВИСА ПОЛУЧЕН ===")
        logger.info(f"Тип ответа: {type(result)}")
        logger.info(f"Содержимое ответа: {result}")
        
        if hasattr(result, 'available_offers'):
            logger.info(f"Количество доступных офферов: {len(result.available_offers)}")
            logger.info(f"Общее количество: {result.total_count}")
        else:
            logger.warning("В ответе нет поля available_offers")
            logger.info(f"Доступные поля: {dir(result)}")
        
        # Преобразуем офферы в формат для шаблона
        offers = []
        if hasattr(result, 'available_offers') and result.available_offers:
            logger.info("Обработка офферов из микросервиса...")
            for i, offer in enumerate(result.available_offers):
                logger.info(f"Обработка оффера {i+1}: {offer}")
                try:
                    offer_data = {
                        "id": str(offer.id) if hasattr(offer, 'id') else f"offer_{i}",
                        "external_id": getattr(offer, 'external_id', f"EXT{i+1:03d}"),
                        "name": getattr(offer, 'name', f"Товар {i+1}"),
                        "price": {
                            "amount": str(getattr(offer, 'price', 0.0)), 
                            "currency": getattr(offer, 'currency', 'PLN')
                        },
                        "stock": getattr(offer, 'stock', 0),
                        "category": getattr(offer, 'category', 'Неизвестно'),
                        "images": getattr(offer, 'images', []),
                        "created_at": getattr(offer, 'created_at', None),
                        "updated_at": None,
                        "status": getattr(offer, 'status', 'active')
                    }
                    offers.append(offer_data)
                    logger.info(f"Оффер {i+1} обработан: {offer_data}")
                except Exception as offer_error:
                    logger.error(f"Ошибка при обработке оффера {i+1}: {offer_error}")
                    # Добавляем fallback данные для этого оффера
                    offers.append({
                        "id": f"error_offer_{i}",
                        "external_id": f"ERROR_{i}",
                        "name": f"Ошибка загрузки товара {i+1}",
                        "price": {"amount": "0.00", "currency": "PLN"},
                        "stock": 0,
                        "category": "Ошибка",
                        "images": [],
                        "created_at": None,
                        "updated_at": None,
                        "status": "error"
                    })
        else:
            logger.warning("Нет доступных офферов в ответе")
        
        total_count = getattr(result, 'total_count', len(offers))
        logger.info(f"=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ===")
        logger.info(f"Сформировано офферов: {len(offers)}")
        logger.info(f"Общее количество: {total_count}")
        logger.info(f"Офферы: {offers}")
        
    except Exception as e:
        logger.error(f"=== ОШИБКА ПРИ ПОЛУЧЕНИИ ОФФЕРОВ ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        # В случае ошибки используем mock данные
        logger.info("Использование mock данных как fallback")
        offers = [
            {
                "id": "1",
                "external_id": "EXT001",
                "name": "Тестовый товар 1 (Mock)",
                "price": {"amount": "100.00", "currency": "PLN"},
                "stock": 50,
                "category": "Электроника",
                "images": ["https://via.placeholder.com/150x150?text=Product+1"],
                "created_at": "2024-12-19T10:00:00Z",
                "updated_at": "2024-12-19T10:00:00Z",
                "status": "active"
            },
            {
                "id": "2", 
                "external_id": "EXT002",
                "name": "Тестовый товар 2 (Mock)",
                "price": {"amount": "250.00", "currency": "PLN"},
                "stock": 25,
                "category": "Одежда",
                "images": ["https://via.placeholder.com/150x150?text=Product+2"],
                "created_at": "2024-12-19T10:00:00Z",
                "updated_at": "2024-12-19T10:00:00Z",
                "status": "active"
            },
            {
                "id": "3",
                "external_id": "EXT003", 
                "name": "Тестовый товар 3 (Mock)",
                "price": {"amount": "75.50", "currency": "PLN"},
                "stock": 100,
                "category": "Книги",
                "images": ["https://via.placeholder.com/150x150?text=Product+3"],
                "created_at": "2024-12-19T10:00:00Z",
                "updated_at": "2024-12-19T10:00:00Z",
                "status": "active"
            }
        ]
        total_count = len(offers)
        logger.info(f"Mock данные подготовлены: {len(offers)} офферов")
    
    logger.info("=== ПОДГОТОВКА ШАБЛОНА ===")
    logger.info(f"Передача в шаблон: offers={len(offers)}, total_count={total_count}")
    
    return templates.TemplateResponse(
        "offer_transfer/blocks/offers_list.html",
        {
            "request": request,
            "offers": offers,
            "total_count": total_count,
            "user": current_user  # Передаем пользователя в шаблон
        }
    )

@router.get("/health")
async def health_check():
    """
    Проверка здоровья системы
    """
    logger.info("=== ПРОВЕРКА ЗДОРОВЬЯ СИСТЕМЫ ===")
    logger.info("Система работает корректно")
    return {"status": "healthy", "service": "offer-transfer-frontend"}

@router.get("/test-all-methods")
async def test_all_microservice_methods(request: Request):
    """
    Тестирование ВСЕХ методов ВСЕХ эндпоинтов микросервиса для диагностики
    """
    logger.info("=== ТЕСТИРОВАНИЕ ВСЕХ МЕТОДОВ ВСЕХ ЭНДПОИНТОВ МИКРОСЕРВИСА ===")
    
    results = {}
    shared_data = {}  # Данные для переиспользования между методами
    
    try:
        # Создаем фабрику
        logger.info("Создание фабрики микросервиса...")
        factory = get_microservice_client()
        logger.info("Фабрика создана успешно")
        
        # ===============================================
        # 1. ТЕСТИРОВАНИЕ TOKENS ENDPOINT (только для получения данных)
        # ===============================================
        tokens_client = factory.create_tokens_client()
        
        # get_user_tokens - базовый метод для получения токенов
        tokens_results = {}
        try:
            tokens_response = tokens_client.get_user_tokens(settings.PROJECT_NAME, active_only=True)
            
            # Сохраняем токены для использования в других методах
            if hasattr(tokens_response, 'items') and tokens_response.items:
                shared_data['tokens'] = tokens_response.items
                shared_data['token_ids'] = [str(token.get('id', token.get('token_id', 'unknown'))) for token in tokens_response.items]
            
            tokens_results['get_user_tokens'] = {"status": "success"}
        except Exception as e:
            tokens_results['get_user_tokens'] = {"status": "error", "error": str(e)}
        
        results['tokens'] = tokens_results
        
        # ===============================================
        # 2. ТЕСТИРОВАНИЕ MARKETS ENDPOINT (только для получения данных)
        # ===============================================
        markets_client = factory.create_markets_client()
        
        # get_available_markets - доступные рынки
        markets_results = {}
        try:
            markets_response = await markets_client.get_available_markets()
            
            # Сохраняем рынки для использования в других методах
            if hasattr(markets_response, 'markets') and markets_response.markets:
                shared_data['markets'] = [market.dict() for market in markets_response.markets]
                shared_data['market_codes'] = [market.code for market in markets_response.markets]
            
            markets_results['get_available_markets'] = {"status": "success"}
        except Exception as e:
            markets_results['get_available_markets'] = {"status": "error", "error": str(e)}
        
        results['markets'] = markets_results
        
        # ===============================================
        # 3. MONITORING ENDPOINT - ПРОПУСК (не работает)
        # ===============================================
        # Пропускаем monitoring endpoint, так как все методы возвращают 404
        results['monitoring'] = {'status': 'skipped', 'reason': 'All methods return 404'}
        
        # ===============================================
        # 3. ТЕСТИРОВАНИЕ TEMPLATES ENDPOINT (только для получения данных)
        # ===============================================
        templates_client = factory.create_templates_client()
        
        # get_user_templates - шаблоны пользователя
        templates_results = {}
        try:
            templates_list = await templates_client.get_user_templates()
            
            # Сохраняем шаблоны
            if hasattr(templates_list, '__iter__'):
                shared_data['templates'] = list(templates_list)
            
            templates_results['get_user_templates'] = {"status": "success"}
        except Exception as e:
            templates_results['get_user_templates'] = {"status": "error", "error": str(e)}
        
        results['templates'] = templates_results
        
        # ===============================================
        # 4. ТЕСТИРОВАНИЕ OFFERS ENDPOINT (только для получения данных)
        # ===============================================
        offers_client = factory.create_offers_client()
        
        # get_offers_by_external_id - получение офферов по external_id
        offers_results = {}
        if shared_data.get('token_ids'):
            try:
                token_ids = [UUID(token_id) for token_id in shared_data['token_ids'][:2]]  # Берем первые 2 токена
                external_id = "TEST_001"  # Тестовый external_id
                offers_response = offers_client.get_offers_by_external_id(token_ids, external_id)
                
                # Сохраняем офферы для использования в других методах
                if hasattr(offers_response, 'offers') and offers_response.offers:
                    shared_data['offers'] = offers_response.offers
                    shared_data['offer_ids'] = [str(offer.get('id', offer.get('offer_id', 'unknown'))) for offer in offers_response.offers]
                
                offers_results['get_offers_by_external_id'] = {"status": "success"}
            except Exception as e:
                offers_results['get_offers_by_external_id'] = {"status": "error", "error": str(e)}
        else:
            offers_results['get_offers_by_external_id'] = {"status": "skipped", "reason": "No tokens available"}
        
        results['offers'] = offers_results
        
        # ===============================================
        # 5. ТЕСТИРОВАНИЕ OFFER_TRANSFER ENDPOINT (БЕЗ ФАКТИЧЕСКОГО ПЕРЕНОСА)
        # ===============================================
        offer_transfer_client = factory.create_offer_transfer_client()
        
        # compare_offers - сравнение офферов (МЕНЯЕМ МЕСТАМИ АККАУНТЫ)
        offer_transfer_results = {}
        if shared_data.get('token_ids') and len(shared_data['token_ids']) >= 2:
            try:
                # Меняем местами: первый токен становится целевым, второй - исходным
                target_token_id = shared_data['token_ids'][0]  # Первый токен -> целевой
                source_token_id = shared_data['token_ids'][1]  # Второй токен -> исходный
                
                logger.info(f"=== ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ compare_offers ===")
                logger.info(f"source_token_id: {source_token_id}")
                logger.info(f"target_token_id: {target_token_id}")
                
                compare_response = await offer_transfer_client.compare_offers(
                    source_token_id=source_token_id,
                    target_token_id=target_token_id
                )
                
                logger.info(f"Тип ответа: {type(compare_response)}")
                logger.info(f"Полный ответ: {compare_response}")
                
                # Детальное логирование структуры available_offers
                if hasattr(compare_response, 'available_offers') and compare_response.available_offers:
                    logger.info(f"Количество офферов: {len(compare_response.available_offers)}")
                    
                    # Логируем первый оффер полностью
                    if len(compare_response.available_offers) > 0:
                        first_offer = compare_response.available_offers[0]
                        logger.info(f"=== ПЕРВЫЙ ОФФЕР - ПОЛНАЯ СТРУКТУРА ===")
                        logger.info(f"Тип первого оффера: {type(first_offer)}")
                        logger.info(f"Первый оффер полностью: {first_offer}")
                        
                        # Если это словарь, логируем все ключи
                        if isinstance(first_offer, dict):
                            logger.info(f"Ключи первого оффера: {list(first_offer.keys())}")
                            for key, value in first_offer.items():
                                logger.info(f"  {key}: {value} (тип: {type(value)})")
                        # Если это объект, логируем атрибуты
                        elif hasattr(first_offer, '__dict__'):
                            logger.info(f"Атрибуты первого оффера: {dir(first_offer)}")
                            logger.info(f"Словарь первого оффера: {first_offer.__dict__}")
                
                # Сохраняем данные для использования в других методах
                if hasattr(compare_response, 'available_offers') and compare_response.available_offers:
                    shared_data['compare_offers'] = compare_response
                    shared_data['available_offers'] = compare_response.available_offers
                
                offer_transfer_results['compare_offers'] = {"status": "success"}
            except Exception as e:
                logger.error(f"Ошибка compare_offers: {e}")
                logger.error(f"Тип ошибки: {type(e)}")
                if hasattr(e, '__dict__'):
                    logger.error(f"Детали ошибки: {e.__dict__}")
                offer_transfer_results['compare_offers'] = {"status": "error", "error": str(e)}
        else:
            offer_transfer_results['compare_offers'] = {"status": "skipped", "reason": "Insufficient tokens"}
        
        results['offer_transfer'] = offer_transfer_results
        
        # ===============================================
        # 6. ТЕСТИРОВАНИЕ ORDERS ENDPOINT (только для получения данных)
        # ===============================================
        orders_client = factory.create_orders_client()
        
        # get_orders - список заказов (основной метод)
        orders_results = {}
        if shared_data.get('token_ids'):
            try:
                token_id = UUID(shared_data['token_ids'][0])
                orders_response = orders_client.get_orders(token_id, limit=10, offset=0)
                orders_results['get_orders'] = {"status": "success"}
            except Exception as e:
                orders_results['get_orders'] = {"status": "error", "error": str(e)}
        else:
            orders_results['get_orders'] = {"status": "skipped", "reason": "No tokens available"}
        
        results['orders'] = orders_results
        
        # ===============================================
        # 7. ТЕСТИРОВАНИЕ SYNC ENDPOINT (только для получения данных)
        # ===============================================
        sync_client = factory.create_sync_client()
        
        # get_sync_history - история синхронизаций
        sync_results = {}
        try:
            history_response = sync_client.get_sync_history(page=1, per_page=5)
            sync_results['get_sync_history'] = {"status": "success"}
        except Exception as e:
            sync_results['get_sync_history'] = {"status": "error", "error": str(e)}
        
        results['sync'] = sync_results
        
        # ===============================================
        # ИТОГИ ТЕСТИРОВАНИЯ
        # ===============================================
        logger.info("=== ИТОГИ ТЕСТИРОВАНИЯ ВСЕХ МЕТОДОВ ===")
        logger.info(f"Общие результаты: {results}")
        logger.info(f"Общие данные: {shared_data}")
        
        return {
            "status": "completed",
            "results": results,
            "shared_data": shared_data,
            "message": "Тестирование всех методов всех эндпоинтов завершено"
        }
        
    except Exception as e:
        logger.error(f"=== КРИТИЧЕСКАЯ ОШИБКА ТЕСТИРОВАНИЯ ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        return {
            "status": "failed",
            "error": str(e),
            "results": results,
            "shared_data": shared_data
        }


# ===============================================
# JWT и интеграция с микросервисом
# ===============================================

@router.post("/auth/token")
async def generate_jwt_token(current_user: CurrentUser = CurrentUserDep) -> Dict[str, str]:
    """
    Генерация JWT токена для микросервиса
    """
    try:
        # Создаем payload для JWT
        payload = {
            "user_id": settings.PROJECT_NAME,  # Используем PROJECT_NAME как user_id
            "real_user_id": current_user.user_id,  # Сохраняем реальный ID пользователя
            "exp": datetime.utcnow() + timedelta(hours=24),  # Токен действует 24 часа
            "iat": datetime.utcnow(),
            "iss": "baselinker_to_wix"
        }
        
        # Генерируем JWT токен
        jwt_token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        
        return {
            "access_token": jwt_token,
            "token_type": "bearer",
            "expires_in": 86400  # 24 часа в секундах
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка генерации JWT токена: {str(e)}"
        )


def get_microservice_client():
    """
    Получить клиента микросервиса с актуальным JWT токеном
    """
    try:
        logger.info("=== СОЗДАНИЕ JWT ТОКЕНА ДЛЯ МИКРОСЕРВИСА ===")
        
        # Создаем JWT токен для микросервиса
        payload = {
            "user_id": settings.PROJECT_NAME,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
            "iss": "baselinker_to_wix"
        }
        
        logger.info(f"JWT payload: {payload}")
        logger.info(f"SECRET_KEY доступен: {'Да' if settings.SECRET_KEY else 'Нет'}")
        logger.info(f"SECRET_KEY длина: {len(settings.SECRET_KEY) if settings.SECRET_KEY else 0}")
        
        jwt_token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        logger.info(f"JWT токен создан: {jwt_token[:20]}...")
        logger.info(f"Длина JWT токена: {len(jwt_token)}")
        
        # Создаем фабрику клиентов
        logger.info(f"Создание фабрики с параметрами:")
        logger.info(f"  - JWT токен: {jwt_token[:20]}...")
        logger.info(f"  - URL: {settings.MICRO_SERVICE_URL}")
        logger.info(f"  - URL доступен: {'Да' if settings.MICRO_SERVICE_URL else 'Нет'}")
        
        factory = create_factory(jwt_token, settings.MICRO_SERVICE_URL)
        logger.info("=== ФАБРИКА КЛИЕНТОВ СОЗДАНА УСПЕШНО ===")
        logger.info(f"Тип фабрики: {type(factory)}")
        logger.info(f"Доступные методы: {[method for method in dir(factory) if not method.startswith('_')]}")
        
        return factory
        
    except Exception as e:
        logger.error(f"=== ОШИБКА СОЗДАНИЯ КЛИЕНТА МИКРОСЕРВИСА ===")
        logger.error(f"Тип ошибки: {type(e)}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error("Полный traceback:", exc_info=True)
        
        # Дополнительная диагностика
        logger.error(f"Проверка настроек:")
        logger.error(f"  - PROJECT_NAME: {getattr(settings, 'PROJECT_NAME', 'Не задан')}")
        logger.error(f"  - SECRET_KEY: {'Доступен' if getattr(settings, 'SECRET_KEY', None) else 'Не доступен'}")
        logger.error(f"  - MICRO_SERVICE_URL: {getattr(settings, 'MICRO_SERVICE_URL', 'Не задан')}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка создания клиента микросервиса: {str(e)}"
        )


# ===============================================
# API прокси эндпоинты
# ===============================================

@router.get("/api/accounts")
async def get_user_accounts(current_user: CurrentUser = CurrentUserDep) -> List[Dict[str, Any]]:
    """
    Получить аккаунты пользователя через микросервис
    """
    try:
        factory = get_microservice_client()
        client = factory.create_offer_transfer_client()
        
        # Получаем аккаунты через микросервис
        accounts = await client.get_user_accounts()
        
        return accounts
        
    except Exception as e:
        # В случае ошибки возвращаем mock данные
        return [
            {"id": "1", "name": "Аккаунт 1 (PL)", "country_code": "PL"},
            {"id": "2", "name": "Аккаунт 2 (CZ)", "country_code": "CZ"},
            {"id": "3", "name": "Аккаунт 3 (SK)", "country_code": "SK"}
        ]


@router.post("/api/compare-offers")
async def compare_offers_api(
    source_token_id: int,
    target_token_id: int,
    current_user: CurrentUser = CurrentUserDep
) -> Dict[str, Any]:
    """
    Сравнить офферы между аккаунтами через микросервис
    """
    try:
        factory = get_microservice_client()
        client = factory.create_offer_transfer_client()
        
        # Сравниваем офферы через микросервис
        result = await client.compare_offers(
            source_token_id=source_token_id,
            target_token_id=target_token_id
        )
        
        return {
            "source_account": result.source_account,
            "target_account": result.target_account,
            "offers": [offer.dict() for offer in result.available_offers],
            "total_count": result.total_count
        }
        
    except Exception as e:
        # В случае ошибки возвращаем mock данные
        return {
            "source_account": "Аккаунт 1 (PL)",
            "target_account": "Аккаунт 2 (CZ)",
            "offers": [
                {
                    "id": "1",
                    "external_id": "EXT001",
                    "name": "Тестовый товар 1",
                    "price": 29.99,
                    "currency": "PLN",
                    "stock": 50,
                    "category": "Электроника",
                    "images": ["https://via.placeholder.com/150x150?text=Product+1"],
                    "status": "active"
                }
            ],
            "total_count": 1
        }


@router.get("/api/markets")
async def get_available_markets(current_user: CurrentUser = CurrentUserDep) -> List[Dict[str, Any]]:
    """
    Получить доступные рынки через микросервис
    """
    try:
        factory = get_microservice_client()
        client = factory.create_markets_client()
        
        # Получаем рынки через микросервис
        markets_response = await client.get_available_markets()
        
        return [market.dict() for market in markets_response.markets]
        
    except Exception as e:
        # В случае ошибки возвращаем mock данные
        return [
            {"code": "PL", "name": "Польша", "currency": "PLN", "flag": "🇵🇱"},
            {"code": "CZ", "name": "Чехия", "currency": "CZK", "flag": "🇨🇿"},
            {"code": "SK", "name": "Словакия", "currency": "EUR", "flag": "🇸🇰"},
            {"code": "HU", "name": "Венгрия", "currency": "HUF", "flag": "🇭🇺"}
        ]


@router.get("/api/currency-rates")
async def get_currency_rates(current_user: CurrentUser = CurrentUserDep) -> Dict[str, Any]:
    """
    Получить курсы валют через микросервис
    """
    try:
        factory = get_microservice_client()
        client = factory.create_markets_client()
        
        # Получаем курсы валют через микросервис
        rates_response = await client.get_currency_rates()
        
        return {
            "rates": rates_response.rates,
            "base_currency": rates_response.base_currency,
            "last_updated": rates_response.last_updated.isoformat()
        }
        
    except Exception as e:
        # В случае ошибки возвращаем mock данные
        return {
            "rates": {
                "PLN": 1.0,
                "CZK": 5.8,
                "EUR": 0.23,
                "HUF": 85.0
            },
            "base_currency": "PLN",
            "last_updated": datetime.utcnow().isoformat()
        }


@router.get("/api/metrics")
async def get_transfer_metrics(current_user: CurrentUser = CurrentUserDep) -> Dict[str, Any]:
    """
    Получить метрики переноса через микросервис
    """
    try:
        factory = get_microservice_client()
        client = factory.create_monitoring_client()
        
        # Получаем метрики через микросервис
        metrics = await client.get_current_metrics()
        
        return {
            "active_sessions": metrics.active_sessions,
            "total_processed_offers": metrics.total_offers_processed,
            "success_rate": (metrics.successful_offers / max(metrics.total_offers_processed, 1)) * 100,
            "average_processing_time": metrics.avg_processing_time_ms / 1000,  # Конвертируем в секунды
            "market_distribution": [
                {"market": k, "count": v, "percentage": (v / max(sum(metrics.market_distribution.values()), 1)) * 100}
                for k, v in metrics.market_distribution.items()
            ],
            "top_errors": metrics.top_errors
        }
        
    except Exception as e:
        # В случае ошибки возвращаем mock данные
        return {
            "active_sessions": 3,
            "total_processed_offers": 1247,
            "success_rate": 87.5,
            "average_processing_time": 2.3,
            "market_distribution": [
                {"market": "PL", "count": 450, "percentage": 36.1},
                {"market": "CZ", "count": 320, "percentage": 25.7},
                {"market": "SK", "count": 280, "percentage": 22.5},
                {"market": "HU", "count": 197, "percentage": 15.8}
            ],
            "top_errors": [
                {"error": "Недостаточно остатков", "count": 45, "percentage": 12.3},
                {"error": "Неверная категория", "count": 32, "percentage": 8.7},
                {"error": "Ошибка API Allegro", "count": 28, "percentage": 7.6}
            ]
        }
