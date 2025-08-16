# Руководство по миграции на стандартизированное логирование

## Обзор изменений

В рамках задачи 3 была выполнена интеграция стандартизированной системы логирования в `StockSynchronizationService`. Все вызовы старого метода `_log_operation` были заменены на соответствующие методы `StandardizedLogger`.

## Выполненные изменения

### 1. Добавлена зависимость StandardizedLogger

```python
# В конструкторе StockSynchronizationService
self.standardized_logger = get_standardized_logger(session)
```

### 2. Обновлены импорты

```python
from app.services.standardized_logger import get_standardized_logger, ValidationResult
```

### 3. Удален старый метод _log_operation

Метод `_log_operation` был полностью удален, так как больше не используется.

### 4. Заменены все вызовы логирования

#### Создание операций
**Было:**
```python
self._log_operation(
    operation.id,
    "created",
    f"Операция создана для заказа {order_id}, аккаунт {account_name}"
)
```

**Стало:**
```python
self.standardized_logger.log_operation_created(
    operation_id=operation.id,
    order_id=order_id,
    account_name=account_name,
    warehouse=warehouse,
    operation_type=OperationType.DEDUCTION.value
)
```

#### Переходы статусов
**Добавлено:**
```python
self.standardized_logger.log_status_transition(
    operation_id=operation.id,
    from_status=OperationStatus.PENDING,
    to_status=OperationStatus.COMPLETED,
    reason=f"Заказ {operation.order_id} уже был списан вручную в микросервисе",
    additional_context={
        "order_status": order_status,
        "completion_reason": "already_processed_in_microservice"
    }
)
```

#### Загрузка позиций заказа
**Добавлено:**
```python
# Начало загрузки
self.standardized_logger.log_line_items_loading(
    operation_id=operation.id,
    order_id=operation.order_id,
    account_name=account_name
)

# Успешная загрузка
self.standardized_logger.log_line_items_loaded(
    operation_id=operation.id,
    order_id=operation.order_id,
    items_count=len(line_items)
)

# Ошибка загрузки
self.standardized_logger.log_line_items_load_failed(
    operation_id=operation.id,
    order_id=operation.order_id,
    error_message=error_msg
)
```

#### Валидация остатков
**Добавлено:**
```python
# Начало валидации
self.standardized_logger.log_stock_validation_started(
    operation_id=operation.id,
    warehouse=operation.warehouse,
    items_count=len(operation.line_items)
)

# Успешная валидация
self.standardized_logger.log_stock_validation_passed(
    operation_id=operation.id,
    items_count=validation_result.total_items
)

# Провал валидации
validation_result_obj = ValidationResult(...)
self.standardized_logger.log_validation_failure(
    operation_id=operation.id,
    validation_result=validation_result_obj
)
```

#### Списание остатков
**Добавлено:**
```python
# Начало списания
self.standardized_logger.log_stock_deduction_started(
    operation_id=operation.id,
    warehouse=operation.warehouse,
    items_count=len(operation.line_items)
)

# Успешное списание позиции
self.standardized_logger.log_stock_deduction_completed(
    operation_id=operation.id,
    sku=sku,
    quantity=quantity,
    warehouse=operation.warehouse
)

# Ошибка списания
self.standardized_logger.log_stock_deduction_failed(
    operation_id=operation.id,
    error_message=error_msg
)
```

#### Синхронизация с микросервисом
**Добавлено:**
```python
# Начало синхронизации
self.standardized_logger.log_microservice_sync_started(
    operation_id=operation.id,
    order_id=operation.order_id
)

# Успешная синхронизация
self.standardized_logger.log_microservice_sync_success(
    operation_id=operation.id,
    order_id=operation.order_id,
    execution_time_ms=execution_time
)

# Ошибка синхронизации
self.standardized_logger.log_microservice_sync_failed(
    operation_id=operation.id,
    order_id=operation.order_id,
    error_message=error_msg,
    execution_time_ms=execution_time
)
```

#### Retry логика
**Добавлено:**
```python
# Планирование повтора
self.standardized_logger.log_retry_scheduled(
    operation_id=operation.id,
    retry_count=operation.retry_count,
    next_retry_at=operation.next_retry_at,
    reason="Не удалось загрузить позиции заказа"
)

# Превышение лимита попыток
self.standardized_logger.log_max_retries_reached(
    operation_id=operation.id,
    max_retries=self.config.max_retries,
    final_error="Не удалось загрузить позиции заказа"
)
```

#### Обработка ошибок
**Добавлено:**
```python
self.standardized_logger.log_error_with_context(
    operation_id=operation.id,
    error=e,
    context={
        "method": "create_order_processing_operation",
        "order_id": order_id,
        "account_name": account_name,
        "warehouse": warehouse
    }
)
```

## Преимущества новой системы

### 1. Стандартизированные действия
- Все действия используют enum `LogAction` для последовательности
- Исключены опечатки в именах действий
- Легче анализировать логи

### 2. Структурированное логирование
- Детальная информация о валидации
- Контекстная информация об ошибках
- Измерение времени выполнения

### 3. Переходы статусов
- Явное логирование всех изменений статусов
- Причины переходов
- Дополнительный контекст

### 4. Специализированные методы
- Методы для конкретных действий
- Автоматическое добавление релевантной информации
- Упрощение кода

## Обратная совместимость

- Все существующие логи сохраняются в той же таблице `StockSynchronizationLog`
- Структура данных остается совместимой
- Старые логи можно анализировать теми же инструментами

## Следующие шаги

После интеграции стандартизированного логирования можно:

1. Анализировать логи с помощью новых стандартизированных действий
2. Создавать дашборды на основе структурированных данных
3. Настроить алерты на основе конкретных действий и статусов
4. Использовать измерения времени для оптимизации производительности

## Проверка миграции

Для проверки успешности миграции:

1. Убедитесь, что код компилируется без ошибок
2. Проверьте, что все логи записываются в базу данных
3. Убедитесь, что используются стандартизированные действия из `LogAction`
4. Проверьте, что переходы статусов логируются корректно