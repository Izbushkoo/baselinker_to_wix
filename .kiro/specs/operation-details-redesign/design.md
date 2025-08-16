# Дизайн редизайна страницы деталей операции

## Обзор

Новый дизайн страницы деталей операции основан на компактной, информативной структуре с разворачивающимися блоками. Дизайн сохраняет серую цветовую схему и использует Tailwind CSS для стилизации. Основная цель - улучшить UX за счет более логичной группировки информации и компактного отображения.

## Архитектура

### Структура страницы

Страница состоит из следующих основных блоков:

1. **Шапка (Header)** - компактная шапка с навигацией и статусом
2. **Кнопки действий** - основные операции с заказом
3. **Блок ошибок** - отображается только при наличии ошибок валидации
4. **Товары заказа** - разворачивающаяся таблица с товарами
5. **Логи операции** - история обработки операции

### Компоненты и интерфейсы

#### 1. Компонент шапки (OperationHeader)

```html
<div class="bg-gray-100 border border-gray-300 rounded-lg p-4 mb-6">
  <!-- Основная строка шапки -->
  <div class="flex items-center justify-between">
    <!-- Левая часть: кнопка назад + заголовок + иконка разворачивания -->
    <div class="flex items-center space-x-3">
      <button onclick="history.back()" class="text-gray-600 hover:text-gray-800">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
        </svg>
      </button>
      <h1 class="text-lg font-semibold text-gray-800">Детали операции</h1>
      <button id="toggleDetails" class="text-gray-500 hover:text-gray-700">
        <svg class="w-4 h-4 transform transition-transform" id="toggleIcon">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>
    </div>
    
    <!-- Правая часть: статус списания -->
    <div id="stockStatus" class="px-3 py-1 rounded-full text-sm font-medium">
      <!-- Динамически заполняется через JavaScript -->
    </div>
  </div>
  
  <!-- Разворачивающиеся детали -->
  <div id="operationDetails" class="hidden mt-4 pt-4 border-t border-gray-200">
    <!-- Детали операции -->
  </div>
</div>
```

#### 2. Компонент деталей операции (OperationDetails)

```html
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
  <div class="space-y-2">
    <div class="flex justify-between">
      <span class="text-gray-600">ID заказа:</span>
      <button onclick="copyToClipboard('{{ operation.order_id }}')" 
              class="text-gray-800 hover:text-blue-600 font-mono cursor-pointer">
        {{ operation.order_id }}
      </button>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-600">Аккаунт:</span>
      <span class="text-gray-800">{{ operation.account_name or 'Не указан' }}</span>
    </div>
  </div>
  
  <div class="space-y-2">
    <div class="flex justify-between">
      <span class="text-gray-600">Статус заказа:</span>
      <span class="text-gray-800" id="orderStatus">{{ order_status }}</span>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-600">Статус операции:</span>
      <span class="px-2 py-1 rounded text-xs" id="operationStatus">{{ operation.status }}</span>
    </div>
  </div>
  
  <div class="space-y-2">
    <div class="flex justify-between">
      <span class="text-gray-600">Обновлено:</span>
      <span class="text-gray-800">{{ operation.updated_at.strftime('%d.%m.%Y %H:%M') }}</span>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-600">Следующая попытка:</span>
      <span class="text-gray-800">{{ operation.next_retry_at.strftime('%d.%m.%Y %H:%M') if operation.next_retry_at else 'Не запланирована' }}</span>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-600">Количество попыток:</span>
      <span class="text-gray-800">{{ operation.retry_count }}</span>
    </div>
  </div>
</div>
```

#### 3. Компонент кнопок действий (ActionButtons)

```html
<div class="flex flex-wrap gap-3 mb-6">
  <button onclick="performStockDeduction()" 
          class="bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded-lg font-medium transition-colors">
    Провести операцию списания
  </button>
  
  <button onclick="cancelOperation()" 
          class="bg-gray-500 hover:bg-gray-600 text-white px-4 py-2 rounded-lg font-medium transition-colors" 
          disabled>
    Отменить операцию списания
  </button>
  
  <button onclick="openProductsPanel()" 
          class="bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded-lg font-medium transition-colors">
    Товары
  </button>
</div>
```

#### 4. Компонент блока ошибок (ErrorBlock)

```html
<div id="errorBlock" class="bg-red-50 border border-red-200 rounded-lg p-4 mb-6" style="display: none;">
  <h3 class="text-lg font-semibold text-red-800 mb-4">Ошибка</h3>
  <div id="errorItems" class="space-y-3">
    <!-- Карточки товаров с ошибками -->
  </div>
</div>
```

#### 5. Компонент товаров заказа (OrderItems)

