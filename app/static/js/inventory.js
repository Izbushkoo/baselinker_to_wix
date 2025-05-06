document.addEventListener('DOMContentLoaded', function() {
    console.log('DOMContentLoaded event fired');
    
    // Инициализация поиска
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        console.log('Найден элемент поиска');
        searchInput.addEventListener('input', function(e) {
            console.log('Событие input:', e.target.value);
            window.handleFilterChange();
        });
    } else {
        console.error('Элемент поиска не найден!');
    }
    
    // Инициализация выбора количества товаров
    const pageSizeSelect = document.getElementById('pageSize');
    if (pageSizeSelect) {
        console.log('Найден элемент выбора количества');
        pageSizeSelect.addEventListener('change', function(e) {
            console.log('Событие change:', e.target.value);
            window.handleFilterChange();
        });
    } else {
        console.error('Элемент выбора количества не найден!');
    }
});

// Функции для работы с модальным окном перемещения
window.openTransferModal = function(button) {
    const sku = button.dataset.productSku;
    const name = button.dataset.productName;
    
    console.log('Открытие модального окна:', { sku, name });
    
    document.getElementById('transferSku').value = sku;
    document.getElementById('productName').textContent = name;
    
    document.getElementById('transferModal').classList.remove('hidden');
};

window.closeTransferModal = function() {
    document.getElementById('transferModal').classList.add('hidden');
    document.getElementById('transferForm').reset();
};

// Обработчик отправки формы перемещения
document.getElementById('transferForm')?.addEventListener('submit', async function(event) {
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

        alert(data.message || 'Товар успешно перемещен');
        window.closeTransferModal();
        window.location.reload();
    } catch (error) {
        console.error('Ошибка:', error);
        alert(error.message);
    }
}); 