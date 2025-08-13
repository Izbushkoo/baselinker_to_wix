import os
import time
import random
from typing import Optional, Dict, Any, List
import logging
import httpx


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
    ) -> Optional[Dict[str, Any]]:
        """
        Send a text message to a chat, with enhanced handling of 429 errors.

        :param text: текст сообщения
        :param chat_id: приоритетный chat_id, иначе используется self.chat_id
        :param max_retries: сколько раз пытаться при 429
        :return: Dict с данными ответа при успехе, None при полном провале
        """
        logger = logging.getLogger("telegram.client")
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
        base_delay = 1  # Базовая задержка для экспоненциального backoff
        
        while attempts <= max_retries:
            try:
                if attempts > 0:
                    logger.info(f"Telegram send attempt {attempts + 1}/{max_retries + 1} for chat {target}")
                    
                r = self._client.post("/sendMessage", json=payload)
                r.raise_for_status()
                data = r.json()
                
                if not data.get("ok", False):
                    error_desc = data.get('description', 'Unknown error')
                    logger.error(f"Telegram API error: {error_desc}")
                    raise RuntimeError(f"Telegram API error: {error_desc}")
                    
                if attempts > 0:
                    logger.info(f"Telegram message sent successfully after {attempts} retries to chat {target}")
                
                return data

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                attempts += 1
                
                if status == 400:
                    logger.error(f'Telegram 400 error: {exc.response.text}')
                    # 400 ошибки не retry-able
                    return None
                    
                elif status == 429:
                    if attempts > max_retries:
                        logger.error(f"Telegram 429 error: max retries ({max_retries}) exceeded for chat {target}")
                        return None
                        
                    # Получаем retry_after из ответа
                    retry_after = None
                    try:
                        body = exc.response.json()
                        retry_after = body.get("parameters", {}).get("retry_after")
                        logger.info(f"Telegram 429 error: retry_after={retry_after}, attempt {attempts}/{max_retries + 1}")
                    except Exception:
                        pass
                        
                    if retry_after is None:
                        retry_after = exc.response.headers.get("Retry-After")
                        
                    # Определяем время ожидания
                    if retry_after:
                        try:
                            server_wait = int(retry_after)
                        except Exception:
                            server_wait = base_delay
                    else:
                        # Экспоненциальный backoff если сервер не указал время
                        server_wait = base_delay * (2 ** (attempts - 1))
                    
                    # Добавляем jitter для предотвращения thundering herd
                    jitter = random.uniform(0.1, 0.5)
                    total_wait = server_wait + jitter
                    
                    logger.info(f"Telegram rate limited, waiting {total_wait:.1f}s before retry {attempts}")
                    time.sleep(total_wait)
                    continue
                else:
                    logger.error(f"Telegram HTTP error {status}: {exc.response.text}")
                    if attempts > max_retries:
                        return None
                    
                    # Для других HTTP ошибок делаем экспоненциальный backoff
                    wait_time = base_delay * (2 ** (attempts - 1)) + random.uniform(0.1, 0.5)
                    logger.info(f"Waiting {wait_time:.1f}s before retry {attempts} due to HTTP {status}")
                    time.sleep(wait_time)
                    continue
                    
            except Exception as exc:
                attempts += 1
                logger.error(f"Telegram unexpected error: {exc}")
                
                if attempts > max_retries:
                    logger.error(f"Telegram send failed after {max_retries} retries: {exc}")
                    return None
                
                # Экспоненциальный backoff для неожиданных ошибок
                wait_time = base_delay * (2 ** (attempts - 1)) + random.uniform(0.1, 0.5)
                logger.info(f"Waiting {wait_time:.1f}s before retry {attempts} due to unexpected error")
                time.sleep(wait_time)
                continue
        
        logger.error(f"Telegram send failed: maximum attempts exceeded")
        return None

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

    def delete_webhook(self) -> bool:
        """Удаляет webhook для использования polling."""
        try:
            r = self._client.post("/deleteWebhook")
            r.raise_for_status()
            data = r.json()
            return data.get("ok", False)
        except Exception as e:
            print(f"Ошибка удаления webhook: {e}")
            return False

    def set_webhook(self, webhook_url: str) -> bool:
        """Устанавливает webhook."""
        try:
            r = self._client.post("/setWebhook", json={
                "url": webhook_url,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": True
            })
            r.raise_for_status()
            data = r.json()
            return data.get("ok", False)
        except Exception as e:
            print(f"Ошибка установки webhook: {e}")
            return False

    def discover_admin_groups_live(self, timeout_seconds: int = 30) -> List[int]:
        """
        Ждет новые сообщения в группах и определяет где бот админ.
        Использует long polling для получения новых обновлений.
        
        :param timeout_seconds: сколько секунд ждать новые сообщения
        """
        me = self.get_me()
        bot_id = me["id"]
        found_groups = set()
        
        print(f"Запуск live-мониторинга на {timeout_seconds} секунд...")
        print("Отправьте сообщение в группу где бот является админом!")
        
        try:
            # Сначала получаем текущие обновления и получаем последний offset
            current_updates = self.get_updates(limit=1)
            offset = 0
            if current_updates:
                offset = current_updates[-1]["update_id"] + 1
                print(f"Начинаем мониторинг с offset: {offset}")
            
            # Запускаем long polling
            updates = self.get_updates(offset=offset, timeout=timeout_seconds, limit=100)
            
            if not updates:
                print("За время ожидания новых сообщений не поступило")
                return []
                
            print(f"Получено {len(updates)} новых обновлений!")
            
            # Анализируем обновления
            for upd in updates:
                print(f"Update ID: {upd.get('update_id')}")
                
                # Проверяем разные типы обновлений
                msg = None
                update_type = None
                if 'message' in upd:
                    msg = upd['message']
                    update_type = "message"
                elif 'my_chat_member' in upd:
                    msg = upd['my_chat_member']
                    update_type = "my_chat_member"
                elif 'channel_post' in upd:
                    msg = upd['channel_post']
                    update_type = "channel_post"
                    
                if not msg:
                    print(f"  Неизвестный тип: {list(upd.keys())}")
                    continue

                chat = msg.get("chat")
                if not chat:
                    continue
                    
                chat_type = chat.get("type")
                chat_title = chat.get("title", chat.get("first_name", "N/A"))
                chat_id = chat.get("id")
                
                print(f"  {update_type}: {chat_type} '{chat_title}' ({chat_id})")

                if chat_type in ("group", "supergroup"):
                    found_groups.add((chat_id, chat_title))
                    
            # Проверяем статус бота в найденных группах
            admin_groups = []
            print(f"\nПроверка статуса в {len(found_groups)} группах:")
            
            for chat_id, title in found_groups:
                try:
                    member = self.get_chat_member(chat_id, bot_id)
                    status = member.get("status")
                    if status in ("administrator", "creator"):
                        admin_groups.append(chat_id)
                        print(f"✓ {title} ({chat_id}): {status}")
                    else:
                        print(f"- {title} ({chat_id}): {status}")
                except Exception as e:
                    print(f"✗ {title} ({chat_id}): {e}")
                    
            return admin_groups
                    
        except Exception as e:
            print(f"Ошибка live-мониторинга: {e}")
            return []

    def discover_admin_groups(self, get_all_history: bool = True) -> List[int]:
        """
        Автоматически находит группы/супергруппы, где бот админ.
        
        :param get_all_history: если True, пытается получить всю историю обновлений
        """
        me = self.get_me()
        bot_id = me["id"]
        found_groups = set()
        all_updates = []

        if get_all_history:
            print("Получение истории обновлений...")
            # Получаем без offset (может вернуть последние необработанные)
            try:
                updates = self.get_updates(limit=100, timeout=0)
                all_updates.extend(updates)
                print(f"Получено {len(updates)} обновлений")
                
                # Если есть обновления, пытаемся получить больше
                if updates and len(updates) == 100:
                    last_update_id = max(upd["update_id"] for upd in updates)
                    more_updates = self.get_updates(offset=last_update_id + 1, limit=100)
                    all_updates.extend(more_updates)
                    print(f"Получено еще {len(more_updates)} обновлений")
                
            except Exception as e:
                print(f"Ошибка получения истории: {e}")
        else:
            all_updates = self.get_updates()

        print(f"Анализ {len(all_updates)} обновлений...")
        
        # Отладка: покажем первые несколько обновлений
        if all_updates:
            print(f"\nПример обновлений (первые 3):")
            for i, upd in enumerate(all_updates[:3]):
                print(f"  {i+1}. Update ID: {upd.get('update_id')}")
                if 'message' in upd:
                    msg = upd['message']
                    chat = msg.get('chat', {})
                    print(f"     Message from: {chat.get('type', 'unknown')} '{chat.get('title', chat.get('first_name', 'N/A'))}'")
                elif 'my_chat_member' in upd:
                    member_upd = upd['my_chat_member']
                    chat = member_upd.get('chat', {})
                    print(f"     Chat member update: {chat.get('type', 'unknown')} '{chat.get('title', 'N/A')}'")
                else:
                    print(f"     Type: {list(upd.keys())}")
        
        group_candidates = set()
        private_chats = 0
        channels = 0
        
        for upd in all_updates:
            # Проверяем разные типы обновлений
            msg = None
            if 'message' in upd:
                msg = upd['message']
            elif 'my_chat_member' in upd:
                msg = upd['my_chat_member']
            elif 'channel_post' in upd:
                msg = upd['channel_post']
                
            if not msg:
                continue

            chat = msg.get("chat")
            if not chat:
                continue

            chat_type = chat.get("type")
            if chat_type == "private":
                private_chats += 1
                continue
            elif chat_type == "channel":
                channels += 1
                continue
            elif chat_type in ("group", "supergroup"):
                cid = chat["id"]
                chat_title = chat.get("title", f"Группа {cid}")
                group_candidates.add((cid, chat_title))
                print(f"  Найдена группа: {chat_title} ({cid}) - тип: {chat_type}")
        
        print(f"\nСтатистика обновлений:")
        print(f"  Приватные чаты: {private_chats}")
        print(f"  Каналы: {channels}")
        print(f"  Группы/супергруппы: {len(group_candidates)}")
        
        found_groups = group_candidates

        # Теперь проверяем статус бота в найденных группах
        admin_groups = []
        print(f"\nПроверка статуса бота в {len(found_groups)} найденных группах:")
        
        for cid, title in found_groups:
            try:
                member = self.get_chat_member(cid, bot_id)
                status = member.get("status")
                if status in ("administrator", "creator"):
                    admin_groups.append(cid)
                    print(f"✓ {title} ({cid}): {status}")
                else:
                    print(f"- {title} ({cid}): {status}")
            except Exception as e:
                print(f"✗ {title} ({cid}): ошибка - {e}")
                continue

        return admin_groups


