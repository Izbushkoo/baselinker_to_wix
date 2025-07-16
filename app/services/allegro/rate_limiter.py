"""
 * @file: rate_limiter.py
 * @description: Rate limiter для Allegro API (Token Bucket, 9000 req/min)
 * @dependencies: threading, time
 * @created: 2024-06-13
"""

import threading
import time
from typing import Optional

class AllegroRateLimiter:
    """
    Rate limiter для Allegro API (Token Bucket).
    Ограничивает количество запросов до 9000 в минуту на Client ID.
    """
    def __init__(self, requests_per_minute: int = 9000):
        self.capacity = requests_per_minute
        self.tokens = requests_per_minute
        self.refill_rate = requests_per_minute / 60  # токенов в секунду
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """
        Получить токен(ы) для запроса. Блокирует поток до появления токенов или до timeout.
        Возвращает True, если токены получены, иначе False.
        """
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
            if deadline and time.monotonic() > deadline:
                return False
            time.sleep(0.05)

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        refill_amount = elapsed * self.refill_rate
        if refill_amount >= 1:
            self.tokens = min(self.capacity, self.tokens + int(refill_amount))
            self.last_refill = now

# Пример использования:
# limiter = AllegroRateLimiter()
# if limiter.acquire():
#     # отправляем запрос к Allegro API
# else:
#     # обработка превышения лимита 