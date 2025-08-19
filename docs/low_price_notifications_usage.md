# Система уведомлений о продажах по низким ценам

## Обзор

Система автоматически мониторит продажи товаров и отправляет уведомления в Telegram при обнаружении случаев, когда товар был продан по цене ниже установленной минимальной цены.

## Принцип работы

1. **Автоматическая проверка**: При обработке pending stock operations система автоматически проверяет цены всех позиций заказа
2. **Сравнение с минимальными ценами**: Использует `PricesService` для получения минимальных цен по SKU
3. **Отправка уведомлений**: При обнаружении нарушений отправляет структурированные уведомления в Telegram
4. **Graceful degradation**: При ошибках проверки цен основной процесс продолжается

## Конфигурация

### Включение/отключение функциональности

```python
# В .env.docker или переменных окружения
STOCK_SYNC_PRICE_CHECKING_ENABLED=true
STOCK_SYNC_PRICE_CHECK_TIMEOUT_SECONDS=30
STOCK_SYNC_PRICE_VIOLATION_THRESHOLD_PERCENT=0.0
STOCK_SYNC_PRICE_CHECK_BATCH_SIZE=100
```

### Настройки по умолчанию

- `price_checking_enabled`: `true` - включена по умолчанию
- `price_check_timeout_seconds`: `30` - таймаут 30 секунд
- `price_violation_threshold_percent`: `0.0` - любое нарушение
- `price_check_batch_size`: `100` - размер батча для получения цен

## Формат уведомлений

### Структура сообщения

```
🚨 Продажа по цене ниже минимальной

Аккаунт: Allegro_Account_1
Заказ: 12345-67890
Операция: 550e8400-e29b-41d4-a716-446655440000

📦 Нарушения:
• SKU123 "Product Name"
  Продано: 24.99 PLN
  Минимум: 30.00 PLN
  Убыток: -5.01 PLN (-16.7%)

💰 Общий убыток: -5.01 PLN

💡 Рекомендации:
• Проверьте настройки цен для аккаунта Allegro_Account_1
• Убедитесь, что минимальные цены актуальны
• Рассмотрите возможность корректировки ценовой политики

📋 Мониторинг операций

🕒 2025-01-15 14:30:25 UTC
```

### Приоритеты уведомлений

- **Critical**: Много нарушений (>3) или большой убыток (>100 PLN)
- **High**: Несколько нарушений (>1) или средний убыток (>50 PLN)
- **Normal**: Одно нарушение или небольшой убыток

## Интеграция в код

### Автоматическое использование

Система автоматически интегрирована в `StockSynchronizationService` и не требует дополнительных вызовов.

### Ручное использование

```python
from app.services.low_price_sale_checker import LowPriceSaleChecker
from app.services.prices_service import PricesService
from app.services.standardized_logger import get_standardized_logger

# Создание сервиса
prices_service = PricesService()
logger = get_standardized_logger(session)
checker = LowPriceSaleChecker(prices_service, logger)

# Проверка цен заказа
violations = checker.check_order_prices(
    operation={"id": "operation_id", "order_id": "order_id"},
    line_items=line_items
)

# Создание сводки
summary = checker.create_violation_summary(
    violations=violations,
    account_name="account_name",
    order_id="order_id",
    operation_id="operation_id"
)
```

## Логирование

### Новые действия в StandardizedLogger

- `PRICE_CHECK_STARTED` - начало проверки цен
- `PRICE_CHECK_COMPLETED` - завершение проверки цен
- `PRICE_VIOLATION_DETECTED` - обнаружение нарушения
- `PRICE_CHECK_FAILED` - ошибка проверки цен
- `PRICE_SERVICE_UNAVAILABLE` - недоступность сервиса цен

### Примеры логов

```python
# Начало проверки
logger.info(
    action=LogAction.PRICE_CHECK_STARTED,
    message="Начинаем проверку цен для заказа",
    operation_id="operation_id",
    order_id="order_id",
    line_items_count=5
)

# Обнаружение нарушения
logger.warning(
    action=LogAction.PRICE_VIOLATION_DETECTED,
    message="Обнаружено нарушение минимальной цены для SKU123",
    sku="SKU123",
    product_name="Product Name",
    sale_price="24.99",
    minimum_price="30.00",
    violation_amount="5.01",
    violation_percentage=16.7
)
```

## Обработка ошибок

### Graceful Degradation

1. **PricesService недоступен**: Проверка пропускается, логируется предупреждение
2. **Ошибка получения цен**: Проверка пропускается для проблемного SKU
3. **Ошибка парсинга цен**: Позиция пропускается, логируется ошибка
4. **Ошибка отправки уведомления**: Используется очередь отложенных сообщений

### Логирование ошибок

Все ошибки логируются через `StandardizedLogger` с контекстом:
- ID операции
- ID заказа
- Метод, где произошла ошибка
- Детали ошибки

## Мониторинг и метрики

### Отслеживаемые показатели

- Количество проверок цен
- Количество обнаруженных нарушений
- Ошибки проверки цен
- Доступность сервиса цен

### Интеграция с существующим мониторингом

Система использует существующий `StandardizedLogger` для консистентности с остальными компонентами.

## Troubleshooting

### Частые проблемы

1. **Проверка цен не выполняется**
   - Проверьте `STOCK_SYNC_PRICE_CHECKING_ENABLED=true`
   - Убедитесь, что `PricesService` доступен

2. **Уведомления не отправляются**
   - Проверьте настройки Telegram в `stock_sync_config`
   - Убедитесь, что `StockSyncNotificationService` работает

3. **Ошибки в логах**
   - Проверьте доступность базы данных цен
   - Убедитесь, что структура `line_items` корректна

### Отладка

Включите детальное логирование для отладки:

```python
# В коде
logger.setLevel(logging.DEBUG)

# В конфигурации
STOCK_SYNC_LOGGING_LEVEL=DEBUG
```

## Производительность

### Оптимизации

- Батчевое получение цен для всех SKU заказа
- Асинхронная обработка без блокировки основного процесса
- Кэширование минимальных цен (планируется)

### Влияние на производительность

- Минимальное влияние на время обработки операций
- Проверка цен выполняется параллельно с основным процессом
- Таймаут ограничивает время ожидания

## Расширение функциональности

### Возможные улучшения

1. **Кэширование цен**: Добавить Redis кэш для минимальных цен
2. **Аналитика**: Сбор статистики по нарушениям цен
3. **Автоматические действия**: Автоматическая корректировка цен
4. **Интеграция с другими системами**: Подключение к системам управления ценами

### Добавление новых проверок

```python
class CustomPriceChecker(LowPriceSaleChecker):
    def _should_check_price(self, minimum_price: Optional[Decimal]) -> bool:
        # Кастомная логика проверки
        return minimum_price is not None and minimum_price > 10.0
```

## Заключение

Система уведомлений о продажах по низким ценам обеспечивает автоматический мониторинг ценовой политики и оперативное реагирование на потенциальные убытки. Система спроектирована для надежности и минимального влияния на основные процессы.
