# Технический план реализации системы синхронизации остатков с Allegro

## Содержание
1. [Компоненты системы](#компоненты-системы)
2. [Rate Limiter](#rate-limiter)
3. [Celery задачи](#celery-задачи)
4. [API методы](#api-методы)
5. [Обработка ошибок](#обработка-ошибок)
6. [Мониторинг и логирование](#мониторинг-и-логирование)
7. [Конфигурация](#конфигурация)
8. [Тестирование](#тестирование)

---

## Компоненты системы

### 1. AllegroRateLimiter
**Файл**: `app/services/allegro/rate_limiter.py`

Класс для контроля частоты запросов к API Allegro с использованием алгоритма Token Bucket.

```python
class AllegroRateLimiter:
    def __init__(self, requests_per_minute: int = 9000):
        self.bucket_size = requests_per_minute
        self.refill_rate = requests_per_minute / 60  # tokens per second
        self.tokens = requests_per_minute
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, tokens: int = 1) -> bool:
        """Получить разрешение на выполнение запроса"""
        
    def wait_for_capacity(self, tokens: int = 1) -> float:
        """Ждать до получения разрешения"""
```

### 2. AllegroOfferService
**Файл**: `app/services/allegro/offer_service.py`

Сервис для работы с офферами Allegro, включая обновление количества товаров.

```python
class AllegroOfferService:
    def __init__(self, api_service: AllegroApiService, rate_limiter: AllegroRateLimiter):
        self.api_service = api_service
        self.rate_limiter = rate_limiter
    
    def update_offer_stock(self, token: str, offer_id: str, new_stock: int) -> bool:
        """Обновить количество товара в оффере"""
        
    def get_offers_by_sku_batch(self, token: str, sku_list: List[str]) -> Dict[str, Any]:
        """Получить офферы по списку SKU"""
        
    def batch_update_offers(self, token: str, updates: List[Dict]) -> List[Dict]:
        """Массовое обновление офферов"""
```

### 3. AllegroStockSyncService
**Файл**: `app/services/allegro/stock_sync_service.py`

Основной сервис для синхронизации остатков между локальной БД и Allegro.

```python
class AllegroStockSyncService:
    def __init__(self, db: Session, offer_service: AllegroOfferService):
        self.db = db
        self.offer_service = offer_service
        self.notification_service = TelegramNotificationService()
    
    def sync_single_account(self, token: AllegroToken, products: List[Product]) -> SyncResult:
        """Синхронизация одного аккаунта"""
        
    def sync_all_accounts(self) -> List[SyncResult]:
        """Синхронизация всех аккаунтов"""
        
    def get_products_with_stock(self) -> List[Dict]:
        """Получить все товары с остатками"""
```

---

## Rate Limiter

### Алгоритм Token Bucket
```python
class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self._lock = threading.Lock()
    
    def _refill(self):
        now = time.time()
        tokens_to_add = (now - self.last_refill) * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def wait_time(self, tokens: int = 1) -> float:
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                return 0
            return (tokens - self.tokens) / self.refill_rate
```

### Интеграция с Redis
```python
class RedisRateLimiter:
    def __init__(self, redis_client: redis.Redis, key_prefix: str = "allegro_rate_limit"):
        self.redis = redis_client
        self.key_prefix = key_prefix
    
    def acquire(self, client_id: str, tokens: int = 1) -> bool:
        key = f"{self.key_prefix}:{client_id}"
        # Lua script для атомарного обновления счетчика
        lua_script = """
        local key = KEYS[1]
        local tokens = tonumber(ARGV[1])
        local capacity = tonumber(ARGV[2])
        local refill_rate = tonumber(ARGV[3])
        local current_time = tonumber(ARGV[4])
        
        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local current_tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or current_time
        
        local tokens_to_add = (current_time - last_refill) * refill_rate
        current_tokens = math.min(capacity, current_tokens + tokens_to_add)
        
        if current_tokens >= tokens then
            current_tokens = current_tokens - tokens
            redis.call('HMSET', key, 'tokens', current_tokens, 'last_refill', current_time)
            redis.call('EXPIRE', key, 3600)
            return 1
        else
            return 0
        end
        """
        
        result = self.redis.eval(lua_script, 1, key, tokens, 9000, 150, time.time())
        return bool(result)
```

---

## Celery задачи

### 1. Основная задача синхронизации
```python
@celery.task(bind=True, name="app.celery_app.sync_allegro_stock_all_accounts")
def sync_allegro_stock_all_accounts(self):
    """
    Основная задача синхронизации остатков товаров с офферами Allegro
    для всех аккаунтов.
    """
    try:
        with SessionLocal() as session:
            # Получаем все товары с остатками
            products = get_all_products_with_stock(session)
            
            # Получаем все активные токены
            tokens = get_all_active_tokens(session)
            
            if not tokens:
                logger.info("Нет активных токенов Allegro")
                return {"status": "success", "message": "Нет токенов для обработки"}
            
            # Создаем группу подзадач для каждого токена
            job_group = group(
                sync_allegro_stock_single_account.s(token.id_, products)
                for token in tokens
            )
            
            # Запускаем обработку
            result = job_group.apply_async()
            
            # Ждем завершения всех задач
            results = result.get(timeout=3600)  # 1 час timeout
            
            return {
                "status": "success",
                "processed_accounts": len(tokens),
                "results": results
            }
            
    except Exception as e:
        logger.error(f"Ошибка в основной задаче синхронизации: {str(e)}")
        raise self.retry(countdown=60, max_retries=3)
```

### 2. Задача синхронизации одного аккаунта
```python
@celery.task(bind=True, name="app.celery_app.sync_allegro_stock_single_account")
def sync_allegro_stock_single_account(self, token_id: str, products: List[Dict]):
    """
    Синхронизация остатков товаров для одного аккаунта Allegro.
    """
    try:
        with SessionLocal() as session:
            # Получаем токен
            token = get_token_by_id_sync(session, token_id)
            if not token:
                raise ValueError(f"Токен {token_id} не найден")
            
            # Проверяем и обновляем токен
            token = check_token_sync(session, token)
            
            # Группируем товары по батчам (100 SKU максимум)
            batches = list(chunks(products, 100))
            
            # Создаем группу задач для каждого батча
            batch_jobs = group(
                sync_allegro_offers_batch.s(token_id, batch)
                for batch in batches
            )
            
            # Запускаем обработку батчей
            result = batch_jobs.apply_async()
            batch_results = result.get(timeout=1800)  # 30 минут timeout
            
            # Агрегируем результаты
            total_processed = sum(r.get("processed", 0) for r in batch_results)
            total_updated = sum(r.get("updated", 0) for r in batch_results)
            total_errors = sum(r.get("errors", 0) for r in batch_results)
            
            return {
                "status": "success",
                "account_name": token.account_name,
                "processed": total_processed,
                "updated": total_updated,
                "errors": total_errors,
                "batches": len(batches)
            }
            
    except Exception as e:
        logger.error(f"Ошибка синхронизации аккаунта {token_id}: {str(e)}")
        raise self.retry(countdown=120, max_retries=2)
```

### 3. Задача обработки батча офферов
```python
@celery.task(bind=True, name="app.celery_app.sync_allegro_offers_batch")
def sync_allegro_offers_batch(self, token_id: str, products_batch: List[Dict]):
    """
    Обработка батча товаров для синхронизации офферов.
    """
    try:
        with SessionLocal() as session:
            # Получаем токен
            token = get_token_by_id_sync(session, token_id)
            if not token:
                raise ValueError(f"Токен {token_id} не найден")
            
            # Создаем сервисы
            rate_limiter = AllegroRateLimiter()
            api_service = SyncAllegroApiService()
            offer_service = AllegroOfferService(api_service, rate_limiter)
            
            # Извлекаем SKU из батча
            sku_list = [product["sku"] for product in products_batch]
            
            # Получаем офферы по SKU
            offers_response = offer_service.get_offers_by_sku_batch(
                token.access_token, sku_list
            )
            
            # Создаем задачи для каждого найденного оффера
            update_tasks = []
            for offer in offers_response.get("offers", []):
                # Находим соответствующий товар в батче
                product = next(
                    (p for p in products_batch if p["sku"] == offer.get("external", {}).get("id")),
                    None
                )
                
                if product:
                    update_tasks.append(
                        update_single_allegro_offer.s(
                            token_id, offer["id"], product["sku"], product["stock"]
                        )
                    )
            
            # Запускаем обновление офферов
            if update_tasks:
                update_group = group(update_tasks)
                update_results = update_group.apply_async().get(timeout=900)  # 15 минут
                
                # Подсчитываем результаты
                processed = len(update_tasks)
                updated = sum(1 for r in update_results if r.get("status") == "success")
                errors = sum(1 for r in update_results if r.get("status") == "error")
                
                return {
                    "status": "success",
                    "processed": processed,
                    "updated": updated,
                    "errors": errors,
                    "sku_count": len(sku_list),
                    "offers_found": len(offers_response.get("offers", []))
                }
            else:
                return {
                    "status": "success",
                    "processed": 0,
                    "updated": 0,
                    "errors": 0,
                    "sku_count": len(sku_list),
                    "offers_found": 0
                }
                
    except Exception as e:
        logger.error(f"Ошибка обработки батча для токена {token_id}: {str(e)}")
        raise self.retry(countdown=180, max_retries=2)
```

### 4. Задача обновления одного оффера
```python
@celery.task(bind=True, name="app.celery_app.update_single_allegro_offer")
def update_single_allegro_offer(self, token_id: str, offer_id: str, sku: str, target_stock: int):
    """
    Обновление количества товара в конкретном оффере с retry механизмом.
    """
    try:
        with SessionLocal() as session:
            # Получаем токен
            token = get_token_by_id_sync(session, token_id)
            if not token:
                raise ValueError(f"Токен {token_id} не найден")
            
            # Создаем сервисы
            rate_limiter = AllegroRateLimiter()
            api_service = SyncAllegroApiService()
            
            # Ждем разрешения от rate limiter
            if not rate_limiter.acquire():
                wait_time = rate_limiter.wait_for_capacity()
                logger.info(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
            
            # Получаем текущую информацию об оффере
            offer_details = api_service.get_offer_details(token.access_token, offer_id)
            current_stock = offer_details.get("stock", {}).get("available", 0)
            
            # Проверяем, нужно ли обновление
            if current_stock == target_stock:
                logger.info(f"Offer {offer_id} already has correct stock: {current_stock}")
                return {
                    "status": "success",
                    "message": "No update needed",
                    "offer_id": offer_id,
                    "sku": sku,
                    "current_stock": current_stock,
                    "target_stock": target_stock
                }
            
            # Обновляем количество
            update_data = {
                "stock": {
                    "available": target_stock
                }
            }
            
            # Выполняем PATCH запрос
            response = api_service.update_offer(token.access_token, offer_id, update_data)
            
            logger.info(f"Successfully updated offer {offer_id}: {current_stock} -> {target_stock}")
            
            return {
                "status": "success",
                "offer_id": offer_id,
                "sku": sku,
                "current_stock": current_stock,
                "target_stock": target_stock,
                "updated_at": datetime.now().isoformat()
            }
            
    except Exception as e:
        error_msg = f"Ошибка обновления оффера {offer_id}: {str(e)}"
        logger.error(error_msg)
        
        # Отправляем уведомление в Telegram при достижении лимита попыток
        if self.request.retries >= self.max_retries:
            notification_data = {
                "account_name": token.account_name if 'token' in locals() else "Unknown",
                "sku": sku,
                "offer_id": offer_id,
                "current_stock": current_stock if 'current_stock' in locals() else "Unknown",
                "target_stock": target_stock,
                "error_message": str(e),
                "retry_count": self.request.retries,
                "timestamp": datetime.now().isoformat()
            }
            
            send_allegro_error_notification.delay(notification_data)
            
            return {
                "status": "error",
                "offer_id": offer_id,
                "sku": sku,
                "error": str(e),
                "retry_count": self.request.retries
            }
        
        # Экспоненциальный backoff
        countdown = min(300, (2 ** self.request.retries) * 30)
        raise self.retry(countdown=countdown, max_retries=3)
```

---

## API методы

### Обновление метода AllegroApiService
```python
def update_offer(self, token: str, offer_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обновление оффера через PATCH /sale/offers/{offerId}
    
    Args:
        token: Токен доступа
        offer_id: ID оффера для обновления
        update_data: Данные для обновления
        
    Returns:
        Dict[str, Any]: Ответ от API
        
    Raises:
        ValueError: При ошибке обновления
    """
    try:
        response = self.client.patch(
            f"/sale/offers/{offer_id}",
            headers=self._get_headers(token),
            json=update_data
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise ValueError(f"Ошибка при обновлении оффера {offer_id}: {str(e)}")

def get_offer_details(self, token: str, offer_id: str) -> Dict[str, Any]:
    """
    Получение деталей оффера
    
    Args:
        token: Токен доступа
        offer_id: ID оффера
        
    Returns:
        Dict[str, Any]: Детали оффера
    """
    try:
        response = self.client.get(
            f"/sale/offers/{offer_id}",
            headers=self._get_headers(token)
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise ValueError(f"Ошибка при получении деталей оффера {offer_id}: {str(e)}")
```

---

## Обработка ошибок

### Система уведомлений
```python
@celery.task(name="app.celery_app.send_allegro_error_notification")
def send_allegro_error_notification(notification_data: Dict[str, Any]):
    """
    Отправка уведомления об ошибке в Telegram.
    """
    try:
        tg_manager = TelegramManager(chat_id=os.getenv("NOTIFY_GROUP_ID"))
        
        message = f"""
🚨 <b>Ошибка синхронизации Allegro</b>

<b>Аккаунт:</b> {notification_data['account_name']}
<b>SKU:</b> <code>{notification_data['sku']}</code>
<b>Offer ID:</b> <code>{notification_data['offer_id']}</code>

<b>Остатки:</b>
• Текущий: {notification_data['current_stock']}
• Целевой: {notification_data['target_stock']}

<b>Ошибка:</b> {notification_data['error_message']}
<b>Попыток:</b> {notification_data['retry_count']}
<b>Время:</b> {notification_data['timestamp']}

<i>Требуется ручная проверка</i>
        """
        
        tg_manager.send_message(message)
        logger.info(f"Sent error notification for offer {notification_data['offer_id']}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {str(e)}")
```

### Классы исключений
```python
class AllegroSyncError(Exception):
    """Базовое исключение для ошибок синхронизации Allegro"""
    pass

class AllegroRateLimitError(AllegroSyncError):
    """Исключение при превышении лимита запросов"""
    pass

class AllegroTokenError(AllegroSyncError):
    """Исключение при проблемах с токеном"""
    pass

class AllegroOfferNotFoundError(AllegroSyncError):
    """Исключение когда оффер не найден"""
    pass
```

---

## Мониторинг и логирование

### Метрики
```python
class AllegroSyncMetrics:
    """Класс для сбора метрик синхронизации"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.prefix = "allegro_sync_metrics"
    
    def increment_counter(self, metric_name: str, value: int = 1):
        """Увеличить счетчик"""
        key = f"{self.prefix}:{metric_name}"
        self.redis.incr(key, value)
        self.redis.expire(key, 86400)  # 24 часа
    
    def set_gauge(self, metric_name: str, value: float):
        """Установить значение метрики"""
        key = f"{self.prefix}:{metric_name}"
        self.redis.set(key, value)
        self.redis.expire(key, 86400)
    
    def record_timing(self, metric_name: str, duration: float):
        """Записать время выполнения"""
        key = f"{self.prefix}:timing:{metric_name}"
        self.redis.lpush(key, duration)
        self.redis.ltrim(key, 0, 999)  # Храним последние 1000 записей
        self.redis.expire(key, 86400)
```

### Логирование
```python
import structlog

logger = structlog.get_logger()

def log_sync_operation(operation: str, **kwargs):
    """Структурированное логирование операций синхронизации"""
    logger.info(
        "allegro_sync_operation",
        operation=operation,
        **kwargs
    )

def log_sync_error(operation: str, error: Exception, **kwargs):
    """Логирование ошибок синхронизации"""
    logger.error(
        "allegro_sync_error",
        operation=operation,
        error=str(error),
        error_type=type(error).__name__,
        **kwargs
    )
```

---

## Конфигурация

### Настройки в settings
```python
# Allegro sync settings
ALLEGRO_SYNC_RATE_LIMIT = 9000  # requests per minute
ALLEGRO_SYNC_BATCH_SIZE = 100   # SKU per batch
ALLEGRO_SYNC_RETRY_COUNT = 3    # max retries
ALLEGRO_SYNC_RETRY_DELAY = 30   # base delay in seconds
ALLEGRO_SYNC_SCHEDULE = 1800    # 30 minutes

# Telegram notifications
ALLEGRO_ERROR_NOTIFICATION_CHAT_ID = os.getenv("ALLEGRO_ERROR_NOTIFICATION_CHAT_ID")
```

### Celery Beat schedule
```python
ALLEGRO_SYNC_SCHEDULE = {
    'sync-allegro-stock-all-accounts': {
        'task': 'app.celery_app.sync_allegro_stock_all_accounts',
        'schedule': 1800,  # 30 минут
    },
}
```

---

## Тестирование

### Unit тесты
```python
class TestAllegroRateLimiter:
    def test_acquire_success(self):
        limiter = AllegroRateLimiter(requests_per_minute=60)
        assert limiter.acquire() is True
    
    def test_acquire_failure_when_exhausted(self):
        limiter = AllegroRateLimiter(requests_per_minute=1)
        assert limiter.acquire() is True
        assert limiter.acquire() is False

class TestAllegroOfferService:
    def test_update_offer_stock_success(self):
        # Mock API response
        pass
    
    def test_get_offers_by_sku_batch(self):
        # Mock API response
        pass

class TestAllegroSyncTasks:
    def test_sync_single_account_success(self):
        # Mock database and API
        pass
    
    def test_update_single_offer_success(self):
        # Mock API response
        pass
```

### Integration тесты
```python
class TestAllegroSyncIntegration:
    def test_full_sync_flow(self):
        """Тест полного цикла синхронизации"""
        # Настройка тестовых данных
        # Запуск синхронизации
        # Проверка результатов
        pass
    
    def test_error_handling_and_notifications(self):
        """Тест обработки ошибок и уведомлений"""
        # Имитация ошибки API
        # Проверка retry механизма
        # Проверка отправки уведомлений
        pass
```

---

## Deployment

### Docker
```dockerfile
# Добавить в Dockerfile
RUN pip install redis structlog
```

### Environment Variables
```env
# Allegro sync configuration
ALLEGRO_SYNC_RATE_LIMIT=9000
ALLEGRO_SYNC_BATCH_SIZE=100
ALLEGRO_SYNC_RETRY_COUNT=3
ALLEGRO_SYNC_RETRY_DELAY=30
ALLEGRO_SYNC_SCHEDULE=1800

# Telegram notifications
ALLEGRO_ERROR_NOTIFICATION_CHAT_ID=your_chat_id
```

### Monitoring
```python
# Prometheus metrics endpoint
@app.get("/metrics/allegro-sync")
def get_allegro_sync_metrics():
    metrics = AllegroSyncMetrics(redis_client)
    return {
        "processed_offers": metrics.get_counter("processed_offers"),
        "updated_offers": metrics.get_counter("updated_offers"),
        "errors": metrics.get_counter("errors"),
        "avg_response_time": metrics.get_avg_timing("api_response_time")
    }
```

---

## Заключение

Данная система обеспечивает:

✅ **Масштабируемость**: Многоуровневая архитектура Celery задач  
✅ **Надежность**: Retry механизм с экспоненциальным backoff  
✅ **Соблюдение лимитов**: Token bucket rate limiter  
✅ **Мониторинг**: Детальное логирование и метрики  
✅ **Уведомления**: Telegram боты для критических ошибок  
✅ **Производительность**: Батчевая обработка до 100 SKU  

Система готова к интеграции в существующий проект и может быть легко расширена для поддержки дополнительных маркетплейсов. 