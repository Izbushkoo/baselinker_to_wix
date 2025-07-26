from typing import Optional
from app.core.config import settings


class BaseClient:

    def __init__(
        self,
        jwt_token: str,
        base_url: str = None,
        timeout: Optional[int] = 10
    ):
        """
        :param base_url: Базовый URL сервиса, например "https://example.com"
        :param jwt_token: JWT токен для аутентификации
        :param timeout: Таймаут запросов в секундах
        """
        if base_url:
            self.base_url = base_url.rstrip('/')
        else:
            self.base_url = settings.MICRO_SERVICE_URL.rstrip("/")
        self.headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Content-Type': 'application/json'
        }
        self.timeout = timeout