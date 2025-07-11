## Задача: Реализация редактирования товаров
- **Статус**: В процессе
- **Описание**: Добавление возможности редактирования ранее созданных товаров через веб-интерфейс и API
- **Шаги выполнения**:
  - [x] Анализ текущей архитектуры API и моделей данных
  - [x] Создание Pydantic схем для валидации данных при обновлении
  - [x] Реализация API эндпоинта PUT/PATCH для обновления товаров
  - [x] Создание веб-страницы для редактирования товаров
  - [x] Добавление кнопки "Редактировать" в карточки товаров
  - [x] Реализация валидации данных на фронтенде и бэкенде
  - [x] Интеграция с системой логирования операций
  - [x] Реализация каскадных операций в базе данных
  - [х] Применение миграций для активации каскадных ограничений
  - [ ] Обновление Telegram бота для поддержки редактирования
  - [ ] Добавление тестов для новой функциональности
  - [ ] Обновление документации API
- **Зависимости**: Существующая система аутентификации и авторизации
- **Технические требования**:
  - Поддержка обновления названия, SKU, EAN, изображения
  - Валидация уникальности SKU при изменении
  - Сохранение истории изменений через OperationsService
  - Поддержка частичного обновления (PATCH)
  - Обработка изображений с оптимизацией
  - Каскадное удаление и обновление связанных записей (Stock, Sale, Transfer)

## Задача: Интеграция с Wix API для управления товарами
- **Статус**: В процессе (70% завершено)
- **Описание**: Реализация интерфейса для получения и обновления товаров в Wix через API
- **Шаги выполнения**:
  - [x] Базовая структура WixApiService
  - [x] Реализация метода получения товаров по SKU
  - [x] Реализация моделей для работы с инвентарем
  - [x] Реализация метода query_inventory
  - [x] Реализация метода update_inventory
  - [x] Реализация высокоуровневых методов для работы с API Wix
  - [x] Улучшение валидации данных в API сервисе Wix
  - [ ] Написание тестов для методов работы с инвентарем
  - [ ] Реализация массового обновления инвентаря
  - [ ] Интеграция с основным потоком данных
- **Зависимости**: Базовая структура WixApiService
- **Текущий статус**:
  - ✅ **Реализовано**: Полная базовая функциональность WixApiService
    - Методы получения товаров по SKU с пагинацией
    - Методы работы с инвентарем (query_inventory, update_inventory)
    - Высокоуровневые методы для получения всех товаров и инвентарей
    - Поддержка фильтрации и постраничной загрузки
    - Валидация данных через SQLModel
    - Обработка ошибок API
  - ⚠️ **Требует доработки**: Интеграция с основным потоком данных
    - WixApiService не интегрирован в процесс обработки заказов Allegro
    - Нет автоматического обновления остатков в Wix при списании товаров
    - Отсутствует синхронизация между локальной базой и Wix
  - 📋 **Планируется**: Тестирование и оптимизация
    - Написание unit-тестов для методов работы с инвентарем
    - Реализация массового обновления инвентаря
    - Добавление кэширования и механизма повторных попыток

## Задача: Оптимизация работы с инвентарем
- **Статус**: Не начата
- **Описание**: Улучшение производительности и надежности работы с инвентарем
- **Шаги выполнения**:
  - [ ] Реализация кэширования для часто запрашиваемых данных
  - [ ] Добавление механизма повторных попыток при ошибках API
  - [ ] Реализация пакетной обработки обновлений
  - [ ] Добавление мониторинга и логирования операций
- **Зависимости**: Завершение базовой интеграции с Wix API

## Задача: Реализация метода получения товаров по SKU
- **Статус**: В процессе
- **Описание**: Разработка метода для получения товаров из Wix по списку SKU
- **Шаги выполнения**:
  - [ ] Модификация метода query_products для поддержки списка SKU
  - [ ] Добавление пагинации для больших списков
  - [ ] Обработка ошибок и валидация входных данных
  - [ ] Тестирование метода
- **Зависимости**: Базовая структура WixApiService

## Задача: Реализация высокоуровневых методов для работы с API Wix
- **Статус**: Завершена
- **Описание**: Реализация методов для получения всех товаров и инвентарей с учетом ограничений API и поддержкой фильтрации
- **Шаги выполнения**:
  - [x] Реализация базовых моделей данных
  - [x] Реализация моделей фильтров
  - [x] Реализация метода получения всех товаров
  - [x] Реализация метода получения всех инвентарей
  - [x] Добавление поддержки фильтрации
  - [x] Реализация постраничной загрузки
  - [x] Улучшение обработки ошибок
  - [x] Добавление логирования
  - [x] Тестирование и отладка
  - [x] Обновление документации
