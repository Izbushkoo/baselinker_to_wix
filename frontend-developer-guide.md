# Полное руководство для фронтенд разработчика
## Система переноса офферов между аккаунтами Allegro

Это единый файл-справочник содержит всю необходимую информацию для создания полнофункционального фронтенд интерфейса системы переноса офферов.

## ⚠️ Важное примечание об аутентификации

**Микросервис переноса офферов НЕ предоставляет методы для логина!**

- Микросервис только **валидирует** JWT токен в заголовке `Authorization: Bearer <token>`
- **Логин и создание JWT токена** должны происходить в основном фронтенд приложении
- Фронтенд должен получить готовый JWT токен из основного приложения
- Все примеры в документации учитывают эту особенность

## Содержание

1. [Архитектура и общие принципы](#архитектура-и-общие-принципы)
2. [Аутентификация и авторизация](#аутентификация-и-авторизация)
3. [API эндпоинты](#api-эндпоинты)
4. [WebSocket соединения](#websocket-соединения)
5. [Модели данных](#модели-данных)
6. [Пошаговый workflow](#пошаговый-workflow)
7. [Система мониторинга](#система-мониторинга)
8. [Обработка ошибок](#обработка-ошибок)
9. [Примеры кода](#примеры-кода)
10. [Рекомендации по UX](#рекомендации-по-ux)

---

## Архитектура и общие принципы

### Базовая конфигурация

```javascript
const API_CONFIG = {
    BASE_URL: '/api/v1',
    WS_BASE_URL: '/ws',
    TIMEOUT: 30000,
    RETRY_ATTEMPTS: 3
};

// JWT токен должен передаваться во всех запросах
const getAuthHeaders = () => ({
    'Authorization': `Bearer ${localStorage.getItem('jwt_token')}`,
    'Content-Type': 'application/json'
});
```

### Принципы работы системы

1. **Асинхронная обработка**: Все операции переноса выполняются через Celery задачи
2. **Реальное время**: WebSocket соединения для мониторинга прогресса
3. **Пакетная обработка**: Поддержка переноса тысяч офферов одновременно
4. **Возобновляемость**: Сессии можно приостанавливать и возобновлять
5. **Шаблоны**: Сохранение конфигураций для повторного использования

---

## Аутентификация и авторизация

### Важно: Логин НЕ в микросервисе

**Микросервис переноса офферов НЕ предоставляет методы для логина.** Он только валидирует JWT токен в заголовке `Authorization: Bearer <token>`.

Логин и создание JWT токена должны происходить в основном фронтенд приложении или отдельном сервисе аутентификации.

### JWT токен

Все API запросы требуют готовый JWT токен в заголовке `Authorization`:

```javascript
class AuthService {
    static getToken() {
        return localStorage.getItem('jwt_token');
    }
    
    static setToken(token) {
        localStorage.setItem('jwt_token', token);
    }
    
    static clearToken() {
        localStorage.removeItem('jwt_token');
    }
    
    static isAuthenticated() {
        const token = this.getToken();
        if (!token) return false;
        
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            return payload.exp * 1000 > Date.now();
        } catch {
            return false;
        }
    }
    
    // Этот метод должен быть реализован в основном приложении
    static async login(credentials) {
        // Логин происходит в основном фронтенд приложении
        // или через отдельный сервис аутентификации
        throw new Error('Login should be implemented in main frontend application');
    }
    
    // Получение токена из основного приложения
    static async getTokenFromMainApp() {
        // Пример получения токена из parent window или localStorage
        if (window.parent && window.parent !== window) {
            // Если это iframe, получаем токен от родительского окна
            return new Promise((resolve) => {
                window.parent.postMessage({ type: 'GET_JWT_TOKEN' }, '*');
                window.addEventListener('message', (event) => {
                    if (event.data.type === 'JWT_TOKEN') {
                        resolve(event.data.token);
                    }
                });
            });
        } else {
            // Иначе получаем из localStorage основного приложения
            return this.getToken();
        }
    }
}
```

### Обработка истекших токенов

```javascript
class ApiClient {
    static async request(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {
                ...getAuthHeaders(),
                ...options.headers
            }
        });
        
        if (response.status === 401) {
            AuthService.clearToken();
            
            // НЕ перенаправляем на /login, так как логин не в этом микросервисе
            // Вместо этого уведомляем основное приложение или показываем сообщение
            this.handleAuthRequired();
            throw new Error('Authentication required');
        }
        
        return response;
    }
    
    static handleAuthRequired() {
        if (window.parent && window.parent !== window) {
            // Если это iframe, уведомляем родительское окно
            window.parent.postMessage({ 
                type: 'AUTH_REQUIRED',
                message: 'JWT token expired or invalid'
            }, '*');
        } else {
            // Показываем сообщение пользователю
            ErrorHandler.showNotification('error', 
                'Сессия истекла. Пожалуйста, обновите страницу или войдите заново в основном приложении');
        }
    }
}
```

### Сценарии интеграции с основным приложением

#### 1. Интеграция через iframe

```javascript
// В родительском окне (основное приложение)
window.addEventListener('message', (event) => {
    if (event.data.type === 'GET_JWT_TOKEN') {
        // Отправляем JWT токен в iframe
        event.source.postMessage({
            type: 'JWT_TOKEN',
            token: getJwtToken() // ваш метод получения токена
        }, '*');
    }
    
    if (event.data.type === 'AUTH_REQUIRED') {
        // Обработать истечение токена
        console.log('JWT token expired in offer transfer service');
        refreshTokenAndNotifyIframe();
    }
});

// В iframe (микросервис переноса офферов)
class AuthService {
    static async initializeFromParent() {
        const token = await this.getTokenFromMainApp();
        if (token) {
            this.setToken(token);
        }
    }
}
```

#### 2. Standalone интеграция

```javascript
// Микросервис работает как отдельное приложение
// JWT токен должен быть уже в localStorage

class AuthService {
    static async initialize() {
        const token = this.getToken();
        if (!token) {
            this.showTokenMissingWarning();
            return false;
        }
        return true;
    }
    
    static showTokenMissingWarning() {
        alert('JWT токен не найден. Пожалуйста, войдите в основное приложение сначала.');
    }
}
```

#### 3. Интеграция через URL параметры

```javascript
// Передача токена через URL параметр (НЕ рекомендуется для production)
class AuthService {
    static initializeFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('jwt_token');
        
        if (token) {
            this.setToken(token);
            // Очистить токен из URL для безопасности
            window.history.replaceState({}, document.title, window.location.pathname);
            return true;
        }
        return false;
    }
}
```

#### 4. Интеграция через sessionStorage

```javascript
// Использование sessionStorage для обмена токенами между вкладками
class AuthService {
    static syncWithMainApp() {
        // Слушаем изменения в sessionStorage
        window.addEventListener('storage', (event) => {
            if (event.key === 'jwt_token' && event.newValue) {
                this.setToken(event.newValue);
            }
        });
        
        // Проверяем токен в sessionStorage
        const sessionToken = sessionStorage.getItem('jwt_token');
        if (sessionToken) {
            this.setToken(sessionToken);
        }
    }
}
```

---

## API эндпоинты

### 1. Управление аккаунтами

#### Получить список аккаунтов пользователя
```
GET /api/v1/tokens/user-tokens
```

**Ответ:**
```json
{
    "tokens": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "account_name": "MyStore PL",
            "is_active": true,
            "expires_at": "2024-12-31T23:59:59Z",
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]
}
```

### 2. Работа с рынками

#### Получить доступные рынки
```
GET /api/v1/markets/
```

**Ответ:**
```json
{
    "markets": [
        {
            "code": "PL",
            "name": "Allegro Polska",
            "currency": "PLN",
            "flag_url": "/static/flags/pl.svg",
            "active": true,
            "exchange_rate": 1.0000
        },
        {
            "code": "SK",
            "name": "Allegro Slovensko",
            "currency": "EUR",
            "flag_url": "/static/flags/sk.svg",
            "active": true,
            "exchange_rate": 0.2174
        }
    ]
}
```

#### Получить курсы валют
```
GET /api/v1/markets/currency-rates
```

**Ответ:**
```json
{
    "rates": {
        "base_currency": "PLN",
        "rates": {
            "PLN": 1.0000,
            "EUR": 0.2174,
            "CZK": 5.4500,
            "HUF": 85.2000,
            "USD": 0.2300
        },
        "updated_at": "2024-01-15T11:00:00Z"
    }
}
```

### 3. Сравнение офферов

#### Сравнить офферы между аккаунтами
```
POST /api/v1/offer-transfer/compare-offers
```

**Запрос:**
```json
{
    "source_token_id": "550e8400-e29b-41d4-a716-446655440000",
    "target_token_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

**Ответ:**
```json
{
    "source_account": "MyStore PL",
    "target_account": "MyStore SK",
    "available_offers": [
        {
            "id": "17258483742",
            "external_id": "8850370841114_400g",
            "name": "Produkt testowy 400g",
            "price": {
                "amount": 74.15,
                "currency": "PLN"
            },
            "stock": 3,
            "category": "Żywność > Słodycze",
            "images": [
                "https://allegro.pl/image1.jpg"
            ],
            "created_at": "2024-01-10T12:00:00Z",
            "updated_at": "2024-01-15T10:30:00Z"
        }
    ],
    "total_count": 1,
    "comparison_completed_at": "2024-01-15T11:00:00Z"
}
```

### 4. Предварительный расчет цен

#### Рассчитать цены для рынков
```
POST /api/v1/markets/pricing/preview
```

**Запрос:**
```json
{
    "offers": [
        {
            "id": "17258483742",
            "external_id": "8850370841114_400g",
            "name": "Produkt testowy 400g",
            "price": {
                "amount": 74.15,
                "currency": "PLN"
            },
            "stock": 3,
            "category": "Żywność > Słodycze",
            "images": [],
            "created_at": "2024-01-10T12:00:00Z",
            "updated_at": "2024-01-15T10:30:00Z"
        }
    ],
    "markets": ["SK", "CZ"],
    "pricing_rules": [
        {
            "market_code": "SK",
            "type": "multiply",
            "multiplier": 3.0
        },
        {
            "market_code": "CZ",
            "type": "convert_with_markup",
            "markup_percent": 10.0
        }
    ]
}
```

**Ответ:**
```json
{
    "previews": [
        {
            "offer_id": "17258483742",
            "original_price": {
                "amount": 74.15,
                "currency": "PLN"
            },
            "market_prices": {
                "SK": {
                    "amount": 48.37,
                    "currency": "EUR"
                },
                "CZ": {
                    "amount": 445.23,
                    "currency": "CZK"
                }
            }
        }
    ],
    "total_offers": 1,
    "markets": ["SK", "CZ"]
}
```

### 5. Управление сессиями переноса

#### Запустить перенос
```
POST /api/v1/offer-transfer/start
```

**Запрос:**
```json
{
    "source_token_id": "550e8400-e29b-41d4-a716-446655440000",
    "target_token_id": "550e8400-e29b-41d4-a716-446655440001",
    "offer_ids": ["17258483742"],
    "excluded_offer_ids": [],
    "markets": ["SK", "CZ"],
    "pricing_rules": [
        {
            "market_code": "SK",
            "type": "multiply",
            "multiplier": 3.0
        }
    ],
    "template_name": "My Template"
}
```

**Ответ:**
```json
{
    "id": "session_12345",
    "status": "pending",
    "total_offers": 1,
    "processed_offers": 0,
    "successful_offers": 0,
    "failed_offers": 0,
    "progress_percentage": 0.0,
    "offer_results": [],
    "created_at": "2024-01-15T11:30:00Z",
    "started_at": null,
    "completed_at": null
}
```

#### Получить статус сессии
```
GET /api/v1/offer-transfer/session/{session_id}
```

#### Приостановить сессию
```
POST /api/v1/offer-transfer/session/{session_id}/pause
```

#### Возобновить сессию
```
POST /api/v1/offer-transfer/session/{session_id}/resume
```

#### Отменить сессию
```
DELETE /api/v1/offer-transfer/session/{session_id}
```

### 6. Управление шаблонами

#### Получить шаблоны пользователя
```
GET /api/v1/offer-transfer/templates/
```

#### Создать шаблон
```
POST /api/v1/offer-transfer/templates/
```

**Запрос:**
```json
{
    "name": "Standard EU Transfer",
    "description": "Перенос в SK и CZ с тройным коэффициентом",
    "markets": ["SK", "CZ"],
    "pricing_rules": [
        {
            "market_code": "SK",
            "type": "multiply",
            "multiplier": 3.0
        }
    ],
    "filter_settings": {},
    "transfer_settings": {}
}
```

### 7. Система мониторинга

#### Получить метрики системы
```
GET /api/v1/monitoring/metrics
```

**Ответ:**
```json
{
    "timestamp": "2024-01-15T11:00:00Z",
    "total_sessions": 150,
    "active_sessions": 5,
    "completed_sessions": 140,
    "failed_sessions": 5,
    "total_offers_processed": 15000,
    "successful_offers": 14250,
    "failed_offers": 750,
    "avg_processing_time_ms": 5000.0,
    "avg_offers_per_second": 2.5,
    "market_distribution": {
        "SK": 7500,
        "CZ": 4500,
        "HU": 3000
    },
    "error_rate_percent": 5.0,
    "top_errors": [
        {
            "error_type": "ALLEGRO_API_ERROR",
            "count": 500,
            "percentage": 66.7
        }
    ],
    "api_calls_count": 25000,
    "avg_api_response_time_ms": 800.0,
    "active_websocket_connections": 12
}
```

#### Получить состояние системы
```
GET /api/v1/monitoring/health
```

---

## WebSocket соединения

### Подключение к мониторингу сессии

```javascript
class TransferMonitor {
    constructor(sessionId, token) {
        this.sessionId = sessionId;
        this.token = token;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.callbacks = {
            onSessionUpdate: () => {},
            onOfferUpdate: () => {},
            onProgress: () => {},
            onError: () => {},
            onComplete: () => {}
        };
    }
    
    connect() {
        const wsUrl = `/api/v1/offer-transfer/session/${this.sessionId}/monitor?user_id=${this.getUserId()}`;
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
        };
        
        this.ws.onmessage = (event) => {
            const update = JSON.parse(event.data);
            this.handleUpdate(update);
        };
        
        this.ws.onclose = (event) => {
            console.log('WebSocket closed:', event.code);
            this.handleReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    handleUpdate(update) {
        switch (update.type) {
            case 'session_status':
                this.callbacks.onSessionUpdate(update.data);
                break;
            case 'offer_status':
                this.callbacks.onOfferUpdate(update.data);
                break;
            case 'progress':
                this.callbacks.onProgress(update.data);
                break;
            case 'error':
                this.callbacks.onError(update.data);
                break;
            case 'completed':
                this.callbacks.onComplete(update.data);
                break;
        }
    }
    
    handleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.pow(2, this.reconnectAttempts) * 1000;
            setTimeout(() => this.connect(), delay);
        }
    }
    
    on(event, callback) {
        if (this.callbacks[event]) {
            this.callbacks[event] = callback;
        }
    }
    
    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
    }
    
    getUserId() {
        // Извлечь user_id из JWT токена
        const token = AuthService.getToken();
        const payload = JSON.parse(atob(token.split('.')[1]));
        return payload.user_id;
    }
}
```

### Типы WebSocket сообщений

**1. Обновление статуса сессии:**
```json
{
    "type": "session_status",
    "data": {
        "session_id": "session_12345",
        "status": "running",
        "progress_percentage": 45.0,
        "processed_offers": 45,
        "successful_offers": 42,
        "failed_offers": 3
    }
}
```

**2. Обновление статуса оффера:**
```json
{
    "type": "offer_status",
    "data": {
        "source_offer_id": "17258483742",
        "external_id": "8850370841114_400g",
        "status": "success",
        "new_offer_id": "17812894477",
        "processed_at": "2024-01-15T11:32:00Z",
        "market_results": {
            "SK": {
                "status": "success",
                "new_offer_id": "17812894477"
            }
        }
    }
}
```

---

## Модели данных

### Основные типы данных

```typescript
interface PriceDTO {
    amount: number;
    currency: string;
}

interface OfferSummaryDTO {
    id: string;
    external_id: string;
    name: string;
    price: PriceDTO;
    stock: number;
    category: string;
    images: string[];
    created_at: string;
    updated_at: string;
}

interface MarketDTO {
    code: string; // 'PL', 'SK', 'CZ', 'HU', 'BUSINESS_CZ'
    name: string;
    currency: string;
    flag_url: string;
    active: boolean;
    exchange_rate?: number;
}

interface PricingRuleDTO {
    market_code: string;
    type: 'multiply' | 'add' | 'convert_with_markup' | 'custom';
    multiplier?: number;
    add_amount?: number;
    markup_percent?: number;
    custom_formula?: string;
}

interface TransferSessionDTO {
    id: string;
    status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
    source_account: string;
    target_account: string;
    total_offers: number;
    processed_offers: number;
    successful_offers: number;
    failed_offers: number;
    progress_percentage: number;
    markets: string[];
    pricing_rules: PricingRuleDTO[];
    created_at: string;
    started_at?: string;
    completed_at?: string;
}

interface OfferTransferResultDTO {
    source_offer_id: string;
    external_id: string;
    name: string;
    status: 'pending' | 'processing' | 'success' | 'failed' | 'retrying' | 'skipped';
    new_offer_id?: string;
    error_message?: string;
    error_code?: string;
    task_id?: string;
    processed_at?: string;
    retry_count: number;
    market_results: Record<string, any>;
}
```

---

## Пошаговый workflow

### Полный процесс переноса офферов

```javascript
class OfferTransferWorkflow {
    constructor() {
        this.currentStep = 1;
        this.data = {
            sourceAccount: null,
            targetAccount: null,
            availableOffers: [],
            selectedOffers: [],
            excludedOffers: [],
            selectedMarkets: [],
            pricingRules: [],
            sessionId: null
        };
    }
    
    // Шаг 1: Загрузить аккаунты пользователя
    async loadAccounts() {
        try {
            const response = await ApiClient.request('/api/v1/tokens/user-tokens');
            const data = await response.json();
            return data.tokens;
        } catch (error) {
            throw new Error(`Ошибка загрузки аккаунтов: ${error.message}`);
        }
    }
    
    // Шаг 2: Сравнить офферы между аккаунтами
    async compareOffers(sourceTokenId, targetTokenId) {
        try {
            const response = await ApiClient.request('/api/v1/offer-transfer/compare-offers', {
                method: 'POST',
                body: JSON.stringify({
                    source_token_id: sourceTokenId,
                    target_token_id: targetTokenId
                })
            });
            
            const data = await response.json();
            this.data.availableOffers = data.available_offers;
            return data;
        } catch (error) {
            throw new Error(`Ошибка сравнения офферов: ${error.message}`);
        }
    }
    
    // Шаг 3: Загрузить доступные рынки
    async loadMarkets() {
        try {
            const response = await ApiClient.request('/api/v1/markets/');
            const data = await response.json();
            return data.markets;
        } catch (error) {
            throw new Error(`Ошибка загрузки рынков: ${error.message}`);
        }
    }
    
    // Шаг 4: Предварительный расчет цен
    async previewPricing(offers, markets, pricingRules) {
        try {
            const response = await ApiClient.request('/api/v1/markets/pricing/preview', {
                method: 'POST',
                body: JSON.stringify({
                    offers: offers,
                    markets: markets,
                    pricing_rules: pricingRules
                })
            });
            
            return await response.json();
        } catch (error) {
            throw new Error(`Ошибка расчета цен: ${error.message}`);
        }
    }
    
    // Шаг 5: Запустить перенос
    async startTransfer() {
        try {
            const response = await ApiClient.request('/api/v1/offer-transfer/start', {
                method: 'POST',
                body: JSON.stringify({
                    source_token_id: this.data.sourceAccount.id,
                    target_token_id: this.data.targetAccount.id,
                    offer_ids: this.data.selectedOffers.map(o => o.id),
                    excluded_offer_ids: this.data.excludedOffers.map(o => o.id),
                    markets: this.data.selectedMarkets,
                    pricing_rules: this.data.pricingRules
                })
            });
            
            const sessionData = await response.json();
            this.data.sessionId = sessionData.id;
            return sessionData;
        } catch (error) {
            throw new Error(`Ошибка запуска переноса: ${error.message}`);
        }
    }
    
    // Шаг 6: Мониторинг прогресса
    startMonitoring(callbacks) {
        if (!this.data.sessionId) {
            throw new Error('Сессия не создана');
        }
        
        const monitor = new TransferMonitor(this.data.sessionId, AuthService.getToken());
        
        monitor.on('onSessionUpdate', callbacks.onSessionUpdate || (() => {}));
        monitor.on('onOfferUpdate', callbacks.onOfferUpdate || (() => {}));
        monitor.on('onProgress', callbacks.onProgress || (() => {}));
        monitor.on('onError', callbacks.onError || (() => {}));
        monitor.on('onComplete', callbacks.onComplete || (() => {}));
        
        monitor.connect();
        return monitor;
    }
}
```

---

## Система мониторинга

### Компонент для отображения метрик

```javascript
class MetricsWidget {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.refreshInterval = 30000; // 30 секунд
        this.intervalId = null;
    }
    
    async loadMetrics() {
        try {
            const response = await ApiClient.request('/api/v1/monitoring/metrics');
            const metrics = await response.json();
            this.renderMetrics(metrics);
        } catch (error) {
            console.error('Ошибка загрузки метрик:', error);
        }
    }
    
    renderMetrics(metrics) {
        this.container.innerHTML = `
            <div class="metrics-grid">
                <div class="metric-card">
                    <h3>Активные сессии</h3>
                    <div class="metric-value">${metrics.active_sessions}</div>
                </div>
                <div class="metric-card">
                    <h3>Обработано офферов</h3>
                    <div class="metric-value">${metrics.total_offers_processed.toLocaleString()}</div>
                </div>
                <div class="metric-card">
                    <h3>Успешность</h3>
                    <div class="metric-value">${(100 - metrics.error_rate_percent).toFixed(1)}%</div>
                </div>
                <div class="metric-card">
                    <h3>Среднее время</h3>
                    <div class="metric-value">${(metrics.avg_processing_time_ms / 1000).toFixed(1)}с</div>
                </div>
            </div>
            <div class="market-distribution">
                <h3>Распределение по рынкам</h3>
                ${Object.entries(metrics.market_distribution).map(([market, count]) => `
                    <div class="market-bar">
                        <span class="market-name">${market}</span>
                        <div class="bar">
                            <div class="bar-fill" style="width: ${(count / Math.max(...Object.values(metrics.market_distribution))) * 100}%"></div>
                        </div>
                        <span class="market-count">${count.toLocaleString()}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    startAutoRefresh() {
        this.loadMetrics(); // Загрузить сразу
        this.intervalId = setInterval(() => this.loadMetrics(), this.refreshInterval);
    }
    
    stopAutoRefresh() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }
}
```

### Компонент для мониторинга сессии

```javascript
class SessionMonitorWidget {
    constructor(containerId, sessionId) {
        this.container = document.getElementById(containerId);
        this.sessionId = sessionId;
        this.monitor = null;
        this.sessionData = null;
    }
    
    async init() {
        // Загрузить начальные данные сессии
        await this.loadSessionData();
        this.render();
        
        // Запустить WebSocket мониторинг
        this.startWebSocketMonitoring();
    }
    
    async loadSessionData() {
        try {
            const response = await ApiClient.request(`/api/v1/offer-transfer/session/${this.sessionId}`);
            this.sessionData = await response.json();
        } catch (error) {
            console.error('Ошибка загрузки данных сессии:', error);
        }
    }
    
    startWebSocketMonitoring() {
        this.monitor = new TransferMonitor(this.sessionId, AuthService.getToken());
        
        this.monitor.on('onSessionUpdate', (data) => {
            Object.assign(this.sessionData, data);
            this.updateProgress();
        });
        
        this.monitor.on('onOfferUpdate', (data) => {
            this.updateOfferStatus(data);
        });
        
        this.monitor.on('onProgress', (data) => {
            this.updateStats(data);
        });
        
        this.monitor.on('onError', (data) => {
            this.showError(data);
        });
        
        this.monitor.on('onComplete', (data) => {
            this.showCompletion(data);
        });
        
        this.monitor.connect();
    }
    
    render() {
        this.container.innerHTML = `
            <div class="session-header">
                <h2>Сессия переноса: ${this.sessionId}</h2>
                <div class="session-status status-${this.sessionData.status}">
                    ${this.getStatusText(this.sessionData.status)}
                </div>
            </div>
            
            <div class="progress-section">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${this.sessionData.progress_percentage}%"></div>
                </div>
                <div class="progress-text">
                    ${this.sessionData.processed_offers} / ${this.sessionData.total_offers} офферов
                    (${this.sessionData.progress_percentage.toFixed(1)}%)
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card success">
                    <div class="stat-value">${this.sessionData.successful_offers}</div>
                    <div class="stat-label">Успешно</div>
                </div>
                <div class="stat-card failed">
                    <div class="stat-value">${this.sessionData.failed_offers}</div>
                    <div class="stat-label">Ошибки</div>
                </div>
                <div class="stat-card processing">
                    <div class="stat-value">${this.sessionData.total_offers - this.sessionData.processed_offers}</div>
                    <div class="stat-label">В очереди</div>
                </div>
            </div>
            
            <div class="controls">
                ${this.renderControls()}
            </div>
            
            <div class="offers-list">
                <h3>Офферы</h3>
                <div id="offers-container">
                    ${this.renderOffers()}
                </div>
            </div>
        `;
        
        this.attachEventListeners();
    }
    
    renderControls() {
        switch (this.sessionData.status) {
            case 'running':
                return `
                    <button class="btn btn-warning" onclick="this.pauseSession()">Приостановить</button>
                    <button class="btn btn-danger" onclick="this.cancelSession()">Отменить</button>
                `;
            case 'paused':
                return `
                    <button class="btn btn-success" onclick="this.resumeSession()">Возобновить</button>
                    <button class="btn btn-danger" onclick="this.cancelSession()">Отменить</button>
                `;
            default:
                return '';
        }
    }
    
    renderOffers() {
        return this.sessionData.offer_results.map(offer => `
            <div class="offer-item status-${offer.status}" id="offer-${offer.source_offer_id}">
                <div class="offer-info">
                    <div class="offer-name">${offer.name}</div>
                    <div class="offer-id">ID: ${offer.source_offer_id}</div>
                    <div class="offer-external-id">External ID: ${offer.external_id}</div>
                </div>
                <div class="offer-status">
                    <div class="status-badge status-${offer.status}">
                        ${this.getStatusText(offer.status)}
                    </div>
                    ${offer.new_offer_id ? `<div class="new-id">Новый ID: ${offer.new_offer_id}</div>` : ''}
                    ${offer.error_message ? `<div class="error-message">${offer.error_message}</div>` : ''}
                </div>
                <div class="offer-markets">
                    ${Object.entries(offer.market_results).map(([market, result]) => `
                        <div class="market-result status-${result.status}">
                            <span class="market-code">${market}</span>
                            <span class="market-status">${result.status}</span>
                            ${result.new_offer_id ? `<span class="market-id">${result.new_offer_id}</span>` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');
    }
    
    getStatusText(status) {
        const statusTexts = {
            'pending': 'Ожидание',
            'running': 'Выполняется',
            'paused': 'Приостановлена',
            'completed': 'Завершена',
            'failed': 'Ошибка',
            'cancelled': 'Отменена',
            'processing': 'Обработка',
            'success': 'Успешно',
            'retrying': 'Повтор',
            'skipped': 'Пропущено'
        };
        return statusTexts[status] || status;
    }
    
    updateProgress() {
        const progressBar = this.container.querySelector('.progress-fill');
        const progressText = this.container.querySelector('.progress-text');
        
        if (progressBar) {
            progressBar.style.width = `${this.sessionData.progress_percentage}%`;
        }
        
        if (progressText) {
            progressText.textContent = 
                `${this.sessionData.processed_offers} / ${this.sessionData.total_offers} офферов ` +
                `(${this.sessionData.progress_percentage.toFixed(1)}%)`;
        }
    }
    
    updateOfferStatus(offerData) {
        const offerElement = document.getElementById(`offer-${offerData.source_offer_id}`);
        if (offerElement) {
            offerElement.className = `offer-item status-${offerData.status}`;
            
            const statusBadge = offerElement.querySelector('.status-badge');
            if (statusBadge) {
                statusBadge.className = `status-badge status-${offerData.status}`;
                statusBadge.textContent = this.getStatusText(offerData.status);
            }
            
            if (offerData.new_offer_id) {
                const newIdElement = offerElement.querySelector('.new-id') || 
                    document.createElement('div');
                newIdElement.className = 'new-id';
                newIdElement.textContent = `Новый ID: ${offerData.new_offer_id}`;
                if (!offerElement.contains(newIdElement)) {
                    offerElement.querySelector('.offer-status').appendChild(newIdElement);
                }
            }
            
            if (offerData.error_message) {
                const errorElement = offerElement.querySelector('.error-message') || 
                    document.createElement('div');
                errorElement.className = 'error-message';
                errorElement.textContent = offerData.error_message;
                if (!offerElement.contains(errorElement)) {
                    offerElement.querySelector('.offer-status').appendChild(errorElement);
                }
            }
        }
    }
    
    updateStats(data) {
        const successElement = this.container.querySelector('.stat-card.success .stat-value');
        const failedElement = this.container.querySelector('.stat-card.failed .stat-value');
        const processingElement = this.container.querySelector('.stat-card.processing .stat-value');
        
        if (successElement) successElement.textContent = data.successful_offers;
        if (failedElement) failedElement.textContent = data.failed_offers;
        if (processingElement) {
            processingElement.textContent = data.total_offers - data.processed_offers;
        }
    }
    
    showError(errorData) {
        // Показать уведомление об ошибке
        this.showNotification('error', `Ошибка: ${errorData.message}`);
    }
    
    showCompletion(completionData) {
        // Показать уведомление о завершении
        this.showNotification('success', 'Перенос завершен успешно!');
        
        // Обновить интерфейс для завершенной сессии
        this.sessionData.status = 'completed';
        this.render();
    }
    
    showNotification(type, message) {
        // Реализация системы уведомлений
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }
    
    async pauseSession() {
        try {
            await ApiClient.request(`/api/v1/offer-transfer/session/${this.sessionId}/pause`, {
                method: 'POST'
            });
            this.showNotification('info', 'Сессия приостановлена');
        } catch (error) {
            this.showNotification('error', `Ошибка приостановки: ${error.message}`);
        }
    }
    
    async resumeSession() {
        try {
            await ApiClient.request(`/api/v1/offer-transfer/session/${this.sessionId}/resume`, {
                method: 'POST'
            });
            this.showNotification('info', 'Сессия возобновлена');
        } catch (error) {
            this.showNotification('error', `Ошибка возобновления: ${error.message}`);
        }
    }
    
    async cancelSession() {
        if (confirm('Вы уверены, что хотите отменить сессию?')) {
            try {
                await ApiClient.request(`/api/v1/offer-transfer/session/${this.sessionId}`, {
                    method: 'DELETE'
                });
                this.showNotification('info', 'Сессия отменена');
            } catch (error) {
                this.showNotification('error', `Ошибка отмены: ${error.message}`);
            }
        }
    }
    
    attachEventListeners() {
        // Добавить обработчики событий для кнопок
        const pauseBtn = this.container.querySelector('button[onclick*="pauseSession"]');
        const resumeBtn = this.container.querySelector('button[onclick*="resumeSession"]');
        const cancelBtn = this.container.querySelector('button[onclick*="cancelSession"]');
        
        if (pauseBtn) pauseBtn.onclick = () => this.pauseSession();
        if (resumeBtn) resumeBtn.onclick = () => this.resumeSession();
        if (cancelBtn) cancelBtn.onclick = () => this.cancelSession();
    }
    
    destroy() {
        if (this.monitor) {
            this.monitor.disconnect();
        }
    }
}
```

---

## Обработка ошибок

### Типы ошибок и их обработка

```javascript
class ErrorHandler {
    static handle(error, context = '') {
        console.error(`Error in ${context}:`, error);
        
        if (error.name === 'TypeError' && error.message.includes('fetch')) {
            this.showNetworkError();
            return;
        }
        
        if (error.status) {
            switch (error.status) {
                case 400:
                    this.showValidationError(error.data);
                    break;
                case 401:
                    this.showAuthError();
                    break;
                case 403:
                    this.showPermissionError();
                    break;
                case 429:
                    this.showRateLimitError(error.data);
                    break;
                case 500:
                    this.showServerError(error.data);
                    break;
                default:
                    this.showGenericError(error.message);
            }
        } else {
            this.showGenericError(error.message);
        }
    }
    
    static showValidationError(data) {
        const message = data.details ? 
            `Ошибка валидации: ${data.details.field} - ${data.details.error}` :
            `Ошибка валидации: ${data.message}`;
        this.showNotification('error', message);
    }
    
    static showAuthError() {
        this.showNotification('error', 'Требуется авторизация');
        
        // НЕ перенаправляем на /login, так как логин не в этом микросервисе
        // Уведомляем основное приложение или показываем инструкции
        if (window.parent && window.parent !== window) {
            // Если это iframe, уведомляем родительское окно
            window.parent.postMessage({ 
                type: 'AUTH_REQUIRED',
                message: 'JWT token required for offer transfer service'
            }, '*');
        } else {
            // Показываем инструкции пользователю
            setTimeout(() => {
                this.showNotification('info', 
                    'Пожалуйста, войдите в систему в основном приложении и обновите эту страницу');
            }, 2000);
        }
    }
    
    static showPermissionError() {
        this.showNotification('error', 'Недостаточно прав для выполнения операции');
    }
    
    static showRateLimitError(data) {
        const retryAfter = data.retry_after || 60;
        this.showNotification('warning', 
            `Превышен лимит запросов. Попробуйте через ${retryAfter} секунд`);
    }
    
    static showServerError(data) {
        const requestId = data.request_id || 'unknown';
        this.showNotification('error', 
            `Ошибка сервера. ID запроса: ${requestId}`);
    }
    
    static showNetworkError() {
        this.showNotification('error', 
            'Ошибка сети. Проверьте подключение к интернету');
    }
    
    static showGenericError(message) {
        this.showNotification('error', message || 'Произошла неизвестная ошибка');
    }
    
    static showNotification(type, message) {
        // Реализация системы уведомлений
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <span class="notification-icon">${this.getIcon(type)}</span>
                <span class="notification-message">${message}</span>
                <button class="notification-close" onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
        `;
        
        const container = document.getElementById('notifications') || this.createNotificationContainer();
        container.appendChild(notification);
        
        // Автоматическое удаление через 5 секунд
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }
    
    static getIcon(type) {
        const icons = {
            'error': '❌',
            'warning': '⚠️',
            'info': 'ℹ️',
            'success': '✅'
        };
        return icons[type] || 'ℹ️';
    }
    
    static createNotificationContainer() {
        const container = document.createElement('div');
        container.id = 'notifications';
        container.className = 'notifications-container';
        document.body.appendChild(container);
        return container;
    }
}

// Глобальный обработчик ошибок
window.addEventListener('unhandledrejection', (event) => {
    ErrorHandler.handle(event.reason, 'Unhandled Promise Rejection');
    event.preventDefault();
});

window.addEventListener('error', (event) => {
    ErrorHandler.handle(event.error, 'Global Error Handler');
});
```

---

## Примеры кода

### Полный пример интеграции

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Перенос офферов Allegro</title>
    <style>
        /* Базовые стили */
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .step { display: none; }
        .step.active { display: block; }
        
        /* Прогресс бар */
        .progress-bar { width: 100%; height: 20px; background: #f0f0f0; border-radius: 10px; overflow: hidden; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #007bff, #0056b3); transition: width 0.3s; }
        
        /* Карточки офферов */
        .offer-item { 
            border: 1px solid #ddd; 
            border-radius: 8px; 
            padding: 15px; 
            margin: 10px 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .offer-item.selected { border-color: #007bff; background: #f8f9fa; }
        .offer-item.status-success { border-left: 4px solid #28a745; }
        .offer-item.status-failed { border-left: 4px solid #dc3545; }
        .offer-item.status-processing { border-left: 4px solid #ffc107; }
        
        /* Статусы */
        .status-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-pending { background: #6c757d; color: white; }
        .status-running { background: #007bff; color: white; }
        .status-success { background: #28a745; color: white; }
        .status-failed { background: #dc3545; color: white; }
        .status-paused { background: #ffc107; color: black; }
        
        /* Уведомления */
        .notifications-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
        }
        
        .notification {
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            margin-bottom: 10px;
            max-width: 400px;
        }
        
        .notification-error { border-left: 4px solid #dc3545; }
        .notification-success { border-left: 4px solid #28a745; }
        .notification-warning { border-left: 4px solid #ffc107; }
        .notification-info { border-left: 4px solid #17a2b8; }
        
        .notification-content {
            padding: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .notification-close {
            background: none;
            border: none;
            font-size: 18px;
            cursor: pointer;
            margin-left: auto;
        }
        
        /* Кнопки */
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            margin: 5px;
        }
        
        .btn-primary { background: #007bff; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-warning { background: #ffc107; color: black; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        
        .btn:hover { opacity: 0.9; }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; }
        
        /* Сетки */
        .grid { display: grid; gap: 20px; }
        .grid-2 { grid-template-columns: 1fr 1fr; }
        .grid-3 { grid-template-columns: 1fr 1fr 1fr; }
        .grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
        
        /* Формы */
        .form-group { margin-bottom: 15px; }
        .form-label { display: block; margin-bottom: 5px; font-weight: bold; }
        .form-control {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        
        .form-control:focus {
            outline: none;
            border-color: #007bff;
            box-shadow: 0 0 0 2px rgba(0,123,255,0.25);
        }
        
        /* Чекбоксы и радио */
        .checkbox-group, .radio-group {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .checkbox-item, .radio-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        /* Таблицы */
        .table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        
        .table th, .table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        
        .table th {
            background: #f8f9fa;
            font-weight: bold;
        }
        
        .table tr:hover {
            background: #f8f9fa;
        }
        
        /* Карточки */
        .card {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 20px;
            margin: 10px 0;
        }
        
        .card-header {
            border-bottom: 1px solid #ddd;
            padding-bottom: 15px;
            margin-bottom: 15px;
        }
        
        .card-title {
            margin: 0;
            font-size: 18px;
            font-weight: bold;
        }
        
        /* Модальные окна */
        .modal {
            display: none;
            position: fixed;
            z-index: 2000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
        }
        
        .modal.active { display: flex; align-items: center; justify-content: center; }
        
        .modal-content {
            background: white;
            border-radius: 8px;
            padding: 20px;
            max-width: 500px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }
        
        /* Загрузчики */
        .spinner {
            border: 2px solid #f3f3f3;
            border-top: 2px solid #007bff;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            animation: spin 1s linear infinite;
            display: inline-block;
            margin-right: 10px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .loading-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
        }
        
        /* Адаптивность */
        @media (max-width: 768px) {
            .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; }
            .container { padding: 10px; }
            .offer-item { flex-direction: column; align-items: flex-start; gap: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Перенос офферов между аккаунтами Allegro</h1>
        
        <!-- Индикатор прогресса -->
        <div class="progress-steps">
            <div class="step-indicator">
                <span class="step-number active" id="step-1-indicator">1</span>
                <span class="step-label">Выбор аккаунтов</span>
            </div>
            <div class="step-indicator">
                <span class="step-number" id="step-2-indicator">2</span>
                <span class="step-label">Выбор офферов</span>
            </div>
            <div class="step-indicator">
                <span class="step-number" id="step-3-indicator">3</span>
                <span class="step-label">Настройка рынков</span>
            </div>
            <div class="step-indicator">
                <span class="step-number" id="step-4-indicator">4</span>
                <span class="step-label">Ценообразование</span>
            </div>
            <div class="step-indicator">
                <span class="step-number" id="step-5-indicator">5</span>
                <span class="step-label">Мониторинг</span>
            </div>
        </div>
        
        <!-- Шаг 1: Выбор аккаунтов -->
        <div id="step-1" class="step active">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Выберите аккаунты для переноса</h2>
                </div>
                
                <div class="grid grid-2">
                    <div class="form-group">
                        <label class="form-label">Исходный аккаунт</label>
                        <select id="source-account" class="form-control">
                            <option value="">Выберите аккаунт...</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label class="form-label">Целевой аккаунт</label>
                        <select id="target-account" class="form-control">
                            <option value="">Выберите аккаунт...</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-actions">
                    <button id="compare-accounts-btn" class="btn btn-primary" disabled>
                        Сравнить офферы
                    </button>
                </div>
            </div>
        </div>
        
        <!-- Шаг 2: Выбор офферов -->
        <div id="step-2" class="step">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Выберите офферы для переноса</h2>
                </div>
                
                <div class="offers-controls">
                    <div class="form-group">
                        <input type="text" id="offers-search" class="form-control" 
                               placeholder="Поиск по названию или external ID...">
                    </div>
                    
                    <div class="offers-actions">
                        <button id="select-all-offers" class="btn btn-secondary">Выбрать все</button>
                        <button id="deselect-all-offers" class="btn btn-secondary">Снять выбор</button>
                        <span class="offers-counter">
                            Выбрано: <span id="selected-count">0</span> из <span id="total-count">0</span>
                        </span>
                    </div>
                </div>
                
                <div id="offers-list" class="offers-list">
                    <!-- Офферы загружаются динамически -->
                </div>
                
                <div class="form-actions">
                    <button id="back-to-accounts" class="btn btn-secondary">Назад</button>
                    <button id="proceed-to-markets" class="btn btn-primary" disabled>
                        Настроить рынки
                    </button>
                </div>
            </div>
        </div>
        
        <!-- Шаг 3: Выбор рынков -->
        <div id="step-3" class="step">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Выберите целевые рынки</h2>
                </div>
                
                <div id="markets-list" class="checkbox-group">
                    <!-- Рынки загружаются динамически -->
                </div>
                
                <div class="form-actions">
                    <button id="back-to-offers" class="btn btn-secondary">Назад</button>
                    <button id="proceed-to-pricing" class="btn btn-primary" disabled>
                        Настроить цены
                    </button>
                </div>
            </div>
        </div>
        
        <!-- Шаг 4: Ценообразование -->
        <div id="step-4" class="step">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Настройка правил ценообразования</h2>
                </div>
                
                <div id="pricing-rules">
                    <!-- Правила ценообразования для каждого рынка -->
                </div>
                
                <div class="pricing-preview">
                    <h3>Предварительный расчет</h3>
                    <button id="preview-pricing-btn" class="btn btn-secondary">
                        Рассчитать цены
                    </button>
                    <div id="pricing-preview-results"></div>
                </div>
                
                <div class="template-section">
                    <h3>Сохранить как шаблон</h3>
                    <div class="form-group">
                        <input type="text" id="template-name" class="form-control" 
                               placeholder="Название шаблона (необязательно)">
                    </div>
                </div>
                
                <div class="form-actions">
                    <button id="back-to-markets" class="btn btn-secondary">Назад</button>
                    <button id="start-transfer-btn" class="btn btn-success">
                        Запустить перенос
                    </button>
                </div>
            </div>
        </div>
        
        <!-- Шаг 5: Мониторинг -->
        <div id="step-5" class="step">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Мониторинг переноса</h2>
                </div>
                
                <div id="session-monitor">
                    <!-- Компонент мониторинга сессии -->
                </div>
            </div>
        </div>
    </div>
    
    <!-- Модальные окна -->
    <div id="loading-modal" class="modal">
        <div class="modal-content">
            <div style="text-align: center;">
                <div class="spinner"></div>
                <span id="loading-text">Загрузка...</span>
            </div>
        </div>
    </div>
    
    <script>
        // Главный класс приложения
        class OfferTransferApp {
            constructor() {
                this.workflow = new OfferTransferWorkflow();
                this.currentStep = 1;
                this.init();
            }
            
            async init() {
                // Проверить наличие JWT токена
                if (!AuthService.isAuthenticated()) {
                    this.showAuthWarning();
                    return;
                }
                
                // Загрузить аккаунты
                await this.loadAccounts();
                
                // Настроить обработчики событий
                this.setupEventListeners();
            }
            
            showAuthWarning() {
                const container = document.querySelector('.container');
                container.innerHTML = `
                    <div class="card">
                        <div class="card-header">
                            <h2 class="card-title">⚠️ Требуется авторизация</h2>
                        </div>
                        <div class="card-body">
                            <p>Для использования сервиса переноса офферов необходим JWT токен.</p>
                            <p><strong>Микросервис не предоставляет методы для логина.</strong></p>
                            <p>Пожалуйста:</p>
                            <ol>
                                <li>Войдите в систему в основном приложении</li>
                                <li>Убедитесь, что JWT токен передается в localStorage или через postMessage</li>
                                <li>Обновите эту страницу</li>
                            </ol>
                            <button class="btn btn-primary" onclick="location.reload()">
                                Обновить страницу
                            </button>
                        </div>
                    </div>
                `;
            }
            
            async loadAccounts() {
                try {
                    this.showLoading('Загрузка аккаунтов...');
                    const accounts = await this.workflow.loadAccounts();
                    this.populateAccountSelects(accounts);
                } catch (error) {
                    ErrorHandler.handle(error, 'loadAccounts');
                } finally {
                    this.hideLoading();
                }
            }
            
            populateAccountSelects(accounts) {
                const sourceSelect = document.getElementById('source-account');
                const targetSelect = document.getElementById('target-account');
                
                // Очистить существующие опции
                sourceSelect.innerHTML = '<option value="">Выберите аккаунт...</option>';
                targetSelect.innerHTML = '<option value="">Выберите аккаунт...</option>';
                
                accounts.forEach(account => {
                    const option = document.createElement('option');
                    option.value = account.id;
                    option.textContent = `${account.account_name} (${account.is_active ? 'активен' : 'неактивен'})`;
                    option.disabled = !account.is_active;
                    
                    sourceSelect.appendChild(option.cloneNode(true));
                    targetSelect.appendChild(option);
                });
            }
            
            setupEventListeners() {
                // Шаг 1: Выбор аккаунтов
                const sourceSelect = document.getElementById('source-account');
                const targetSelect = document.getElementById('target-account');
                const compareBtn = document.getElementById('compare-accounts-btn');
                
                const checkAccountsSelected = () => {
                    const sourceSelected = sourceSelect.value !== '';
                    const targetSelected = targetSelect.value !== '';
                    const differentAccounts = sourceSelect.value !== targetSelect.value;
                    
                    compareBtn.disabled = !(sourceSelected && targetSelected && differentAccounts);
                };
                
                sourceSelect.addEventListener('change', checkAccountsSelected);
                targetSelect.addEventListener('change', checkAccountsSelected);
                
                compareBtn.addEventListener('click', () => this.compareAccounts());
                
                // Шаг 2: Выбор офферов
                document.getElementById('offers-search').addEventListener('input', (e) => {
                    this.filterOffers(e.target.value);
                });
                
                document.getElementById('select-all-offers').addEventListener('click', () => {
                    this.selectAllOffers(true);
                });
                
                document.getElementById('deselect-all-offers').addEventListener('click', () => {
                    this.selectAllOffers(false);
                });
                
                document.getElementById('back-to-accounts').addEventListener('click', () => {
                    this.goToStep(1);
                });
                
                document.getElementById('proceed-to-markets').addEventListener('click', () => {
                    this.proceedToMarkets();
                });
                
                // Шаг 3: Выбор рынков
                document.getElementById('back-to-offers').addEventListener('click', () => {
                    this.goToStep(2);
                });
                
                document.getElementById('proceed-to-pricing').addEventListener('click', () => {
                    this.proceedToPricing();
                });
                
                // Шаг 4: Ценообразование
                document.getElementById('back-to-markets').addEventListener('click', () => {
                    this.goToStep(3);
                });
                
                document.getElementById('preview-pricing-btn').addEventListener('click', () => {
                    this.previewPricing();
                });
                
                document.getElementById('start-transfer-btn').addEventListener('click', () => {
                    this.startTransfer();
                });
            }
            
            async compareAccounts() {
                try {
                    this.showLoading('Сравнение офферов...');
                    
                    const sourceTokenId = document.getElementById('source-account').value;
                    const targetTokenId = document.getElementById('target-account').value;
                    
                    const comparison = await this.workflow.compareOffers(sourceTokenId, targetTokenId);
                    
                    this.workflow.data.sourceAccount = { id: sourceTokenId };
                    this.workflow.data.targetAccount = { id: targetTokenId };
                    
                    this.populateOffersList(comparison.available_offers);
                    this.goToStep(2);
                    
                } catch (error) {
                    ErrorHandler.handle(error, 'compareAccounts');
                } finally {
                    this.hideLoading();
                }
            }
            
            populateOffersList(offers) {
                const offersList = document.getElementById('offers-list');
                const totalCount = document.getElementById('total-count');
                
                totalCount.textContent = offers.length;
                
                offersList.innerHTML = offers.map(offer => `
                    <div class="offer-item" data-offer-id="${offer.id}">
                        <div class="offer-checkbox">
                            <input type="checkbox" id="offer-${offer.id}" onchange="app.updateSelectedCount()">
                        </div>
                        <div class="offer-info">
                            <div class="offer-image">
                                ${offer.images.length > 0 ? 
                                    `<img src="${offer.images[0]}" alt="${offer.name}" style="width: 60px; height: 60px; object-fit: cover;">` :
                                    '<div style="width: 60px; height: 60px; background: #f0f0f0; display: flex; align-items: center; justify-content: center;">Нет фото</div>'
                                }
                            </div>
                            <div class="offer-details">
                                <h4>${offer.name}</h4>
                                <p>ID: ${offer.id}</p>
                                <p>External ID: ${offer.external_id}</p>
                                <p>Категория: ${offer.category}</p>
                                <p>Цена: ${offer.price.amount} ${offer.price.currency}</p>
                                <p>Остаток: ${offer.stock}</p>
                            </div>
                        </div>
                    </div>
                `).join('');
                
                this.updateSelectedCount();
            }
            
            filterOffers(searchTerm) {
                const offers = document.querySelectorAll('.offer-item');
                const term = searchTerm.toLowerCase();
                
                offers.forEach(offer => {
                    const text = offer.textContent.toLowerCase();
                    offer.style.display = text.includes(term) ? 'flex' : 'none';
                });
            }
            
            selectAllOffers(select) {
                const checkboxes = document.querySelectorAll('#offers-list input[type="checkbox"]');
                checkboxes.forEach(checkbox => {
                    const offer = checkbox.closest('.offer-item');
                    if (offer.style.display !== 'none') {
                        checkbox.checked = select;
                    }
                });
                this.updateSelectedCount();
            }
            
            updateSelectedCount() {
                const selectedCheckboxes = document.querySelectorAll('#offers-list input[type="checkbox"]:checked');
                const selectedCount = document.getElementById('selected-count');
                const proceedBtn = document.getElementById('proceed-to-markets');
                
                selectedCount.textContent = selectedCheckboxes.length;
                proceedBtn.disabled = selectedCheckboxes.length === 0;
                
                // Обновить данные workflow
                this.workflow.data.selectedOffers = Array.from(selectedCheckboxes).map(checkbox => {
                    const offerId = checkbox.id.replace('offer-', '');
                    return this.workflow.data.availableOffers.find(o => o.id === offerId);
                }).filter(Boolean);
            }
            
            async proceedToMarkets() {
                try {
                    this.showLoading('Загрузка рынков...');
                    const markets = await this.workflow.loadMarkets();
                    this.populateMarketsList(markets);
                    this.goToStep(3);
                } catch (error) {
                    ErrorHandler.handle(error, 'proceedToMarkets');
                } finally {
                    this.hideLoading();
                }
            }
            
            populateMarketsList(markets) {
                const marketsList = document.getElementById('markets-list');
                
                marketsList.innerHTML = markets.map(market => `
                    <div class="checkbox-item">
                        <input type="checkbox" id="market-${market.code}" value="${market.code}" 
                               onchange="app.updateSelectedMarkets()">
                        <label for="market-${market.code}">
                            <img src="${market.flag_url}" alt="${market.code}" style="width: 20px; height: 15px; margin-right: 8px;">
                            ${market.name} (${market.currency})
                        </label>
                    </div>
                `).join('');
            }
            
            updateSelectedMarkets() {
                const selectedMarkets = Array.from(document.querySelectorAll('#markets-list input[type="checkbox"]:checked'))
                    .map(checkbox => checkbox.value);
                
                const proceedBtn = document.getElementById('proceed-to-pricing');
                proceedBtn.disabled = selectedMarkets.length === 0;
                
                this.workflow.data.selectedMarkets = selectedMarkets;
            }
            
            proceedToPricing() {
                this.setupPricingRules();
                this.goToStep(4);
            }
            
            setupPricingRules() {
                const pricingRules = document.getElementById('pricing-rules');
                const selectedMarkets = this.workflow.data.selectedMarkets;
                
                pricingRules.innerHTML = selectedMarkets.map(marketCode => `
                    <div class="pricing-rule-card card">
                        <h4>Правило для рынка ${marketCode}</h4>
                        <div class="form-group">
                            <label class="form-label">Тип правила</label>
                            <select class="form-control" id="rule-type-${marketCode}" 
                                    onchange="app.updatePricingRuleType('${marketCode}')">
                                <option value="multiply">Умножить на коэффициент</option>
                                <option value="add">Добавить фиксированную сумму</option>
                                <option value="convert_with_markup">Конвертировать с наценкой (%)</option>
                            </select>
                        </div>
                        <div id="rule-params-${marketCode}" class="rule-parameters">
                            <div class="form-group">
                                <label class="form-label">Коэффициент</label>
                                <input type="number" class="form-control" id="multiplier-${marketCode}" 
                                       value="1.0" step="0.1" min="0.1">
                            </div>
                        </div>
                    </div>
                `).join('');
            }
            
            updatePricingRuleType(marketCode) {
                const ruleType = document.getElementById(`rule-type-${marketCode}`).value;
                const paramsContainer = document.getElementById(`rule-params-${marketCode}`);
                
                let paramsHtml = '';
                switch (ruleType) {
                    case 'multiply':
                        paramsHtml = `
                            <div class="form-group">
                                <label class="form-label">Коэффициент</label>
                                <input type="number" class="form-control" id="multiplier-${marketCode}" 
                                       value="1.0" step="0.1" min="0.1">
                            </div>
                        `;
                        break;
                    case 'add':
                        paramsHtml = `
                            <div class="form-group">
                                <label class="form-label">Добавить сумму</label>
                                <input type="number" class="form-control" id="add-amount-${marketCode}" 
                                       value="0" step="0.01" min="0">
                            </div>
                        `;
                        break;
                    case 'convert_with_markup':
                        paramsHtml = `
                            <div class="form-group">
                                <label class="form-label">Наценка (%)</label>
                                <input type="number" class="form-control" id="markup-percent-${marketCode}" 
                                       value="0" step="1" min="0" max="1000">
                            </div>
                        `;
                        break;
                }
                
                paramsContainer.innerHTML = paramsHtml;
            }
            
            async previewPricing() {
                try {
                    this.showLoading('Расчет цен...');
                    
                    const pricingRules = this.getPricingRules();
                    const selectedOffers = this.workflow.data.selectedOffers.slice(0, 5); // Показать только первые 5
                    
                    const preview = await this.workflow.previewPricing(
                        selectedOffers,
                        this.workflow.data.selectedMarkets,
                        pricingRules
                    );
                    
                    this.displayPricingPreview(preview);
                    
                } catch (error) {
                    ErrorHandler.handle(error, 'previewPricing');
                } finally {
                    this.hideLoading();
                }
            }
            
            getPricingRules() {
                return this.workflow.data.selectedMarkets.map(marketCode => {
                    const ruleType = document.getElementById(`rule-type-${marketCode}`).value;
                    const rule = {
                        market_code: marketCode,
                        type: ruleType
                    };
                    
                    switch (ruleType) {
                        case 'multiply':
                            rule.multiplier = parseFloat(document.getElementById(`multiplier-${marketCode}`).value);
                            break;
                        case 'add':
                            rule.add_amount = parseFloat(document.getElementById(`add-amount-${marketCode}`).value);
                            break;
                        case 'convert_with_markup':
                            rule.markup_percent = parseFloat(document.getElementById(`markup-percent-${marketCode}`).value);
                            break;
                    }
                    
                    return rule;
                });
            }
            
            displayPricingPreview(preview) {
                const previewResults = document.getElementById('pricing-preview-results');
                
                previewResults.innerHTML = `
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Оффер</th>
                                <th>Исходная цена</th>
                                ${this.workflow.data.selectedMarkets.map(market => `<th>${market}</th>`).join('')}
                            </tr>
                        </thead>
                        <tbody>
                            ${preview.previews.map(p => `
                                <tr>
                                    <td>${this.workflow.data.selectedOffers.find(o => o.id === p.offer_id)?.name || p.offer_id}</td>
                                    <td>${p.original_price.amount} ${p.original_price.currency}</td>
                                    ${this.workflow.data.selectedMarkets.map(market => {
                                        const marketPrice = p.market_prices[market];
                                        return `<td>${marketPrice ? `${marketPrice.amount} ${marketPrice.currency}` : 'N/A'}</td>`;
                                    }).join('')}
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                    ${preview.previews.length < this.workflow.data.selectedOffers.length ? 
                        `<p><em>Показано первые ${preview.previews.length} из ${this.workflow.data.selectedOffers.length} офферов</em></p>` : 
                        ''
                    }
                `;
            }
            
            async startTransfer() {
                try {
                    if (!confirm(`Запустить перенос ${this.workflow.data.selectedOffers.length} офферов на ${this.workflow.data.selectedMarkets.length} рынков?`)) {
                        return;
                    }
                    
                    this.showLoading('Запуск переноса...');
                    
                    // Подготовить данные
                    this.workflow.data.pricingRules = this.getPricingRules();
                    
                    // Запустить перенос
                    const sessionData = await this.workflow.startTransfer();
                    
                    // Перейти к мониторингу
                    this.startSessionMonitoring(sessionData);
                    this.goToStep(5);
                    
                } catch (error) {
                    ErrorHandler.handle(error, 'startTransfer');
                } finally {
                    this.hideLoading();
                }
            }
            
            startSessionMonitoring(sessionData) {
                const monitorContainer = document.getElementById('session-monitor');
                
                // Создать компонент мониторинга
                this.sessionMonitor = new SessionMonitorWidget('session-monitor', sessionData.id);
                this.sessionMonitor.init();
            }
            
            goToStep(stepNumber) {
                // Скрыть все шаги
                document.querySelectorAll('.step').forEach(step => {
                    step.classList.remove('active');
                });
                
                // Показать текущий шаг
                document.getElementById(`step-${stepNumber}`).classList.add('active');
                
                // Обновить индикаторы
                document.querySelectorAll('.step-number').forEach((indicator, index) => {
                    indicator.classList.toggle('active', index + 1 <= stepNumber);
                });
                
                this.currentStep = stepNumber;
            }
            
            showLoading(text = 'Загрузка...') {
                document.getElementById('loading-text').textContent = text;
                document.getElementById('loading-modal').classList.add('active');
            }
            
            hideLoading() {
                document.getElementById('loading-modal').classList.remove('active');
            }
        }
        
        // Запустить приложение
        let app;
        document.addEventListener('DOMContentLoaded', () => {
            app = new OfferTransferApp();
        });
    </script>
</body>
</html>
```

---

## Рекомендации по UX

### 1. Пользовательский интерфейс

- **Прогрессивное раскрытие**: Показывайте информацию поэтапно
- **Визуальная иерархия**: Используйте размеры шрифтов и цвета для выделения важного
- **Состояния загрузки**: Всегда показывайте прогресс длительных операций
- **Обратная связь**: Немедленно реагируйте на действия пользователя

### 2. Обработка ошибок

- **Понятные сообщения**: Объясняйте ошибки простым языком
- **Предложения решений**: Указывайте, как исправить проблему
- **Graceful degradation**: Приложение должно работать даже при частичных сбоях
- **Retry механизмы**: Автоматически повторяйте неудачные операции

### 3. Производительность

- **Виртуализация списков**: Для больших списков офферов
- **Ленивая загрузка**: Загружайте данные по мере необходимости
- **Кэширование**: Сохраняйте часто используемые данные
- **Оптимистичные обновления**: Обновляйте UI до получения ответа сервера

### 4. Доступность

- **Семантическая разметка**: Используйте правильные HTML элементы
- **Альтернативный текст**: Для всех изображений и иконок
- **Клавиатурная навигация**: Все функции доступны с клавиатуры
- **Цветовая контрастность**: Соблюдайте стандарты WCAG

### 5. Мобильная адаптация

- **Отзывчивый дизайн**: Адаптация под разные размеры экранов
- **Touch-friendly**: Кнопки и элементы управления подходящего размера
- **Оптимизация трафика**: Минимизируйте объем передаваемых данных
- **Оффлайн поддержка**: Базовая функциональность без интернета

---

## Заключение

Данная документация предоставляет полную информацию для создания фронтенд интерфейса системы переноса офферов. Все API эндпоинты, модели данных, примеры кода и рекомендации по UX включены в этот единый справочный файл.

### Ключевые особенности системы:

1. **Асинхронная обработка** через Celery
2. **Реальное время** через WebSocket
3. **Пакетная обработка** тысяч офферов
4. **Возобновляемые сессии**
5. **Система шаблонов**
6. **Комплексный мониторинг**
7. **Обработка ошибок**

### Следующие шаги:

1. Настроить базовую структуру проекта
2. Реализовать аутентификацию
3. Создать компоненты по шагам
4. Интегрировать WebSocket мониторинг
5. Добавить обработку ошибок
6. Провести тестирование
7. Оптимизировать производительность

Удачи в разработке! 🚀
