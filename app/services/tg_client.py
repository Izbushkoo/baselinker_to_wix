import os
import time
from typing import Optional, Dict, Any, List

import httpx

from app.utils.logging_config import logger
class TelegramManager:
    """
    Синхронный клиент для Telegram Bot API на httpx.
    Поддерживает отправку сообщений и автоматическую обработку 429 Too Many Requests.
    """

    def __init__(
        self,
        chat_id: Optional[int] = None,
        token_env_var: str = "NOTIFICATOR_BOT_TOKEN",
    ):
        token = os.getenv(token_env_var)
        if not token:
            raise RuntimeError(f"Environment variable {token_env_var} is not set")
        self.chat_id = chat_id
        self._client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=10.0,
        )

    def send_message(
        self,
        text: str,
        chat_id: Optional[int] = None,
        parse_mode: Optional[str] = "HTML",
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        max_retries: int = 5,
    ) -> Dict[str, Any]:
        """
        Send a text message to a chat, with handling of 429 errors.

        :param text: текст сообщения
        :param chat_id: приоритетный chat_id, иначе используется self.chat_id
        :param max_retries: сколько раз пытаться при 429
        """
        target = chat_id or self.chat_id
        if target is None:
            raise RuntimeError("chat_id is not specified")

        payload = {
            "chat_id": target,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
            "disable_notification": disable_notification,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        attempts = 0
        while True:
            try:
                r = self._client.post("/sendMessage", json=payload)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok", False):
                    raise RuntimeError(f"Telegram API error: {data.get('description')}")
                return data

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 and attempts < max_retries:
                    attempts += 1
                    # попытаться прочитать retry_after из тела или заголовков
                    retry_after = None
                    try:
                        body = exc.response.json()
                        logger.info(f"Retry after: {body}")
                        retry_after = body.get("parameters", {}).get("retry_after")

                    except Exception:
                        pass
                    if retry_after is None:
                        retry_after = exc.response.headers.get("Retry-After")
                    # приводим к int
                    try:
                        wait = int(retry_after)
                    except Exception:
                        wait = 1
                    time.sleep(wait + 1)
                    continue
                # иначе пробрасываем ошибку
                raise

    def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Получить список обновлений.
        """
        params: Dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        r = self._client.get("/getUpdates", params=params)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok", False):
            raise RuntimeError(f"getUpdates error: {data.get('description')}")
        return data["result"]

    def get_me(self) -> Dict[str, Any]:
        """Получить информацию о боте (в т.ч. его id)."""
        r = self._client.get("/getMe")
        r.raise_for_status()
        data = r.json()
        if not data.get("ok", False):
            raise RuntimeError(f"getMe error: {data.get('description')}")
        return data["result"]

    def get_chat_member(self, chat_id: int, user_id: int) -> Dict[str, Any]:
        """Запрос getChatMember для проверки статуса пользователя в чате."""
        r = self._client.get(
            "/getChatMember",
            params={"chat_id": chat_id, "user_id": user_id}
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok", False):
            raise RuntimeError(f"getChatMember error: {data.get('description')}")
        return data["result"]

    def discover_admin_groups(self) -> List[int]:
        """
        Автоматически находит группы/супергруппы, где бот админ.
        """
        updates = self.get_updates()
        me = self.get_me()
        bot_id = me["id"]
        found_groups = set()

        for upd in updates:
            msg = upd.get("message") or upd.get("my_chat_member")
            if not msg:
                continue

            chat = msg.get("chat")
            if not chat:
                continue

            if chat.get("type") not in ("group", "supergroup"):
                continue

            cid = chat["id"]
            try:
                member = self.get_chat_member(cid, bot_id)
                status = member.get("status")
                if status in ("administrator", "creator"):
                    found_groups.add(cid)
            except Exception:
                continue

        return list(found_groups)

