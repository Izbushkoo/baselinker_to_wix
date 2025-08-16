# Стандартизированная система логирования

## Обзор

`StandardizedLogger` - это централизованная система логирования для операций синхронизации складских остатков. Она обеспечивает последовательное и структурированное логирование всех действий в процессе синхронизации.

## Основные возможности

- **Стандартизированные действия**: Использует enum `LogAction` для последовательного именования действий
- **Переходы статусов**: Специальный метод для логирования изменений статусов операций
- **Измерение времени**: Автоматическое измерение и логирование времени выполнения
- **Структурированные ошибки**: Детальное логирование ошибок с контекстом
- **Валидация**: Специализированное логирование результатов валидации

## Быстрый старт

```python
from app.services.standardized_logger import get_standardized_logger
from app.models.stock_synchronization import OperationStatus, LogAction

# Создание логгера
logger = get_standardized_logger(session)

# Логирование создания операции
logger.log_operation_created(
    operation_id=operation.id,
    order_id="12345",
    account_name="Test Account",
    warehouse="Ирина",
    operation_type="deduction"
)

# Логирование перехода статуса
logger.log_status_transition(
    operation_id=operation.id,
    from_status=OperationStatus.PENDING,
    to_status=OperationStatus.PROCESSING,
    reason="Line items loaded successfully"
)
```

## Основные методы

### Переходы статусов
- `log_status_transition()` - логирование изменений статусов

### Действия с временем
- `log_action_with_timing()` - общий метод для действий с измерением времени

### Специализированные методы
- `log_operation_created()` - создание операции
- `log_line_items_loading()` - начало загрузки позиций
- `log_line_items_loaded()` - успешная загрузка позиций
- `log_stock_validation_started()` - начало валидации
- `log_stock_validation_passed()` - успешная валидация
- `log_stock_deduction_completed()` - успешное списание
- `log_microservice_sync_success()` - успешная синхронизация

### Обработка ошибок
- `log_validation_failure()` - ошибки валидации
- `log_error_with_context()` - общие ошибки с контекстом
- `log_max_retries_reached()` - превышение лимита попыток

## Миграция с существующего кода

### Было:
```python
self._log_operation(
    operation.id,
    "created",
    f"Операция создана для заказа {order_id}, аккаунт {account_name}"
)
```

### Стало:
```python
self.standardized_logger.log_operation_created(
    operation_id=operation.id,
    order_id=order_id,
    account_name=account_name,
    warehouse="Ирина",
    operation_type="deduction"
)
```

## Интеграция в StockSynchronizationService

```python
class StockSynchronizationService:
    def __init__(self, session: Session):
        self.session = session
        self.standardized_logger = get_standardized_logger(session)
        # ... остальная инициализация
    
    def process_operation(self, operation):
        # Используем стандартизированное логирование
        self.standardized_logger.log_status_transition(
            operation_id=operation.id,
            from_status=operation.status,
            to_status=OperationStatus.PROCESSING,
            reason="Starting processing"
        )
```

## Стандартизированные действия (LogAction)

Все действия определены в enum `LogAction`:

- `OPERATION_CREATED` - создание операции
- `LINE_ITEMS_LOADING` - загрузка позиций
- `STOCK_VALIDATION_STARTED` - начало валидации
- `STOCK_DEDUCTION_COMPLETED` - списание завершено
- `MICROSERVICE_SYNC_SUCCESS` - синхронизация успешна
- `STATUS_TRANSITION` - переход статуса
- `RETRY_SCHEDULED` - запланирован повтор
- И многие другие...

## Примеры использования

Подробные примеры использования смотрите в файле `standardized_logger_examples.py`.