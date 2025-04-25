import os
from typing import Optional, List, Dict, Any
import httpx



class TelegramManager:
    """
    Синхронный клиент для Telegram Bot API с отправкой сообщений и 
    автоматическим получением chat_id групп, где бот является админом.
    """

    def __init__(
        self,
        chat_id: Optional[int] = None,
        token_env_var: str = "NOTIFICATOR_BOT_TOKEN",
    ):
        token = os.getenv(token_env_var)
        if not token:
            raise RuntimeError(f"Environment variable {token_env_var} is not set")
        self.api = httpx.Client(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=10.0,
        )
        self.chat_id = chat_id

    def send_message(
        self,
        text: str,
        chat_id: Optional[int] = None,
        parse_mode: Optional[str] = "HTML",
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
    ) -> Dict[str, Any]:
        """
        Send a text message to a chat.
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

        r = self.api.post("/sendMessage", json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description')}")
        return data

    def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Получить список обновлений. offset берёт только обновления с update_id > offset.
        """
        params: Dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset:
            params["offset"] = offset
        r = self.api.get("/getUpdates", params=params)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates error: {data.get('description')}")
        return data["result"]

    def get_me(self) -> Dict[str, Any]:
        """
        Запрос getMe() для получения информации о самом боте (в т.ч. его id).
        """
        r = self.api.get("/getMe")
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getMe error: {data.get('description')}")
        return data["result"]

    def get_chat_member(self, chat_id: int, user_id: int) -> Dict[str, Any]:
        """
        Запрос getChatMember для проверки статуса пользователя в чате.
        """
        r = self.api.get("/getChatMember", params={"chat_id": chat_id, "user_id": user_id})
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getChatMember error: {data.get('description')}")
        return data["result"]

    def discover_admin_groups(self) -> List[int]:
        """
        Автоматически находит все группы/супергруппы, которые бот видел в обновлениях,
        и возвращает те chat_id, где он является администратором или создателем.
        """
        updates = self.get_updates()
        me = self.get_me()
        bot_id = me["id"]
        found_groups = set()

        for upd in updates:
            # Сообщения могут идти в полях message, my_chat_member, etc.
            msg = upd.get("message") or upd.get("my_chat_member")
            if not msg:
                continue

            chat = msg.get("chat")
            if not chat:
                continue

            # Интересуют только группы и супергруппы
            if chat.get("type") not in ("group", "supergroup"):
                continue

            cid = chat["id"]
            try:
                member = self.get_chat_member(cid, bot_id)
                status = member.get("status")
                if status in ("administrator", "creator"):
                    found_groups.add(cid)
            except Exception:
                # пропускаем чаты, где что-то пошло не так
                continue

        return list(found_groups)

