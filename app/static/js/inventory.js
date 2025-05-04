let searchTimeout;

async function handleFilterChange() {
    // Очищаем предыдущий таймаут, чтобы избежать частых запросов
    clearTimeout(searchTimeout);
    
    // Показываем состояние загрузки
    document.getElementById('loadingState').classList.remove('hidden');
    document.getElementById('productsList').classList.add('hidden');
    
    // Ждем немного перед отправкой запроса (300ms)
    searchTimeout = setTimeout(async () => {
        try {
            // Получаем значения фильтров
            const search = document.getElementById('searchInput').value;
            const pageSize = document.getElementById('pageSizeSelect').value;
            
            // Формируем URL с параметрами
            const params = new URLSearchParams({
                search: search,
                page_size: pageSize,
                page: 1 // Сбрасываем на первую страницу при поиске
            });
            
            // Делаем запрос к API
            const response = await fetch(`/api/v1/products?${params.toString()}`);
            if (!response.ok) {
                throw new Error('Ошибка при получении данных');
            }
            
            const data = await response.json();
            
            // Обновляем список товаров
            const productsList = document.getElementById('productsList');
            productsList.innerHTML = data.products.map(item => item.html).join('');
            
            // Обновляем пагинацию
            updatePagination(data.page, Math.ceil(data.total / data.page_size));
            
            // Показываем пустое состояние, если нет результатов
            const emptyState = document.getElementById('emptyState');
            if (data.products.length === 0) {
                emptyState.classList.remove('hidden');
                productsList.classList.add('hidden');
            } else {
                emptyState.classList.add('hidden');
                productsList.classList.remove('hidden');
            }
            
        } catch (error) {
            console.error('Ошибка при фильтрации:', error);
            alert('Произошла ошибка при фильтрации товаров');
        } finally {
            // Скрываем состояние загрузки
            document.getElementById('loadingState').classList.add('hidden');
            document.getElementById('productsList').classList.remove('hidden');
        }
    }, 300);
}

// Функция для обновления пагинации
function updatePagination(currentPage, totalPages) {
    const nav = document.querySelector('[aria-label="Pagination"]');
    if (!nav) return;
    
    let html = '<ul class="inline-flex items-center -space-x-px rounded-md shadow-sm">';
    
    // Кнопка "Назад"
    if (currentPage > 1) {
        html += `
            <li>
                <a href="javascript:void(0)" onclick="goToPage(${currentPage - 1})"
                   class="relative inline-flex items-center rounded-l-md px-3 py-2 text-sm font-medium text-gray-900 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 focus:z-20 focus:outline-offset-0">
                    <svg class="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
                    </svg>
                </a>
            </li>`;
    }
    
    // Номера страниц
    for (let i = 1; i <= totalPages; i++) {
        html += `
            <li>
                <a href="javascript:void(0)" onclick="goToPage(${i})"
                   class="relative inline-flex items-center px-4 py-2 text-sm font-medium ${i === currentPage 
                       ? 'z-10 bg-blue-600 text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600'
                       : 'text-gray-900 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 focus:z-20 focus:outline-offset-0'}">
                    ${i}
                </a>
            </li>`;
    }
    
    // Кнопка "Вперед"
    if (currentPage < totalPages) {
        html += `
            <li>
                <a href="javascript:void(0)" onclick="goToPage(${currentPage + 1})"
                   class="relative inline-flex items-center rounded-r-md px-3 py-2 text-sm font-medium text-gray-900 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 focus:z-20 focus:outline-offset-0">
                    <svg class="h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
                    </svg>
                </a>
            </li>`;
    }
    
    html += '</ul>';
    nav.innerHTML = html;
}

