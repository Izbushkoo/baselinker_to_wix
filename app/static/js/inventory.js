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

// Функции для работы с модальным окном перемещения удалены из inventory.js
// Они теперь определены в соответствующих шаблонах:
// - openTransferModal(button) для кнопок в operation_details_blocks/scripts.html
// - openTransferModal(fromData, toData) для drag&drop в catalog_new_blocks/product_card.html

// Quick Edit Slider функции также удалены - они определены в operation_details_blocks/scripts.html