```html
<div class="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-6">
  <div class="flex items-center justify-between cursor-pointer" onclick="toggleOrderItems()">
    <h3 class="text-lg font-semibold text-gray-800">Товары заказа</h3>
    <svg class="w-5 h-5 text-gray-500 transform transition-transform" id="orderItemsIcon">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
    </svg>
  </div>
  
  <div id="orderItemsContent" class="hidden mt-4">
    <div class="h-64 overflow-y-auto border border-gray-300 rounded">
      <table class="w-full text-sm">
        <thead class="bg-gray-100 sticky top-0">
          <tr>
            <th class="px-3 py-2 text-left">SKU</th>
            <th class="px-3 py-2 text-left">Название</th>
            <th class="px-3 py-2 text-right">Цена за ед.</th>
            <th class="px-3 py-2 text-right">Кол-во</th>
            <th class="px-3 py-2 text-right">Цена</th>
          </tr>
        </thead>
        <tbody id="orderItemsTable">
          <!-- Строки товаров -->
        </tbody>
      </table>
    </div>
    
    <div class="mt-4 text-right space-y-1">
      <div class="text-sm text-gray-600">
        Стоимость доставки: <span id="deliveryCost">{{ order.delivery.cost.amount }} {{ order.delivery.cost.currency }}</span>
      </div>
      <div class="text-lg font-semibold">
        Итого: <span id="totalAmount">{{ order.summary.totalToPay.amount }} {{ order.summary.totalToPay.currency }}</span>
      </div>
    </div>
  </div>
</div>
```

#### 6. Компонент логов (LogsBlock)

```html
<div class="bg-gray-50 border border-gray-200 rounded-lg p-4">
  <h3 class="text-lg font-semibold text-gray-800 mb-4">Логи</h3>
  <div class="h-64 overflow-y-auto space-y-2">
    <div id="logsContainer">
      <!-- Записи логов -->
    </div>
  </div>
</div>
```

## Модели данных

### Статусы заказа

Логика определения статуса заказа:

```javascript
function getOrderStatus(order) {
  // Приоритет отмены продавцом
  if (order.fulfillment?.status === 'CANCELLED') {
    return 'Отменен продавцом';
  }
  
  // Отмена покупателем
  if (order.status === 'CANCELLED') {
    return 'Отменен покупателем';
  }
  
  // Если заказ отправлен, показываем статус fulfillment
  if (order.fulfillment?.status === 'SENT') {
    return 'Отправлен';
  }
  
  // Иначе показываем основной статус
  const statusMap = {
    'BOUGHT': 'Куплен',
    'FILLED_IN': 'Заполнен',
    'READY_FOR_PROCESSING': 'Готов к обработке'
  };
  
  return statusMap[order.status] || order.status;
}
```

### Статус списания

```javascript
async function getStockStatus(orderId, tokenId) {
  try {
    const response = await fetch(`/api/stock-status/${orderId}/${tokenId}`);
    const data = await response.json();
    return data.is_stock_updated ? 'Списано' : 'Не списано';
  } catch (error) {
    return 'Неизвестно';
  }
}
```

## Обработка ошибок

### Валидация товаров

Блок ошибок отображается только при наличии товаров с ошибками валидации:

```javascript
function renderErrorBlock(validationDetails) {
  const errorBlock = document.getElementById('errorBlock');
  const errorItems = document.getElementById('errorItems');
  
  if (!validationDetails || validationDetails.invalid_items === 0) {
    errorBlock.style.display = 'none';
    return;
  }
  
  errorBlock.style.display = 'block';
  errorItems.innerHTML = validationDetails.items_details
    .filter(item => !item.valid)
    .map(item => renderErrorItem(item))
    .join('');
}

function renderErrorItem(item) {
  return `
    <div class="flex items-center space-x-4 bg-white border border-red-200 rounded-lg p-3">
      <div class="w-12 h-12 bg-gray-200 rounded flex-shrink-0">
        <!-- Изображение товара или placeholder -->
      </div>
      <div class="flex-1">
        <button onclick="copyToClipboard('${item.sku}')" 
                class="font-mono font-semibold text-gray-800 hover:text-blue-600 cursor-pointer">
          ${item.sku}
        </button>
        <div class="flex space-x-4 mt-2 text-sm">
          <span class="text-green-600">Доступно: ${item.available_quantity}</span>
          <span class="text-blue-600">Требуется: ${item.required_quantity}</span>
          <span class="text-red-600">Нехватка: ${item.shortage_quantity}</span>
        </div>
      </div>
    </div>
  `;
}
```

## Стратегия тестирования

### Модульные тесты

1. **Тестирование логики статусов заказа**
   - Проверка корректного определения статуса при различных комбинациях
   - Тестирование приоритетов статусов

2. **Тестирование компонентов интерфейса**
   - Проверка разворачивания/сворачивания блоков
   - Тестирование копирования в буфер обмена

### Интеграционные тесты

1. **Тестирование загрузки данных**
   - Проверка корректного отображения данных операции
   - Тестирование обработки ошибок API

2. **Тестирование взаимодействия с микросервисом**
   - Проверка получения статуса списания
   - Тестирование выполнения операций списания

### Тестирование пользовательского интерфейса

1. **Адаптивность**
   - Проверка корректного отображения на разных размерах экрана
   - Тестирование таблицы товаров в половину экрана

2. **Интерактивность**
   - Проверка работы всех кнопок и ссылок
   - Тестирование модальных окон и панелей

## Производительность

### Оптимизация загрузки

1. **Ленивая загрузка данных**
   - Статус списания загружается асинхронно
   - Детали заказа загружаются при разворачивании

2. **Кэширование**
   - Кэширование статуса списания на клиенте
   - Минимизация повторных запросов к API

### Оптимизация рендеринга

1. **Виртуализация длинных списков**
   - Для таблицы товаров при большом количестве позиций
   - Для списка логов при большой истории

2. **Оптимизация DOM-операций**
   - Группировка изменений DOM
   - Использование DocumentFragment для массовых операций