# Руководство по тестированию системы синхронизации складских остатков

## Обзор системы

Система синхронизации складских остатков обеспечивает надежную синхронизацию между локальным складским учетом и микросервисом Allegro с использованием hybrid подхода:

- **Немедленная синхронизация** при создании операции
- **Retry механизм** для неудачных операций  
- **Периодическая сверка** состояний
- **Telegram уведомления** о проблемах
- **API мониторинга** для управления

## Предварительная подготовка

### 1. Запуск миграций базы данных

```bash
# Применение миграций для новых таблиц синхронизации
docker-compose exec app alembic upgrade head
```

### 2. Проверка переменных окружения

Убедитесь, что в `.env` или `.env.docker` настроены:

```env
# Основные настройки микросервиса
MICRO_SERVICE_URL=http://your-microservice-url
PROJECT_NAME=baselinker_to_wix

# Telegram уведомления (опционально)
STOCK_SYNC_TELEGRAM_MAIN_CHAT_ID=-1234567890
STOCK_SYNC_TELEGRAM_CRITICAL_CHAT_ID=-1234567890  
STOCK_SYNC_TELEGRAM_TECH_CHAT_ID=-1234567890

# Настройки синхронизации (опционально, есть defaults)
STOCK_SYNC_RETRY_MAX_ATTEMPTS=5
STOCK_SYNC_MONITORING_MAX_PENDING_OPERATIONS=1000
STOCK_SYNC_ALERTS_ENABLED=true
```

## Тестирование компонентов

### 1. Проверка API endpoints

#### Получение статуса системы
```bash
curl -X GET "http://localhost:9042/api/v1/stock_sync/health" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

Ожидаемый ответ:
```json
{
  "status": "success",
  "health_data": {
    "pending_operations": 0,
    "failed_operations": 0,
    "completed_today": 0,
    "stale_operations": 0,
    "health_status": "healthy"
  }
}
```

#### Просмотр pending операций
```bash
curl -X GET "http://localhost:9042/api/v1/stock_sync/operations/pending?limit=10" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

#### Валидация товара на складе
```bash
curl -X POST "http://localhost:9042/api/v1/stock_sync/validate/stock?sku=TEST_SKU&quantity=1&warehouse=Ирина" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

#### Ручная синхронизация операции
```bash
curl -X POST "http://localhost:9042/api/v1/stock_sync/sync/manual?token_id=test-token&order_id=test-order&sku=TEST_SKU&quantity=1" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### 2. Проверка Celery задач

#### Просмотр активных задач
```bash
# Проверка статуса Celery worker
docker-compose exec celery_worker celery -A app.celery_shared inspect active

# Проверка расписания задач
docker-compose exec celery_beat celery -A app.celery_shared inspect scheduled
```

#### Ручной запуск задач для тестирования
```bash
# Обработка pending операций
docker-compose exec celery_worker celery -A app.celery_shared call app.services.stock_sync_tasks.process_pending_stock_operations

# Мониторинг системы
docker-compose exec celery_worker celery -A app.celery_shared call app.services.stock_sync_tasks.monitor_sync_system_health

# Валидация операций  
docker-compose exec celery_worker celery -A app.celery_shared call app.services.stock_sync_tasks.validate_pending_operations
```

### 3. Проверка базы данных

#### Проверка создания таблиц
```sql
-- Подключение к БД
docker-compose exec postgres psql -U postgres -d baselinker_to_wix

-- Проверка таблиц
\dt pending*
\dt stock*

-- Проверка структуры таблиц
\d pendingstockoperation
\d stocksynchronizationlog

-- Примеры запросов
SELECT COUNT(*) FROM pendingstockoperation;
SELECT status, COUNT(*) FROM pendingstockoperation GROUP BY status;
SELECT action, COUNT(*) FROM stocksynchronizationlog GROUP BY action;
```

### 4. Тестирование основного workflow

#### Создание тестовой операции синхронизации

