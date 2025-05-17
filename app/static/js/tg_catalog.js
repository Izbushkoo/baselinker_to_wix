import { saveImageToDB, getImageFromDB } from './image_cache.js';


// Ожидаем загрузки DOM и Telegram WebApp
document.addEventListener('DOMContentLoaded', function() {

    // В начале скрипта (внутри DOMContentLoaded) добавьте:
    let stateHistory = [];  // <<< где хранятся все состояния

    window.toggleMenu = toggleMenu;
    window.goTo = goTo;
    window.copyToClipboard = copyToClipboard;
    window.toggleDetails = toggleDetails;
    window.showStockModal = showStockModal;
    window.closeStockModal = closeStockModal;
    window.confirmStockModal = confirmStockModal;
    window.deleteProduct = deleteProduct;

    window.addEventListener('popstate', event => {
        const state = event.state;
        if (state && state.filters) {
            applyState(state); // <<< ИЗМЕНЕНИЕ
        }
    });

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
        if (stateHistory.length > 1) {
            // Убираем текущее состояние
            stateHistory.pop();
            const prev = stateHistory[stateHistory.length - 1];
            
            // Восстанавливаем UI-фильтры и подгружаем нужную страницу
            applyState(prev);
            
            // Обновляем URL без новых записей
            const url = `${location.pathname}?${new URLSearchParams(prev.filters).toString()}&page=${prev.page}`;
            window.history.replaceState(prev, '', url);
        } else {
            window.history.back();
        }
    });
    window.addEventListener('pageshow', (event) => {
        console.log('pageshow event triggered', {
            persisted: event.persisted,
            filters: getFilters()
        });
        if (event.persisted) {
            handleFilterChange();
        }
    });
    // Инициализация переменных
    let currentPage = 1;
    let isLoading = false;
    let hasMore = true;
    let totalPages = 1;
    let cacheTimeout = 5 * 60 * 1000; // 5 минут

    function applyState(state) {
        // восстанавливаем поля фильтров
        const f = state.filters;
        document.getElementById('searchInput').value   = f.search       || '';
        document.getElementById('stockFilter').value  = f.stock_filter || '';
        document.getElementById('sortOrder').value    = f.sort_order   || '';
        document.getElementById('pageSize').value     = f.page_size    || '50';
        // загружаем именно ту страницу без пуша в history
        currentPage = state.page;
        hasMore = true;
        loadProducts(state.page, false, false);
    }

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

    function getFilters() {
        const filters = {};
        const search = document.getElementById('searchInput').value.trim();
        const stock_filter = document.getElementById('stockFilter').value.trim();
        const sort_order = document.getElementById('sortOrder').value;
        const page_size = document.getElementById('pageSize').value;

        if (search) filters.search = search;
        if (stock_filter) {
            const stockValue = parseInt(stock_filter);
            if (stockValue > 0) {
                filters.stock_filter = stockValue;
            } else {
                if (stockValue == 0) {
                    if (tg && tg.showAlert) {
                        tg.showAlert('Остаток не может быть меньше 0');
                }
                }
                if (tg && tg.showAlert) {
                    tg.showAlert('Значение остатка не может быть отрицательным');
                }
                document.getElementById('stockFilter').value = '';
                return filters;
            }
        }
        if (sort_order) filters.sort_order = sort_order;
        if (page_size) filters.page_size = page_size;
        return filters;
    }

    function handleFilterChange() {
        console.log('handleFilterChange called', {
            currentFilters: getFilters(),
            currentPage: currentPage
        });
        currentPage = 1;
        hasMore = true;
        // Сохраняем только фильтры
        filterCache.set(getFilters());
        loadProducts(1, false, false);
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
        
        if (filtersPanel.classList.contains('active')) {
            btn.querySelector('.arrow-up').style.display = 'inline-block';
            btn.querySelector('.filter-icon').style.display = 'none';
            const pagination = document.getElementById('paginationBottom');
            if (pagination) pagination.style.display = 'none';
        } else {
            btn.querySelector('.arrow-up').style.display = 'none';
            btn.querySelector('.filter-icon').style.display = 'inline-block';
            const pagination = document.getElementById('paginationBottom');
            const productsList = document.getElementById('productsList');
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
    });

    // Инициализация при загрузке
    // clearAllFiltersOnLoad();
    initSearchClear();
    applyFiltersFromStorage(); // Восстанавливаем фильтры при загрузке
    
    // Загрузка первой страницы товаров
    loadProducts(1, false, false);

    // Обработка сообщений от Telegram
    tg.onEvent('message', function(event) {
        console.log('Received message:', event);
    });

    // --- Функции для карточек товара ---
    function copyToClipboard(element) {
        if (element.classList.contains('copying')) return;
        const text = element.getAttribute('data-sku');
        navigator.clipboard.writeText(text).then(() => {
            const originalText = element.textContent;
            element.textContent = 'Скопировано!';
            element.style.backgroundColor = 'rgba(34, 197, 94, 0.7)';
            element.style.color = 'white';
            element.style.pointerEvents = 'none';
            element.classList.add('copying');
            setTimeout(() => {
                element.textContent = originalText;
                element.style.backgroundColor = '';
                element.style.color = '';
                element.style.pointerEvents = '';
                element.classList.remove('copying');
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

    async function moveStock(sku, fromWarehouse) {
        try {
            const result = await new Promise(resolve => {
                const warehouses = ['WH1', 'WH2', 'WH3', 'WH4'];
                const buttons = warehouses.filter(wh => wh !== fromWarehouse).map(wh => ({ id: wh, text: `Склад ${wh}` }));
                tg.showPopup({ title: 'Перемещение товара', message: 'Выберите склад назначения:', buttons: buttons }, resolve);
            });
            if (!result) return;
            const toWarehouse = result;
            const qty = await new Promise(resolve => {
                tg.showPopup({ title: 'Количество', message: 'Введите количество для перемещения:', buttons: [{ type: 'default', id: 'cancel', text: 'Отмена' }] }, resolve);
            });
            if (!qty || isNaN(qty) || qty <= 0) {
                tg.showAlert('Неверное количество');
                return;
            }
            const removed = await removeFromStock(sku, fromWarehouse, qty);
            if (!removed) return;
            const added = await addToStock(sku, toWarehouse, qty);
            if (!added) {
                await addToStock(sku, fromWarehouse, qty);
                return;
            }
            // Обновить отображение остатков на обоих складах
            const card = document.querySelector(`.tg-product-card[data-sku="${sku}"]`);
            await updateStockDisplay(card, fromWarehouse, -qty);
            await updateStockDisplay(card, toWarehouse, qty);
            tg.showAlert(`Успешно перемещено ${qty} шт. со склада ${fromWarehouse} на склад ${toWarehouse}`);
        } catch (error) {
            console.error('Error:', error);
            tg.showAlert('Произошла ошибка при перемещении товара');
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
            let warning = '';
            if (fromWarehouses.length === 0) {
                warning = '<div style="color:#b91c1c; margin-bottom:8px;">Нет складов с остатком для перемещения</div>';
            }
            const fromDefault = fromWarehouses[0];
            const toOptions = fromDefault ? warehouses.filter(w => w !== fromDefault) : [];
            html = `
                ${warning}
                <label>Склад-источник:<br>
                    <select id="modalFrom-${sku}" ${fromWarehouses.length === 0 ? 'disabled' : ''}>
                        ${fromWarehouses.map(w => `<option value="${w}">${w} (${stockMap[w]} шт.)</option>`).join('')}
                    </select>
                </label><br><br>
                <label>Склад-назначения:<br>
                    <select id="modalTo-${sku}" ${fromWarehouses.length === 0 ? 'disabled' : ''}>
                        ${toOptions.map(w => `<option value="${w}">${w}</option>`).join('')}
                    </select>
                </label><br><br>
                <label>Количество:<br>
                    <input id="modalQty-${sku}" type="number" min="1" style="width:80px;" ${fromWarehouses.length === 0 ? 'disabled' : ''}>
                </label>
            `;
        } else if (action === 'remove') {
            title.textContent = 'Списание товара';
            // Только склады с остатком > 0 для списания
            const removeWarehouses = warehouses.filter(w => stockMap[w] > 0);
            let warning = '';
            if (removeWarehouses.length === 0) {
                warning = '<div style="color:#b91c1c; margin-bottom:8px;">Нет складов с остатком для списания</div>';
            }
            html = `
                ${warning}
                <label>Склад:<br>
                    <select id="modalWarehouse-${sku}" ${removeWarehouses.length === 0 ? 'disabled' : ''}>
                        ${removeWarehouses.map(w => `<option value="${w}">${w} (${stockMap[w]} шт.)</option>`).join('')}
                    </select>
                </label><br><br>
                <label>Количество:<br>
                    <input id="modalQty-${sku}" type="number" min="1" style="width:80px;" ${removeWarehouses.length === 0 ? 'disabled' : ''}>
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
    }

    async function loadProducts(page = 1, append = false, pushHistory = false) {
        if (isLoading || (!hasMore && append)) return;
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
            // Найти img
            const img = card.querySelector('.tg-product-image img');
            if (img && img.src.startsWith('data:image')) {
                const sku = card.getAttribute('data-sku');
                try {
                    const cachedBlob = await getImageFromDB(sku);
                    if (cachedBlob) {
                        img.src = URL.createObjectURL(cachedBlob);
                    } else {
                        // Конвертируем base64 в Blob и сохраняем
                        const base64 = img.src.split(',')[1];
                        const byteString = atob(base64);
                        const mimeString = img.src.split(',')[0].split(':')[1].split(';')[0];
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
}); 