import logging
import hmac
import hashlib
import json
from typing import Dict, Any, Optional
from app.core.config import settings
import httpx
from httpx import AsyncClient
from urllib.parse import unquote_plus, parse_qsl
from datetime import datetime, timezone
from operator import itemgetter
logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        self.bot_token = settings.NOTIFICATOR_BOT_TOKEN
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.webhook_url = settings.TELEGRAM_WEBHOOK_URL
        self._client: Optional[AsyncClient] = None

    async def get_client(self) -> AsyncClient:
        """Получение или создание httpx клиента"""
        if self._client is None:
            self._client = AsyncClient(
                base_url=self.api_url,
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self._client

    async def close(self):
        """Закрытие клиента"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def set_webhook(self) -> bool:
        """Установка вебхука для бота"""
        try:
            client = await self.get_client()
            
            # Устанавливаем вебхук с дополнительными параметрами
            response = await client.post(
                "/setWebhook",
                json={
                    "url": self.webhook_url,
                    "allowed_updates": ["message", "callback_query"],
                    "drop_pending_updates": True
                }
            )
            result = response.json()
            
            if not result.get("ok", False):
                logger.error(f"Failed to set webhook: {result.get('description', 'Unknown error')}")
                return False
                
            logger.info(f"Webhook set successfully: {result}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting webhook: {str(e)}")
            return False

    def validate_init_data(self, init_data: str) -> bool:
        """
        Валидация initData от Telegram Web App
        """
        logger.info(f"Validating initData: {init_data}")
        
        try:
            parsed_data = dict(parse_qsl(init_data))
        except ValueError:
            # Init data is not a valid query string
            return False
        if "hash" not in parsed_data:
            # Hash is not present in init data
            return False
            
        hash_ = parsed_data.pop('hash')
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items(), key=itemgetter(0))
        )
        secret_key = hmac.new(
            key=b"WebAppData", msg=self.bot_token.encode(), digestmod=hashlib.sha256
        )
        calculated_hash = hmac.new(
            key=secret_key.digest(), msg=data_check_string.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        return calculated_hash == hash_

    async def send_message(self, chat_id: int, text: str, **kwargs) -> bool:
        """Отправка сообщения пользователю"""
        try:
            client = await self.get_client()
            
            # Добавляем timestamp к логам
            logger.info(f"Sending message to chat_id {chat_id} at {datetime.now(timezone.utc)}")
            
            # Подготавливаем данные для отправки
            message_data = {
                "chat_id": chat_id,
                "text": text,
                **kwargs
            }
            
            logger.info(f"Message data: {message_data}")
            
            # Отправляем сообщение
            response = await client.post(
                "/sendMessage",
                json=message_data
            )
            
            result = response.json()
            
            if not result.get("ok", False):
                error_msg = result.get("description", "Unknown error")
                logger.error(f"Failed to send message: {error_msg}")
                logger.error(f"Full response: {result}")
                return False
                
            logger.info(f"Message sent successfully: {result}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}", exc_info=True)
            return False

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> bool:
        """Ответ на callback query"""
        try:
            client = await self.get_client()
            response = await client.post(
                "/answerCallbackQuery",
                json={
                    "callback_query_id": callback_query_id,
                    "text": text,
                    "show_alert": show_alert
                }
            )
            result = response.json()
            return result.get("ok", False)
        except Exception as e:
            logger.error(f"Error answering callback query: {str(e)}")
            return False

# Создаем экземпляр сервиса
telegram_service = TelegramService() 