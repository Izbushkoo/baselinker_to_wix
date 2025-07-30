# Руководство по логированию

## Обзор

Система логирования была полностью переработана для обеспечения более удобочитаемых логов с фильтрацией технических деталей. Теперь в консоли отображаются только важные бизнес-события, а технические логи (SQL запросы, HTTP запросы, etc.) записываются только в файлы.

## Основные возможности

### 1. Фильтрация технических логов
- SQL запросы отключены в консоли по умолчанию
- HTTP запросы библиотек (urllib3, httpx) скрыты
- Логи Celery, Redis, PostgreSQL минимизированы
- Логи Uvicorn/Gunicorn отключены

### 2. Цветной вывод в консоль
- INFO: зеленый
- WARNING: желтый  
- ERROR: красный
- DEBUG: голубой
- CRITICAL: пурпурный

### 3. Разделение логов по файлам
- `logs/app.log` - все логи приложения
- `logs/errors.log` - только ошибки
- Консоль - только бизнес-логика

### 4. Специальные логгеры для бизнес-логики
- `allegro.sync` - синхронизация Allegro
- `allegro.api` - API Allegro
- `wix.api` - API Wix
- `baselinker` - интеграция с Baselinker
- `warehouse` - управление складом
- `operations` - операции
- `prices` - цены
- `stock` - остатки

## Настройка через переменные окружения

### LOG_LEVEL
Уровень логирования для консоли:
- `DEBUG` - отладочная информация
- `INFO` - общая информация (по умолчанию)
- `WARNING` - предупреждения
- `ERROR` - ошибки
- `CRITICAL` - критические ошибки

### ENABLE_SQL_LOGS
Включить логи SQL запросов в консоль:
- `true` - показывать SQL запросы
- `false` - скрыть SQL запросы (по умолчанию)

### ENABLE_DEBUG_LOGS
Включить отладочное логирование:
- `true` - включить DEBUG уровень
- `false` - использовать обычный уровень (по умолчанию)

## Примеры использования

### Базовое логирование
```python
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
logger.info("Заказ создан успешно")
logger.error("Ошибка при создании заказа")
```

### Логирование бизнес-событий
```python
from app.utils.logging_config import log_business_event

log_business_event(
    "order_created", 
    "Новый заказ создан",
    order_id="12345",
    customer="Иван Иванов",
    amount=1500.00
)
```

### Логирование ошибок с контекстом
```python
from app.utils.logging_config import log_error_with_context

try:
    # какой-то код
    pass
except Exception as e:
    log_error_with_context(
        e, 
        "Ошибка при синхронизации заказов",
        user_id="user123",
        sync_type="allegro"
    )
```

### Включение отладочного режима
```python
from app.utils.logging_config import enable_debug_logging

# Включает DEBUG уровень и SQL логи
enable_debug_logging()
```

## Форматы логов

### Консоль (с цветами)
```
10:30:15 [INFO] allegro.sync: [SYNC_STARTED] Начало синхронизации заказов | user_id=user123
10:30:16 [ERROR] errors: [ERROR] Ошибка API: timeout | user_id=user123 | api=allegro
```

### Файл app.log
```
2025-07-30 10:30:15 [INFO] allegro.sync: [SYNC_STARTED] Начало синхронизации заказов | user_id=user123
2025-07-30 10:30:16 [ERROR] errors: [ERROR] Ошибка API: timeout | user_id=user123 | api=allegro
```

### Файл errors.log
```
2025-07-30 10:30:16 [ERROR] errors: [ERROR] Ошибка API: timeout | user_id=user123 | api=allegro
```

## Рекомендации по использованию

### 1. Для разработки
```bash
# Включить отладку
export LOG_LEVEL=DEBUG
export ENABLE_SQL_LOGS=true
```

### 2. Для продакшена
```bash
# Минимальные логи
export LOG_LEVEL=WARNING
export ENABLE_SQL_LOGS=false
```

### 3. Для диагностики проблем
```bash
# Подробные логи без SQL
export LOG_LEVEL=DEBUG
export ENABLE_SQL_LOGS=false
```

### 4. Для анализа SQL запросов
```bash
# Логи с SQL запросами
export LOG_LEVEL=INFO
export ENABLE_SQL_LOGS=true
```

## Мониторинг логов

### Просмотр логов в реальном времени
```bash
# Все логи
tail -f logs/app.log

# Только ошибки
tail -f logs/errors.log

# Логи с цветами
tail -f logs/app.log | grep -E "(ERROR|WARNING|CRITICAL)"
```

### Поиск по логам
```bash
# Поиск ошибок
grep "ERROR" logs/app.log

# Поиск по типу события
grep "SYNC_STARTED" logs/app.log

# Поиск по пользователю
grep "user_id=user123" logs/app.log
```

## Миграция с старой системы

### Старый код
```python
import logging
logger = logging.getLogger(__name__)
logger.info("Сообщение")
```

### Новый код
```python
from app.utils.logging_config import get_logger
logger = get_logger(__name__)
logger.info("Сообщение")
```

### Для бизнес-событий
```python
# Вместо
logger.info(f"Заказ {order_id} создан для {customer}")

# Используйте
log_business_event("order_created", "Заказ создан", order_id=order_id, customer=customer)
```

## Troubleshooting

### Проблема: Не видно SQL запросы
**Решение:** Установите `ENABLE_SQL_LOGS=true`

### Проблема: Слишком много логов
**Решение:** Установите `LOG_LEVEL=WARNING`

### Проблема: Нужны отладочные логи
**Решение:** Установите `LOG_LEVEL=DEBUG`

### Проблема: Логи не записываются в файл
**Решение:** Проверьте права доступа к папке `logs/` 