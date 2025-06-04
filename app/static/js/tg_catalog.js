import { saveImageToDB, getImageFromDB } from './image_cache.js';

function clearImageCacheDB() {
    const dbName = 'image_cache';
    const req = indexedDB.deleteDatabase(dbName);
    req.onsuccess = function() {
        console.log('IndexedDB image_cache очищена');
    };
    req.onerror = function(e) {
        console.warn('Ошибка очистки image_cache:', e);
    };
    req.onblocked = function() {
        console.warn('Очистка image_cache заблокирована');
    };
}

// Ожидаем загрузки DOM и Telegram WebApp
document.addEventListener('DOMContentLoaded', function() {
    // clearImageCacheDB(); // Очищаем кэш изображений при загрузке страницы

    // В начале скрипта (внутри DOMContentLoaded) добавьте:

    window.toggleMenu = toggleMenu;
    window.goTo = goTo;
    window.copyToClipboard = copyToClipboard;
    window.toggleDetails = toggleDetails;
    window.showStockModal = showStockModal;
    window.closeStockModal = closeStockModal;
    window.confirmStockModal = confirmStockModal;
    window.deleteProduct = deleteProduct;

    // Инициализация Telegram WebApp
    let tg;
    try {
        tg = window.Telegram.WebApp;
        if (!tg) {
            console.error('Telegram WebApp не инициализирован');
            return;
        }
    } catch (error) {
        console.error('Ошибка при инициализации Telegram WebApp:', error);
        return;
    }
    
    // Расширяем окно на весь экран
    tg.expand();

    // Показываем кнопку "Назад"
    tg.BackButton.show();
    
    // Обработчик нажатия кнопки "Назад"
    tg.BackButton.onClick(() => {
        window.history.back();
    });

    // Инициализация переменных
    let currentPage = 1;
    let isLoading = false;
    let hasMore = true;
    let totalPages = 1;
    let cacheTimeout = 5 * 60 * 1000; // 5 минут

    // Функция для работы с кэшем фильтров (только параметры, не товары)
    const filterCache = {
        set: (filters) => {
            sessionStorage.setItem('catalog_filters', JSON.stringify(filters));
        },
        get: () => {
            const saved = sessionStorage.getItem('catalog_filters');
            return saved ? JSON.parse(saved) : {};
        },
        clear: () => {
            sessionStorage.removeItem('catalog_filters');
        }
    };

    // Функция для очистки кеша при операциях с товарами
    function clearCache() {
        filterCache.clear();
    }

    // Инициализация пагинации из data-атрибутов
    const paginationData = document.getElementById('paginationData');
    if (paginationData) {
        currentPage = parseInt(paginationData.dataset.currentPage) || 1;
        totalPages = parseInt(paginationData.dataset.totalPages) || 1;
        renderPagination();
    }

    function renderPagination() {
        const pagination = document.getElementById('paginationBottom');
        if (!pagination) return;
        
        pagination.innerHTML = '';
        
        const prevBtn = document.createElement('button');
        prevBtn.className = 'pagination-btn';
        prevBtn.textContent = 'Назад';
        prevBtn.disabled = currentPage <= 1;
        prevBtn.onclick = () => loadProducts(currentPage - 1, false, true);
        
        const nextBtn = document.createElement('button');
        nextBtn.className = 'pagination-btn';
        nextBtn.textContent = 'Вперед';
        nextBtn.disabled = currentPage >= totalPages;
        nextBtn.onclick = () => loadProducts(currentPage + 1, false, true);
        
        const info = document.createElement('span');
        info.className = 'pagination-info';
        info.textContent = `Страница ${currentPage} из ${totalPages}`;
        
        pagination.appendChild(prevBtn);
        pagination.appendChild(info);
        pagination.appendChild(nextBtn);
    }

    function isValidStockFilter(val) {
        if (!val) return false;
        return val.match(/^[0-9]+$/);
    }

    function getFilters() {
        const filters = {};
        const search = document.getElementById('searchInput').value.trim();
        const stock_filter = document.getElementById('stockFilter').value.trim();
        const sort_order = document.getElementById('sortOrder').value;
        const page_size = document.getElementById('pageSize').value;

        if (search) filters.search = search;
        if (stock_filter && isValidStockFilter(stock_filter)) {
            filters.stock_filter = parseInt(stock_filter);
        } 

        if (sort_order) filters.sort_order = sort_order;
        if (page_size) filters.page_size = page_size;
        return filters;
    }

    function handleFilterChange() {
        const stockInput = document.getElementById('stockFilter');
        const valRaw = stockInput.value;
        const val = valRaw.trim();
        if (val && !isValidStockFilter(val)) {
            tg.showAlert('Введите только целое положительное число для фильтра по остатку');
            stockInput.focus();
            return;
        }
        const filters = getFilters();
        currentPage = 1;
        hasMore = true;
        filterCache.set(filters);
        loadProducts(1, false);
        const filtersPanel = document.getElementById('filtersPanel');
        if (filtersPanel && filtersPanel.classList.contains('active')) {
            toggleFilters();
        }
    }

    function toggleFilters() {
        initSearchClear();
        const filtersPanel = document.getElementById('filtersPanel');
        const content = document.getElementById('content');
        const btn = document.getElementById('filtersToggleBtn');
        
        filtersPanel.classList.toggle('active');
        content.classList.toggle('with-filters');
        btn.classList.toggle('active');

        const pagination = document.getElementById('paginationBottom');
        const productsList = document.getElementById('productsList');
        if (filtersPanel.classList.contains('active')) {
            if (pagination) pagination.style.display = 'none';
        } else {
            if (pagination && productsList && productsList.children.length > 0) {
                pagination.style.display = '';
            }
        }
    }

    function initSearchClear() {
        const searchInput = document.getElementById('searchInput');
        const clearSearchBtn = document.getElementById('clearSearchBtn');

        if (searchInput && clearSearchBtn) {
            searchInput.addEventListener('input', () => {
                clearSearchBtn.style.display = searchInput.value.length > 0 ? 'flex' : 'none';
            });

            clearSearchBtn.addEventListener('click', (e) => {
                e.preventDefault();
                searchInput.value = '';
                clearSearchBtn.style.display = 'none';
                searchInput.focus();
            });

            if (searchInput.value.length > 0) {
                clearSearchBtn.style.display = 'flex';
            }
        }
    }

    function initStockClear() {
        const stockInput = document.getElementById('stockFilter');
        const clearStockBtn = document.getElementById('clearStockBtn');
        if (stockInput && clearStockBtn) {
            stockInput.addEventListener('input', () => {
                clearStockBtn.style.display = stockInput.value.length > 0 ? 'flex' : 'none';
            });
            clearStockBtn.addEventListener('click', (e) => {
                e.preventDefault();
                stockInput.value = '';
                clearStockBtn.style.display = 'none';
                stockInput.focus();
                updateResetFiltersBtnVisibility();
            });
            if (stockInput.value.length > 0) {
                clearStockBtn.style.display = 'flex';
            } else {
                clearStockBtn.style.display = 'none';
            }
        }
    }

    function updateResetFiltersBtnVisibility() {
        const search = document.getElementById('searchInput').value.trim();
        const stock = document.getElementById('stockFilter').value.trim();
        const sort = document.getElementById('sortOrder').value;
        const pageSize = document.getElementById('pageSize').value;
        const btn = document.querySelector('.btn-reset');
        const buttonRow = document.querySelector('.button-row');
        if (!btn) return;
        // дефолтные значения: все пусто, pageSize = '50'
        if (search || stock || sort || pageSize !== '50') {
            btn.style.display = '';
            if (buttonRow) buttonRow.classList.add('has-reset');
        } else {
            btn.style.display = 'none';
            if (buttonRow) buttonRow.classList.remove('has-reset');
        }
    }

    function clearAllFiltersOnLoad() {
        const searchInput = document.getElementById('searchInput');
        const stockFilter = document.getElementById('stockFilter');
        const sortOrder = document.getElementById('sortOrder');
        const pageSize = document.getElementById('pageSize');
        const clearSearchBtn = document.getElementById('clearSearchBtn');

        if (searchInput) searchInput.value = '';
        if (stockFilter) stockFilter.value = '';
        if (sortOrder) sortOrder.value = '';
        if (pageSize) pageSize.value = '50';
        if (clearSearchBtn) clearSearchBtn.style.display = 'none';
        updateResetFiltersBtnVisibility();
    }

    function toggleMenu() {
        const menu = document.getElementById('menu');
        menu.classList.toggle('active');
    }

    function goTo(page) {
        if (page === 'warehouse') {
            window.location.href = '/tg/catalog';
            return;
        }
        if (window.Telegram && Telegram.WebApp) {
            Telegram.WebApp.sendData(JSON.stringify({action: 'navigate', page: page}));
        } else {
            window.location.href = '/' + page;
        }
    }

    // Инициализация обработчиков событий
    document.getElementById('applyFiltersBtn').addEventListener('click', handleFilterChange);
    document.getElementById('filtersToggleBtn').addEventListener('click', toggleFilters);
    
    // Закрытие меню при клике вне
    document.addEventListener('click', function(e) {
        const menu = document.getElementById('menu');
        const burger = document.querySelector('.burger');
        if (!menu.contains(e.target) && !burger.contains(e.target)) {
            menu.classList.remove('active');
        }
        // --- Закрытие фильтров при клике вне панели фильтров и кнопки фильтров ---
        const filtersPanel = document.getElementById('filtersPanel');
        const filtersBtn = document.getElementById('filtersToggleBtn');
        if (
            filtersPanel &&
            filtersPanel.classList.contains('active') &&
            !filtersPanel.contains(e.target) &&
            !filtersBtn.contains(e.target)
        ) {
            toggleFilters();
        }
        // --- Закрытие деталей по складам при клике вне карточки ---
        const expandedCards = document.querySelectorAll('.tg-product-card.expanded');
        expandedCards.forEach(card => {
            if (!card.contains(e.target)) {
                card.classList.remove('expanded');
                const toggleText = card.querySelector('.toggle-text');
                if (toggleText) toggleText.textContent = 'Детали по складам ▼';
            }
        });
    });

    // Инициализация при загрузке
    initSearchClear();
    initStockClear();
    applyFiltersFromStorage(); // Восстанавливаем фильтры при загрузке
    
    // Загрузка первой страницы товаров
    loadProducts(1, false);

    // Обработка сообщений от Telegram
    tg.onEvent('message', function(event) {
        console.log('Received message:', event);
    });

    // --- Функции для карточек товара ---
    function copyToClipboard(element) {
        if (element.classList.contains('copying')) return;
        const text = element.getAttribute('data-sku');
        const skuBlock = element.closest('.tg-product-sku');
        navigator.clipboard.writeText(text).then(() => {
            const originalText = element.textContent;
            if (skuBlock) skuBlock.classList.add('copied');
            element.textContent = 'Скопировано!';
            element.style.color = '#22c55e';
            element.style.background = 'none';
            element.style.pointerEvents = 'none';
            element.classList.add('copying');
            setTimeout(() => {
                element.textContent = originalText;
                element.style.color = '';
                element.style.background = '';
                element.style.pointerEvents = '';
                element.classList.remove('copying');
                if (skuBlock) skuBlock.classList.remove('copied');
            }, 1000);
        });
    }

    function toggleDetails(card) {
        card.classList.toggle('expanded');
        const toggleText = card.querySelector('.toggle-text');
        if (card.classList.contains('expanded')) {
            toggleText.textContent = 'Детали по складам ▲';
        } else {
            toggleText.textContent = 'Детали по складам ▼';
        }
    }

    function findStockItemByWarehouse(card, warehouse) {
        const items = card.querySelectorAll('.stock-item');
        for (const item of items) {
            const nameDiv = item.querySelector('.stock-item-name');
            if (nameDiv && nameDiv.textContent.trim() === warehouse) {
                return item;
            }
        }
        return null;
    }

    async function updateStockDisplay(cardOrSku, warehouse, delta) {
        let cards = [];
        if (typeof cardOrSku === 'string') {
            cards = Array.from(document.querySelectorAll(`.tg-product-card[data-sku="${cardOrSku}"]`));
        } else if (cardOrSku) {
            cards = [cardOrSku];
        }
        if (!cards.length) return;
        for (const card of cards) {
            let stockItem = findStockItemByWarehouse(card, warehouse);
            if (!stockItem) {
                const details = card.querySelector('.tg-product-details');
                if (details) {
                    stockItem = document.createElement('div');
                    stockItem.className = 'stock-item';
                    stockItem.innerHTML = `
                        <div class="stock-item-name">${warehouse}</div>
                        <div class="stock-item-qty">0 шт.</div>
                    `;
                    details.appendChild(stockItem);
                }
            }
            if (stockItem) {
                const qtyElement = stockItem.querySelector('.stock-item-qty');
                const currentQty = parseInt((qtyElement.textContent || '0').replace(/[^\d-]/g, ''));
                const newQty = currentQty + delta;
                qtyElement.textContent = `${newQty} шт.`;
                qtyElement.className = 'stock-item-qty ' + (newQty > 5 ? 'green' : newQty > 0 ? 'yellow' : 'red');
                qtyElement.style.transition = 'background 0.3s';
                qtyElement.style.background = '#fef08a';
                setTimeout(() => { qtyElement.style.background = ''; }, 400);
            }
            const totalQtyElement = card.querySelector('.tg-product-qty');
            if (totalQtyElement) {
                const currentTotal = parseInt((totalQtyElement.textContent || '0').replace(/[^\d-]/g, ''));
                const newTotal = currentTotal + delta;
                totalQtyElement.textContent = `${newTotal} шт.`;
                totalQtyElement.className = 'tg-product-qty ' + (newTotal > 5 ? 'green' : newTotal > 0 ? 'yellow' : 'red');
                totalQtyElement.style.transition = 'background 0.3s';
                totalQtyElement.style.background = '#fef08a';
                setTimeout(() => { totalQtyElement.style.background = ''; }, 400);
            }
            const statusElement = card.querySelector('.tg-product-status');
            if (statusElement && totalQtyElement) {
                const newTotal = parseInt((totalQtyElement.textContent || '0').replace(/[^\d-]/g, ''));
                if (newTotal > 5) {
                    statusElement.textContent = 'В наличии';
                    statusElement.className = 'tg-product-status in';
                } else if (newTotal > 0) {
                    statusElement.textContent = 'Мало';
                    statusElement.className = 'tg-product-status low';
                } else {
                    statusElement.textContent = 'Нет в наличии';
                    statusElement.className = 'tg-product-status out';
                }
                statusElement.style.transition = 'background 0.3s';
                statusElement.style.background = '#fef08a';
                setTimeout(() => { statusElement.style.background = ''; }, 400);
            }
        }
    }

    async function addToStock(sku, warehouse, quantity) {
        try {
            const response = await fetch('/api/warehouse/add/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sku, warehouse, quantity })
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Ошибка при пополнении остатков');
            }
            const data = await response.json();
            await updateStockDisplay(sku, warehouse, quantity);
            clearCache();
            tg.showAlert(data.message || 'Остатки успешно пополнены');
            return true;
        } catch (error) {
            console.error('Error:', error);
            tg.showAlert(error.message || 'Произошла ошибка при пополнении остатков');
            return false;
        }
    }

    async function removeFromStock(sku, warehouse, quantity) {
        try {
            const response = await fetch('/api/warehouse/remove/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sku, warehouse, quantity })
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Ошибка при списании остатков');
            }
            const data = await response.json();
            await updateStockDisplay(sku, warehouse, -quantity);
            clearCache();
            tg.showAlert(data.message || 'Остатки успешно списаны');
            return true;
        } catch (error) {
            console.error('Error:', error);
            tg.showAlert(error.message || 'Произошла ошибка при списании остатков');
            return false;
        }
    }

    async function updateStock(sku, warehouse, delta) {
        const quantity = Math.abs(delta);
        if (delta > 0) {
            return await addToStock(sku, warehouse, quantity);
        } else {
            return await removeFromStock(sku, warehouse, quantity);
        }
    }

    async function deleteProduct(sku, name) {
        const confirmed = await new Promise(resolve => {
            tg.showConfirm(`Вы уверены, что хотите удалить товар "${name}"?`, resolve);
        });
        if (!confirmed) return;
        try {
            const response = await fetch(`/api/products/${sku}`, { method: 'DELETE' });
            if (!response.ok) {
                const errorData = await response.json();
                tg.showAlert(errorData.detail || 'Ошибка при удалении товара');
                return;
            }
            const card = document.querySelector(`.tg-product-card[data-sku="${sku}"]`);
            if (card) card.remove();
            clearCache();
            tg.showAlert('Товар успешно удален');
        } catch (error) {
            console.error('Error:', error);
            tg.showAlert('Произошла ошибка при удалении товара');
        }
    }

    function showStockModal(action, sku) {
        const modal = document.getElementById(`stockModal-${sku}`);
        const title = document.getElementById(`stockModalTitle-${sku}`);
        const fields = document.getElementById(`stockModalFields-${sku}`);
        const card = document.querySelector(`.tg-product-card[data-sku="${sku}"]`);
        const warehouses = JSON.parse(card.dataset.warehouses);
        // Получаем остатки по складам
        const stockMap = {};
        const stockItems = card.querySelectorAll('.stock-item');
        stockItems.forEach(item => {
            const name = item.querySelector('.stock-item-name').textContent.trim();
            const qty = parseInt((item.querySelector('.stock-item-qty').textContent || '0').replace(/[^\d-]/g, ''));
            stockMap[name] = qty;
        });
        let html = '';
        if (action === 'move') {
            title.textContent = 'Перемещение товара';
            // Только склады с остатком > 0
            const fromWarehouses = warehouses.filter(w => stockMap[w] > 0);
            if (fromWarehouses.length === 0) {
                tg.showAlert('Нет складов с остатком для перемещения');
                return;
            }
            const fromDefault = fromWarehouses[0];
            const toOptions = fromDefault ? warehouses.filter(w => w !== fromDefault) : [];
            html = `
                <label>Склад-источник:<br>
                    <select id="modalFrom-${sku}">
                        ${fromWarehouses.map(w => `<option value="${w}">${w} (${stockMap[w]} шт.)</option>`).join('')}
                    </select>
                </label><br><br>
                <label>Склад-назначения:<br>
                    <select id="modalTo-${sku}">
                        ${toOptions.map(w => `<option value="${w}">${w}</option>`).join('')}
                    </select>
                </label><br><br>
                <label>Количество:<br>
                    <input id="modalQty-${sku}" type="number" min="1" style="width:80px;">
                </label>
            `;
        } else if (action === 'remove') {
            title.textContent = 'Списание товара';
            // Только склады с остатком > 0 для списания
            const removeWarehouses = warehouses.filter(w => stockMap[w] > 0);
            if (removeWarehouses.length === 0) {
                tg.showAlert('Нет складов с остатком для списания');
                return;
            }
            html = `
                <label>Склад:<br>
                    <select id="modalWarehouse-${sku}">
                        ${removeWarehouses.map(w => `<option value="${w}">${w} (${stockMap[w]} шт.)</option>`).join('')}
                    </select>
                </label><br><br>
                <label>Количество:<br>
                    <input id="modalQty-${sku}" type="number" min="1" style="width:80px;">
                </label>
            `;
        } else {
            title.textContent = action === 'add' ? 'Пополнение товара' : 'Списание товара';
            html = `
                <label>Склад:<br>
                    <select id="modalWarehouse-${sku}">${warehouses.map(w => `<option value="${w}">${w}</option>`).join('')}</select>
                </label><br><br>
                <label>Количество:<br>
                    <input id="modalQty-${sku}" type="number" min="1" style="width:80px;">
                </label>
            `;
        }
        fields.innerHTML = html;
        modal.style.display = 'flex';
        modal.dataset.action = action;

        // Динамическое обновление склада-назначения
        if (action === 'move') {
            const fromSelect = document.getElementById(`modalFrom-${sku}`);
            const toSelect = document.getElementById(`modalTo-${sku}`);
            const okBtn = modal.querySelector('.stock-modal-btn.ok');
            if (fromSelect) {
                fromSelect.addEventListener('change', () => {
                    const selectedWarehouse = fromSelect.value;
                    const toOptions = warehouses.filter(w => w !== selectedWarehouse);
                    toSelect.innerHTML = toOptions.map(w => `<option value="${w}">${w}</option>`).join('');
                });
            }
            if (fromSelect && fromSelect.disabled && okBtn) okBtn.disabled = true;
        }
        if (action === 'remove') {
            const removeSelect = document.getElementById(`modalWarehouse-${sku}`);
            const okBtn = modal.querySelector('.stock-modal-btn.ok');
            if (removeSelect && removeSelect.disabled && okBtn) okBtn.disabled = true;
        }
    }

    function closeStockModal(sku) {
        document.getElementById(`stockModal-${sku}`).style.display = 'none';
    }

    async function confirmStockModal(sku) {
        const modal = document.getElementById(`stockModal-${sku}`);
        const action = modal.dataset.action;
        const card = document.querySelector(`.tg-product-card[data-sku="${sku}"]`);
        const warehouses = JSON.parse(card.dataset.warehouses);
        if (action === 'move') {
            const from = document.getElementById(`modalFrom-${sku}`).value;
            const to = document.getElementById(`modalTo-${sku}`).value;
            const qty = parseInt(document.getElementById(`modalQty-${sku}`).value);
            if (!from || !to || from === to || !qty || qty <= 0) {
                tg.showAlert('Проверьте корректность выбора складов и количества');
                return;
            }
            try {
                const response = await fetch('/api/warehouse/transfer-item/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sku: sku, from_warehouse: from, to_warehouse: to, quantity: qty })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Ошибка при перемещении');
                await updateStockDisplay(sku, from, -qty);
                await updateStockDisplay(sku, to, qty);
                tg.showAlert(data.message || 'Перемещение выполнено');
            } catch (e) {
                tg.showAlert(e.message || 'Ошибка при перемещении');
            }
        } else {
            const warehouse = document.getElementById(`modalWarehouse-${sku}`).value;
            const qty = parseInt(document.getElementById(`modalQty-${sku}`).value);
            if (!warehouse || !qty || qty <= 0) {
                tg.showAlert('Проверьте корректность выбора склада и количества');
                return;
            }
            try {
                const url = action === 'add' ? '/api/warehouse/add/' : '/api/warehouse/remove/';
                const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sku: sku, warehouse: warehouse, quantity: qty })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Ошибка при операции');
                await updateStockDisplay(sku, warehouse, action === 'add' ? qty : -qty);
                tg.showAlert(data.message || 'Операция выполнена');
            } catch (e) {
                tg.showAlert(e.message || 'Ошибка при операции');
            }
        }
        closeStockModal(sku);
    }

    function applyFiltersFromStorage() {
        const filters = filterCache.get();
        document.getElementById('searchInput').value = filters.search || '';
        document.getElementById('stockFilter').value = filters.stock_filter || '';
        document.getElementById('sortOrder').value = filters.sort_order || '';
        document.getElementById('pageSize').value = filters.page_size || '50';
        const clearSearchBtn = document.getElementById('clearSearchBtn');
        if (clearSearchBtn) {
            clearSearchBtn.style.display = filters.search ? 'flex' : 'none';
        }
        updateResetFiltersBtnVisibility();
    }

    async function loadProducts(page = 1, append = false) {
        if (isLoading || (!hasMore && append)) return;
        const stockInput = document.getElementById('stockFilter');
        const valRaw = stockInput.value;
        const val = valRaw.trim();
        if (val && !isValidStockFilter(val)) {
            return;
        }
        isLoading = true;
        const loadingSpinner = document.getElementById('loadingSpinner');
        const productsList   = document.getElementById('productsList');
        const emptyState     = document.getElementById('emptyState');
        const pagination     = document.getElementById('paginationBottom');
        const filtersPanel   = document.getElementById('filtersPanel');
        const mobilePanel    = document.querySelector('.mobile-panel');
        const applyFiltersBtn = document.getElementById('applyFiltersBtn');
        const filterInputs   = filtersPanel ? filtersPanel.querySelectorAll('input, select') : [];
        loadingSpinner.classList.add('active');
        productsList.style.display = 'none';
        if (!append) productsList.innerHTML = '';
        if (emptyState) emptyState.style.display = 'none';
        if (pagination) pagination.style.display = 'none';
        if (filtersPanel) {
            filtersPanel.classList.add('disabled');
            filterInputs.forEach(input => input.disabled = true);
            if (applyFiltersBtn) applyFiltersBtn.disabled = true;
        }
        if (mobilePanel) {
            mobilePanel.classList.add('disabled');
        }
        const filters = getFilters();
        filters.page = page;
        try {
            const params = new URLSearchParams(filters);
            const response = await fetch(`/tg/api/catalog?${params.toString()}`, {
                headers: { 'Accept': 'application/json' }
            });
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();
            console.log('Ответ сервера:', data);
            if (!data || !Array.isArray(data.products)) {
                console.error('Ошибка формата данных:', data);
                throw new Error('Некорректный формат данных от сервера');
            }
            await handleProductsData(data, productsList, emptyState, pagination);
            const url = `${location.pathname}?${new URLSearchParams(filters).toString()}&page=${page}`;
            window.history.replaceState(null, '', url);
        } catch (error) {
            console.error('Ошибка при загрузке товаров:', error);
            if (tg && tg.showAlert) tg.showAlert('Произошла ошибка при загрузке товаров');
            else alert('Произошла ошибка при загрузке товаров');
        } finally {
            loadingSpinner.classList.remove('active');
            isLoading = false;
            renderPagination();
            if (filtersPanel) {
                filtersPanel.classList.remove('disabled');
                filterInputs.forEach(input => input.disabled = false);
                if (applyFiltersBtn) applyFiltersBtn.disabled = false;
            }
            if (mobilePanel) {
                mobilePanel.classList.remove('disabled');
            }
        }
    }

    async function handleProductsData(data, productsList, emptyState, pagination) {
        if (!data || !Array.isArray(data.products)) {
            console.error('Некорректный формат данных:', data);
            if (emptyState) emptyState.style.display = 'block';
            productsList.style.display = 'none';
            if (pagination) pagination.style.display = 'none';
            return;
        }
        for (const item of data.products) {
            const div = document.createElement('div');
            div.innerHTML = item.html;
            const card = div.firstElementChild;
            const img = card.querySelector('.tg-product-image img');
            if (img && img.src.startsWith('data:image')) {
                const sku = card.getAttribute('data-sku');
                try {
                    // Получаем base64 из текущего src
                    const base64 = img.src.split(',')[1];
                    const mimeString = img.src.split(',')[0].split(':')[1].split(';')[0];

                    // Проверяем, есть ли blob в кэше
                    const cachedBlob = await getImageFromDB(sku);

                    // Если blob есть, сравниваем его с текущим base64
                    let needUpdate = true;
                    if (cachedBlob) {
                        // Преобразуем blob обратно в base64 для сравнения
                        const arrayBuffer = await cachedBlob.arrayBuffer();
                        const cachedBase64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));
                        if (cachedBase64 === base64) {
                            // Всё совпадает, используем кэш
                            img.src = URL.createObjectURL(cachedBlob);
                            needUpdate = false;
                        }
                    }
                    if (needUpdate) {
                        // Конвертируем base64 в Blob и сохраняем
                        const byteString = atob(base64);
                        const ab = new ArrayBuffer(byteString.length);
                        const ia = new Uint8Array(ab);
                        for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
                        const blob = new Blob([ab], { type: mimeString });
                        await saveImageToDB(sku, blob);
                        img.src = URL.createObjectURL(blob);
                    }
                } catch (e) {
                    console.warn('Ошибка кеша изображений:', e);
                }
            }
            productsList.appendChild(card);
        }
        currentPage = data.page;
        totalPages = data.total_pages;
        hasMore = data.page < data.total_pages;
        if (!data.products || data.products.length === 0) {
            if (emptyState) emptyState.style.display = 'block';
            productsList.style.display = 'none';
            if (pagination) pagination.style.display = 'none';
        } else {
            if (emptyState) emptyState.style.display = 'none';
            productsList.style.display = 'block';
            const filtersPanel = document.getElementById('filtersPanel');
            if (pagination) pagination.style.display = (filtersPanel && filtersPanel.classList.contains('active')) ? 'none' : '';
        }
    }

    // Добавьте новую функцию после clearAllFiltersOnLoad
    function resetFilters() {
        clearAllFiltersOnLoad();
        handleFilterChange();
    }

    // Добавьте функцию в список глобальных функций
    window.resetFilters = resetFilters;

    // Вызов при изменении любого фильтра
    document.getElementById('searchInput').addEventListener('input', updateResetFiltersBtnVisibility);
    document.getElementById('stockFilter').addEventListener('input', updateResetFiltersBtnVisibility);
    document.getElementById('sortOrder').addEventListener('change', updateResetFiltersBtnVisibility);
    document.getElementById('pageSize').addEventListener('change', updateResetFiltersBtnVisibility);

    // Вызов при инициализации
    updateResetFiltersBtnVisibility();
}); 