// Функция для перехода на страницу
async function goToPage(page) {
    const search = document.getElementById('searchInput').value;
    const pageSize = document.getElementById('pageSizeSelect').value;
    
    const params = new URLSearchParams({
        search: search,
        page_size: pageSize,
        page: page
    });
    
    // Показываем состояние загрузки
    document.getElementById('loadingState').classList.remove('hidden');
    document.getElementById('productsList').classList.add('hidden');
    
    try {
        const response = await fetch(`/api/v1/products?${params.toString()}`);
        if (!response.ok) {
            throw new Error('Ошибка при получении данных');
        }
        
        const data = await response.json();
        
        // Обновляем список товаров
        const productsList = document.getElementById('productsList');
        productsList.innerHTML = data.products.map(item => item.html).join('');
        
        // Обновляем пагинацию
        updatePagination(data.page, Math.ceil(data.total / data.page_size));
        
        // Показываем пустое состояние, если нет результатов
        const emptyState = document.getElementById('emptyState');
        if (data.products.length === 0) {
            emptyState.classList.remove('hidden');
            productsList.classList.add('hidden');
        } else {
            emptyState.classList.add('hidden');
            productsList.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Ошибка при переходе на страницу:', error);
        alert('Произошла ошибка при загрузке страницы');
    } finally {
        document.getElementById('loadingState').classList.add('hidden');
        document.getElementById('productsList').classList.remove('hidden');
    }
}

// Функции для работы с модальным окном перемещения
document.addEventListener('DOMContentLoaded', function() {
    let currentModal = null;
    const modalTemplate = document.getElementById('transferModal');
    
    if (!modalTemplate) {
        console.error('Модальное окно не найдено');
        return;
    }

    // Глобальная функция для открытия модального окна
    window.openTransferModal = function(button) {
        const sku = button.dataset.productSku;
        const name = button.dataset.productName;
        
        console.log('Открытие модального окна:', { sku, name });
        
        // Заполняем данные в модальном окне
        document.getElementById('transferSku').value = sku;
        document.getElementById('productName').textContent = name;
        
        // Показываем модальное окно
        modalTemplate.classList.remove('hidden');
        currentModal = modalTemplate;
        
        // Сбрасываем форму
        document.getElementById('transferForm').reset();
    };

    window.closeTransferModal = function() {
        if (currentModal) {
            currentModal.classList.add('hidden');
            document.getElementById('transferForm').reset();
            currentModal = null;
        }
    };

    // Обработчик отправки формы
    document.getElementById('transferForm').addEventListener('submit', async function(event) {
        console.log('Форма отправлена');
        event.preventDefault();
        const formData = new FormData(event.target);
        
        try {
            const requestData = {
                sku: formData.get('sku'),
                from_warehouse: formData.get('from_warehouse'),
                to_warehouse: formData.get('to_warehouse'),
                quantity: parseInt(formData.get('quantity'))
            };

            const response = await fetch('/api/warehouse/transfer-item/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Ошибка при перемещении товара');
            }

            // Показываем сообщение об успехе
            alert(data.message || 'Товар успешно перемещен');

            // Закрываем модальное окно и обновляем страницу
            window.closeTransferModal();
            window.location.reload();
        } catch (error) {
            console.error('Ошибка:', error);
            alert(error.message);
        }
    });

    // Закрытие модального окна при клике вне его области
    document.addEventListener('click', function(event) {
        if (currentModal && event.target === currentModal) {
            closeTransferModal();
        }
    });

    // Предотвращаем закрытие при клике на содержимое модального окна
    const modalContent = modalTemplate.querySelector('.bg-white');
    if (modalContent) {
        modalContent.addEventListener('click', function(event) {
            event.stopPropagation();
        });
    }

    // Добавляем обработчики для поиска и изменения количества товаров
    const searchInput = document.getElementById('searchInput');
    const pageSizeSelect = document.getElementById('pageSizeSelect');
    
    if (searchInput) {
        searchInput.addEventListener('input', handleFilterChange);
    }
    
    if (pageSizeSelect) {
        pageSizeSelect.addEventListener('change', handleFilterChange);
    }
}); 