- **Зависимости**: Нет

## Задача: Улучшение валидации данных в API сервисе Wix
- **Статус**: Завершена
- **Описание**: Улучшение валидации данных и обработки ошибок в API сервисе
- **Шаги выполнения**:
  - [x] Исправление валидации вариантов товаров
  - [x] Исправление обработки preorder_info
  - [x] Улучшение обработки алиасов полей
  - [x] Добавление методов для работы со словарями
  - [x] Улучшение логирования ошибок
  - [x] Тестирование валидации
  - [x] Обновление документации
- **Зависимости**: Реализация высокоуровневых методов для работы с API Wix

## Задача: Реализация метода получения офферов Allegro
- **Статус**: Завершена
- **Описание**: Добавление метода для получения списка офферов с возможностью фильтрации по external.id и другим параметрам
- **Шаги выполнения**:
  - [x] Анализ API документации Allegro
  - [x] Реализация синхронной версии метода
  - [x] Реализация асинхронной версии метода
  - [x] Добавление валидации параметров
  - [x] Обновление документации
- **Зависимости**: Нет

## Задача: Реализация централизованного управления остатками
- **Статус**: Не начата
- **Описание**: Создание системы синхронизации остатков между PostgreSQL, Wix и Allegro с поддержкой множественных аккаунтов
- **Шаги выполнения**:
  - [ ] Создание моделей данных для интеграции (WixAccount, WixProductMapping, WixInventorySync)
  - [ ] Реализация InventorySyncService для централизованной синхронизации
  - [ ] Реализация WixAccountService для управления аккаунтами Wix
  - [ ] Интеграция InventorySyncService в AllegroStockService
  - [ ] Создание Celery задач для периодической синхронизации
  - [ ] Создание API эндпоинтов для управления аккаунтами и маппингами
  - [ ] Создание веб-интерфейса для мониторинга синхронизации
  - [ ] Написание тестов для новой функциональности
  - [ ] Документирование API и процессов синхронизации
- **Зависимости**: Завершение базовой интеграции с Wix API
- **Технические требования**:
  - PostgreSQL как источник правды для остатков
  - Поддержка множественных аккаунтов Wix
  - Автоматическая синхронизация при списании товаров
  - Периодическая синхронизация всех остатков
  - Отслеживание истории синхронизации
  - Обработка ошибок и повторные попытки
  - Масштабируемость для будущих маркетплейсов

## Задача: Создание Celery задачи для синхронизации количества товаров с Wix
- **Статус**: Завершена
- **Описание**: Создание автоматизированной задачи для синхронизации количества товаров между локальной базой данных и Wix магазином
- **Шаги выполнения**:
  - [x] Анализ существующих моделей товаров и складов
  - [x] Изучение Wix API для работы с инвентарем
  - [x] Создание функции получения всех SKU и количества из базы данных
  - [x] Создание функции поиска товаров в Wix по SKU
  - [x] Создание функции обновления количества в Wix
  - [x] Создание основной Celery задачи
  - [x] Добавление логирования и обработки ошибок
  - [x] Создание API эндпоинтов для ручного запуска
  - [x] Добавление задачи в расписание по умолчанию
  - [x] Обновление документации проекта
- **Зависимости**: Wix API сервис, модели товаров и складов
- **Результат**: Полностью функциональная система синхронизации с автоматическим запуском каждый час и возможностью ручного запуска через API

## Задача: Обновление Celery задачи sync_wix_inventory
- **Статус**: Завершена
- **Описание**: Обновить Celery задачу sync_wix_inventory для использования нового метода get_wix_products_info_by_sku_list вместо старой логики получения данных из Wix
- **Шаги выполнения**:
  - [x] Изучить новый метод get_wix_products_info_by_sku_list
  - [x] Обновить логику задачи для использования нового метода
  - [x] Упростить процесс получения информации о товарах в Wix
  - [x] Сохранить батчевую обработку обновлений
  - [x] Обновить документацию
- **Зависимости**: Новый метод get_wix_products_info_by_sku_list в WixApiService

