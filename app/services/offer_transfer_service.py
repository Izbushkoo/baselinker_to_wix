"""
 * @file: offer_transfer_service.py
 * @description: Основной сервис для системы переноса офферов Allegro
 * @dependencies: allegro_api_service, database models, schemas
 * @created: 2024-12-19
"""

from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import logging
from datetime import datetime, timedelta

from app.services.allegro.allegro_api_service import AllegroAPIService
from app.models.allegro_token import AllegroToken
from app.models.user import User
from app.schemas.offer_transfer import (
    OfferTransferSession,
    OfferTransferRequest,
    MarketPricingRule,
    TransferTemplate,
    TransferMetrics
)

logger = logging.getLogger(__name__)


class OfferTransferService:
    """Сервис для управления переносом офферов между аккаунтами Allegro"""
    
    def __init__(self, db: Session):
        self.db = db
        self.allegro_service = AllegroAPIService()
    
    async def get_user_accounts(self, user_id: int) -> List[Dict]:
        """Получить доступные аккаунты Allegro для пользователя"""
        try:
            # Получаем токены пользователя
            tokens = self.db.query(AllegroToken).filter(
                AllegroToken.user_id == user_id,
                AllegroToken.is_active == True
            ).all()
            
            accounts = []
            for token in tokens:
                # Получаем информацию об аккаунте через Allegro API
                account_info = await self.allegro_service.get_account_info(token.access_token)
                if account_info:
                    accounts.append({
                        "id": token.id,
                        "name": account_info.get("name", f"Аккаунт {token.id}"),
                        "email": account_info.get("email", ""),
                        "country_code": account_info.get("countryCode", "PL"),
                        "is_verified": account_info.get("verified", False)
                    })
            
            return accounts
            
        except Exception as e:
            logger.error(f"Ошибка при получении аккаунтов: {e}")
            return []
    
    async def get_source_offers(self, source_token_id: int, filters: Optional[Dict] = None) -> List[Dict]:
        """Получить список офферов из исходного аккаунта"""
        try:
            # Получаем токен
            token = self.db.query(AllegroToken).filter(AllegroToken.id == source_token_id).first()
            if not token:
                raise ValueError("Токен не найден")
            
            # Получаем офферы через Allegro API
            offers = await self.allegro_service.get_offers(
                token.access_token,
                limit=100,  # Можно сделать настраиваемым
                filters=filters
            )
            
            # Преобразуем в нужный формат
            formatted_offers = []
            for offer in offers:
                formatted_offers.append({
                    "id": offer.get("id"),
                    "external_id": offer.get("externalId"),
                    "name": offer.get("name"),
                    "price": offer.get("price", {}).get("amount"),
                    "currency": offer.get("price", {}).get("currency", "PLN"),
                    "stock": offer.get("stock", {}).get("available"),
                    "category": offer.get("category", {}).get("id"),
                    "images": [img.get("url") for img in offer.get("images", [])],
                    "status": offer.get("status"),
                    "created_at": offer.get("createdAt")
                })
            
            return formatted_offers
            
        except Exception as e:
            logger.error(f"Ошибка при получении офферов: {e}")
            return []
    
    async def validate_market_compatibility(self, source_country: str, target_markets: List[str]) -> Dict[str, bool]:
        """Проверить совместимость исходного рынка с целевыми"""
        # Простая логика проверки - можно расширить
        compatibility_map = {
            "PL": ["CZ", "SK", "HU"],  # Польша -> Чехия, Словакия, Венгрия
            "CZ": ["PL", "SK", "HU"],  # Чехия -> Польша, Словакия, Венгрия
            "SK": ["PL", "CZ", "HU"],  # Словакия -> Польша, Чехия, Венгрия
            "HU": ["PL", "CZ", "SK"]   # Венгрия -> Польша, Чехия, Словакия
        }
        
        source_markets = compatibility_map.get(source_country, [])
        return {market: market in source_markets for market in target_markets}
    
    async def calculate_prices(self, base_price: float, base_currency: str, 
                              target_currency: str, rule: MarketPricingRule) -> float:
        """Рассчитать цену для целевого рынка по правилу"""
        try:
            # Получаем курс валют (можно использовать внешний API)
            exchange_rate = await self._get_exchange_rate(base_currency, target_currency)
            
            # Применяем правило ценообразования
            if rule.type == "multiply":
                return base_price * exchange_rate * rule.value
            elif rule.type == "add":
                return base_price * exchange_rate + rule.value
            elif rule.type == "convert_with_markup":
                markup = 1 + (rule.value / 100)
                return base_price * exchange_rate * markup
            elif rule.type == "custom":
                # Кастомная формула (например, "price * 1.2 + 5")
                # Здесь можно добавить безопасный eval или парсер формул
                return base_price * exchange_rate * 1.2 + 5
            else:
                return base_price * exchange_rate
                
        except Exception as e:
            logger.error(f"Ошибка при расчете цены: {e}")
            return base_price
    
    async def _get_exchange_rate(self, from_currency: str, to_currency: str) -> float:
        """Получить курс валют (заглушка - в реальности использовать API курсов валют)"""
        # Простые курсы для демонстрации
        rates = {
            ("PLN", "CZK"): 5.8,
            ("PLN", "EUR"): 0.23,
            ("PLN", "HUF"): 85.0,
            ("CZK", "PLN"): 0.17,
            ("CZK", "EUR"): 0.04,
            ("CZK", "HUF"): 14.7,
            ("EUR", "PLN"): 4.35,
            ("EUR", "CZK"): 25.5,
            ("EUR", "HUF"): 375.0,
            ("HUF", "PLN"): 0.012,
            ("HUF", "CZK"): 0.068,
            ("HUF", "EUR"): 0.0027
        }
        
        # Обратные курсы
        reverse_rates = {(to, from_): 1/rate for (from_, to), rate in rates.items()}
        all_rates = {**rates, **reverse_rates}
        
        return all_rates.get((from_currency, to_currency), 1.0)
    
    async def create_transfer_session(self, user_id: int, request: OfferTransferRequest) -> str:
        """Создать сессию переноса офферов"""
        try:
            session_id = f"transfer_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Здесь можно сохранить сессию в базу данных
            # Пока возвращаем ID сессии
            logger.info(f"Создана сессия переноса: {session_id}")
            return session_id
            
        except Exception as e:
            logger.error(f"Ошибка при создании сессии: {e}")
            raise
    
    async def start_transfer_process(self, session_id: str, offers: List[Dict], 
                                   markets: List[str], pricing_rules: Dict[str, MarketPricingRule]) -> Dict:
        """Запустить процесс переноса офферов"""
        try:
            # Создаем задачу в Celery для асинхронного выполнения
            from app.celery_app import celery_app
            
            task = celery_app.send_task(
                'app.services.offer_transfer_tasks.process_offers_transfer',
                args=[session_id, offers, markets, pricing_rules]
            )
            
            return {
                "session_id": session_id,
                "task_id": task.id,
                "status": "started",
                "total_offers": len(offers),
                "target_markets": markets
            }
            
        except Exception as e:
            logger.error(f"Ошибка при запуске переноса: {e}")
            raise
    
    async def get_transfer_status(self, session_id: str) -> Dict:
        """Получить статус переноса офферов"""
        try:
            # Здесь должна быть логика получения статуса из базы или Redis
            # Пока возвращаем mock-данные
            return {
                "session_id": session_id,
                "status": "in_progress",
                "progress": 65,
                "processed": 13,
                "total": 20,
                "successful": 11,
                "failed": 2,
                "current_offer": "iPhone 15 Pro 256GB",
                "estimated_time": "2 мин"
            }
            
        except Exception as e:
            logger.error(f"Ошибка при получении статуса: {e}")
            return {}
    
    async def save_template(self, user_id: int, template: TransferTemplate) -> bool:
        """Сохранить шаблон переноса"""
        try:
            # Здесь должна быть логика сохранения в базу данных
            logger.info(f"Сохранен шаблон для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении шаблона: {e}")
            return False
    
    async def get_user_templates(self, user_id: int) -> List[TransferTemplate]:
        """Получить шаблоны пользователя"""
        try:
            # Здесь должна быть логика получения из базы данных
            # Пока возвращаем mock-данные
            return [
                TransferTemplate(
                    id=1,
                    name="Стандартный перенос",
                    description="Базовые настройки для переноса офферов",
                    markets=["PL", "CZ", "SK"],
                    pricing_rules={
                        "PL": MarketPricingRule(type="multiply", value=1.0),
                        "CZ": MarketPricingRule(type="convert_with_markup", value=15),
                        "SK": MarketPricingRule(type="convert_with_markup", value=12)
                    }
                )
            ]
            
        except Exception as e:
            logger.error(f"Ошибка при получении шаблонов: {e}")
            return []
    
    async def get_transfer_metrics(self, user_id: int, days: int = 30) -> TransferMetrics:
        """Получить метрики переноса офферов"""
        try:
            # Здесь должна быть логика получения из базы данных
            # Пока возвращаем mock-данные
            return TransferMetrics(
                active_sessions=3,
                total_processed_offers=1247,
                success_rate=87.5,
                average_processing_time=2.3,
                market_distribution=[
                    {"market": "PL", "count": 450, "percentage": 36.1},
                    {"market": "CZ", "count": 320, "percentage": 25.7},
                    {"market": "SK", "count": 280, "percentage": 22.5},
                    {"market": "HU", "count": 197, "percentage": 15.8}
                ],
                top_errors=[
                    {"error": "Недостаточно остатков", "count": 45, "percentage": 12.3},
                    {"error": "Неверная категория", "count": 32, "percentage": 8.7},
                    {"error": "Ошибка API Allegro", "count": 28, "percentage": 7.6}
                ]
            )
            
        except Exception as e:
            logger.error(f"Ошибка при получении метрик: {e}")
            return TransferMetrics()