```python
# Пример Python скрипта для тестирования
from app.services.stock_synchronization_service import StockSynchronizationService
from app.services.warehouse.manager import get_manager
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.database import SessionLocal
from app.core.security import create_access_token
from app.core.config import settings

# Создаем тестовую сессию
session = SessionLocal()

# Инициализируем клиенты
jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
orders_client = OrdersClient(jwt_token=jwt_token, base_url=settings.MICRO_SERVICE_URL)
tokens_client = AllegroTokenMicroserviceClient(jwt_token=jwt_token, base_url=settings.MICRO_SERVICE_URL)
inventory_manager = get_manager()

# Создаем сервис синхронизации
sync_service = StockSynchronizationService(
    session=session,
    orders_client=orders_client,
    tokens_client=tokens_client,  
    inventory_manager=inventory_manager
)

# Тестовая операция
result = sync_service.sync_stock_deduction(
    token_id="test-token-uuid",
    order_id="test-order-123", 
    sku="TEST_SKU_001",
    quantity=1,
    warehouse="Ирина"
)

print(f"Результат синхронизации: {result}")
session.close()
```

### 5. Проверка Telegram уведомлений

Если настроены Telegram чаты, проверьте получение уведомлений:

1. **Тестовое уведомление о недостатке товара**
2. **Уведомление о сбое синхронизации** 
3. **Ежедневная сводка** (если включена)
4. **Уведомления о состоянии системы**

### 6. Нагрузочное тестирование

#### Создание множественных операций
```python
# Скрипт для создания нескольких тестовых операций
import uuid

for i in range(10):
    result = sync_service.sync_stock_deduction(
        token_id=str(uuid.uuid4()),
        order_id=f"load-test-{i}",
        sku=f"LOAD_TEST_SKU_{i:03d}",
        quantity=1,
        warehouse="Ирина"
    )
    print(f"Операция {i+1}: {result.success}")
```

#### Проверка обработки очереди
```bash
# Запуск обработки pending операций
curl -X POST "http://localhost:9042/api/v1/stock_sync/operations/process?limit=20" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

## Ожидаемые результаты тестирования

### ✅ Успешное завершение тестов

1. **API endpoints возвращают корректные ответы**
2. **Celery задачи запускаются без ошибок**
3. **Базы данных содержит новые таблицы**
4. **Операции синхронизации создаются и обрабатываются**
5. **Retry механизм работает для неудачных операций**
6. **Telegram уведомления доставляются (если настроены)**

### ❌ Возможные проблемы и решения

#### Проблемы с миграциями
```bash
# Откат и повторное применение миграции
docker-compose exec app alembic downgrade -1
docker-compose exec app alembic upgrade head
```

#### Ошибки Pydantic
- Убедитесь что установлен `pydantic-settings`
- Проверьте совместимость версий в `requirements.txt`

#### Проблемы с Celery задачами
```bash
# Перезапуск Celery сервисов
docker-compose restart celery_worker celery_beat
```

#### Ошибки подключения к микросервису
- Проверьте `MICRO_SERVICE_URL` в переменных окружения
- Убедитесь что микросервис Allegro доступен
- Проверьте правильность JWT токенов

## Мониторинг в production

### Логи системы синхронизации
```bash
# Просмотр логов синхронизации
docker-compose logs -f app | grep "stock.sync"
docker-compose logs -f celery_worker | grep "stock_sync_tasks"
```

### Ключевые метрики для мониторинга

1. **Количество pending операций** (не должно расти бесконечно)
2. **Процент успешности синхронизации** (должен быть >95%)
3. **Время выполнения операций** (среднее <5 секунд)
4. **Количество застрявших операций** (должно быть близко к 0)

### Dashboard запросы (для Grafana/аналогов)
```sql
-- Pending операции по времени
SELECT 
  DATE_TRUNC('hour', created_at) as hour,
  COUNT(*) as pending_count
FROM pendingstockoperation 
WHERE status = 'PENDING'
GROUP BY hour 
ORDER BY hour;

-- Успешность синхронизации за последние 24 часа
SELECT 
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM pendingstockoperation 
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY status;
```

## Заключение

Система синхронизации складских остатков готова к работе в production среде. Регулярно мониторьте ключевые метрики и настройте автоматические алерты для критических ситуаций.

При возникновении проблем проверьте:
1. Логи приложения и Celery
2. Состояние микросервиса Allegro  
3. API endpoints мониторинга
4. Telegram уведомления (если настроены)