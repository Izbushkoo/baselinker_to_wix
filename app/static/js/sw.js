const CACHE_NAME = 'tg-catalog-v1';
const STATIC_CACHE = 'static-v1';
const API_CACHE = 'api-v1';

// Список статических ресурсов для кэширования
const STATIC_RESOURCES = [
    '/static/js/tg_catalog.js',
    '/static/css/styles.css',
    'https://telegram.org/js/telegram-web-app.js'
];

// Установка Service Worker
self.addEventListener('install', (event) => {
    event.waitUntil(
        Promise.all([
            caches.open(STATIC_CACHE).then((cache) => {
                return cache.addAll(STATIC_RESOURCES);
            }),
            caches.open(API_CACHE)
        ])
    );
});

// Активация и очистка старых кэшей
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== STATIC_CACHE && cacheName !== API_CACHE) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

// Стратегия кэширования: Network First для API, Cache First для статики
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    
    // Для API-запросов используем Network First
    if (url.pathname.startsWith('/tg/catalog')) {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    // Клонируем ответ, так как он может быть использован только один раз
                    const responseClone = response.clone();
                    
                    // Кэшируем успешные ответы
                    if (response.ok) {
                        caches.open(API_CACHE).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    
                    return response;
                })
                .catch(() => {
                    // Если сеть недоступна, пробуем взять из кэша
                    return caches.match(event.request);
                })
        );
        return;
    }
    
    // Для статических ресурсов используем Cache First
    if (STATIC_RESOURCES.some(resource => url.pathname.endsWith(resource))) {
        event.respondWith(
            caches.match(event.request)
                .then((response) => {
                    if (response) {
                        return response;
                    }
                    return fetch(event.request).then((response) => {
                        const responseClone = response.clone();
                        caches.open(STATIC_CACHE).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                        return response;
                    });
                })
        );
        return;
    }
}); 