if __name__ == "__main__":
    # Поиск всех групп где бот является администратором
    try:
        import os
        # Надо добавить в environ токен прежде чем запускать
        print("Создание Telegram Manager...")
        tg_manager = TelegramManager()
        
        print("Получение информации о боте...")
        bot_info = tg_manager.get_me()
        print(f"Бот: @{bot_info.get('username', 'неизвестно')} (ID: {bot_info['id']})")
        
        print("Удаление webhook для использования polling...")
        if tg_manager.delete_webhook():
            print("✓ Webhook удален успешно")
        else:
            print("⚠ Не удалось удалить webhook, продолжаем...")
        
        print("Поиск групп где бот является администратором...")
        admin_groups = tg_manager.discover_admin_groups()
        
        if admin_groups:
            print(f"\nНайдено {len(admin_groups)} групп:")
            for i, group_id in enumerate(admin_groups, 1):
                print(f"  {i}. Группа ID: {group_id}")
        else:
            print("\nГруппы, где бот является администратором, не найдены.")
            print("Возможные причины:")
            print("- Бот не добавлен в группы как администратор")
            print("- В группах нет недавних сообщений или активности")
            print("- getUpdates возвращает пустой список (попробуйте отправить сообщение в группу)")
        
        print(f"\nВНИМАНИЕ: webhook был удален для выполнения поиска.")
        print("Если используется webhook в приложении, его нужно восстановить.")
            
    except RuntimeError as e:
        print(f"Ошибка конфигурации: {e}")
        print("Убедитесь что переменная окружения NOTIFICATOR_BOT_TOKEN установлена")
    except Exception as e:
        print(f"Произошла ошибка: {e}")