## Задача: Исправление ошибок API и оптимизация групповых обновлений
- **Статус**: Завершена
- **Описание**: Исправить ошибку 400 Bad Request при обновлении инвентаря и оптимизировать логику для групповых обновлений вместо отдельных запросов
- **Шаги выполнения**:
  - [x] Выявить причину ошибки 400 Bad Request
  - [x] Исправить формат данных для API increment/decrement
  - [x] Добавить обязательный параметр variantId в запросы
  - [x] Изменить логику Celery задачи для групповой обработки
  - [x] Разделить обновления на инкременты и декременты
  - [x] Отправлять групповые запросы вместо отдельных
  - [x] Создать тестовый скрипт для проверки
  - [x] Обновить документацию
- **Зависимости**: WixApiService, Celery задача sync_wix_inventory

## Задача: Отладка ошибок Allegro API и улучшение логирования
- **Статус**: В процессе
- **Описание**: Диагностика и исправление ошибки `'NoneType' object has no attribute 'get'` при работе с API Allegro
- **Шаги выполнения**:
  - [x] Анализ ошибки в логах Celery
  - [x] Добавление подробного логирования в методы AllegroApiService
  - [x] Добавление логирования в процесс обработки событий заказов
  - [x] Добавление проверок структуры ответов API
  - [ ] Тестирование с реальными токенами
  - [ ] Анализ полученных логов для выявления корневой причины
  - [ ] Исправление выявленных проблем
  - [ ] Обновление документации
- **Зависимости**: AllegroApiService, Celery задача process_allegro_order_events
- **Текущий статус**: Добавлено подробное логирование для диагностики проблемы

## Задача: Улучшение стабильности Wix API и замена print на логирование
- **Статус**: Завершена
- **Описание**: Исправление ошибок 500 от Wix API и замена всех print на логирование

## Задача: Диагностика ошибки 404 от Wix API
- **Статус**: В процессе
- **Описание**: Исследование и исправление ошибки 404 "Entity not found" от Wix API
- **Шаги выполнения**:
  - [x] Добавлен метод `test_connection()` для проверки подключения к Wix API
  - [x] Добавлен API эндпоинт для тестирования подключения
  - [x] Добавлено подробное логирование инициализации WixApiService
  - [x] Добавлена валидация критических параметров (API_KEY, SITE_ID)
  - [x] Добавлено тестирование альтернативных endpoints
  - [ ] Проверка валидности WIX_SITE_ID и WIX_API_KEY
  - [ ] Тестирование подключения через API эндпоинт
  - [ ] Анализ ответов от Wix API для определения точной причины ошибки
- **Зависимости**: WixApiService, allegro_sync.py, celery_app.py
- **Шаги выполнения**:
  - [x] Замена всех print на соответствующие уровни логирования
  - [x] Добавление подробного логирования запросов к Wix API
  - [x] Реализация механизма повторных попыток для временных ошибок
  - [x] Валидация SKU перед отправкой запросов
  - [x] Ограничение размера батча до 50 элементов
  - [x] Добавление экспоненциальной задержки между попытками
  - [x] Обновление документации
- **Зависимости**: WixApiService
- **Результат**: Повышена стабильность работы с Wix API, улучшена диагностика ошибок

## Задача: Создание API роута для запуска синхронизации Wix
- **Статус**: Завершена
- **Описание**: Создание API эндпоинта для единоразового запуска синхронизации стоков Wix
- **Шаги выполнения**:
  - [x] Добавление импорта функции `launch_wix_sync` в роутер
  - [x] Создание POST эндпоинта `/wix-sync` в `allegro_sync.py`
  - [x] Реализация обработки ошибок и логирования
  - [x] Возврат ID задачи для отслеживания статуса
  - [x] Обновление документации
- **Зависимости**: `launch_wix_sync` функция из `celery_app.py`
- **Результат**: API эндпоинт `POST /api/v1/allegro_sync/wix-sync` для запуска синхронизации Wix

## Задача: Исправление загрузки переменных окружения в Celery worker
- **Статус**: Завершена
- **Описание**: Решение проблемы с отсутствующими переменными Wix в Celery worker
- **Шаги выполнения**:
  - [x] Анализ проблемы с загрузкой переменных из `.env.docker` в Celery
  - [x] Добавление загрузки переменных окружения в начало `celery_app.py`
  - [x] Проверка загрузки переменных Wix в функциях запуска
  - [x] Добавление логирования статуса загрузки переменных
  - [x] Обработка ошибок при отсутствии критических переменных
  - [x] Обновление документации
- **Зависимости**: Файл `.env.docker` с переменными Wix
- **Результат**: Корректная загрузка переменных Wix в Celery worker, исправление ошибок 500 от Wix API 