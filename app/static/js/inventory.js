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
        event.preventDefault();
        const formData = new FormData(event.target);

        try {
            console.log('Отправка данных:', {
                sku: formData.get('sku'),
                from_warehouse: formData.get('from_warehouse'),
                to_warehouse: formData.get('to_warehouse'),
                quantity: formData.get('quantity')
            });

            const response = await fetch('/api/warehouse/transfer-item/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    sku: formData.get('sku'),
                    from_warehouse: formData.get('from_warehouse'),
                    to_warehouse: formData.get('to_warehouse'),
                    quantity: parseInt(formData.get('quantity'))
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Ошибка при перемещении товара');
            }

            // Показываем сообщение об успехе
            alert(data.message || 'Товар успешно перемещен');

            // Закрываем модальное окно и обновляем страницу
            closeTransferModal();
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
}); 