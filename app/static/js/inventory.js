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
        
        console.log('Данные формы:', {
            sku: formData.get('sku'),
            from_warehouse: formData.get('from_warehouse'),
            to_warehouse: formData.get('to_warehouse'),
            quantity: formData.get('quantity')
        });

        try {
            const requestData = {
                sku: formData.get('sku'),
                from_warehouse: formData.get('from_warehouse'),
                to_warehouse: formData.get('to_warehouse'),
                quantity: parseInt(formData.get('quantity'))
            };
            
            console.log('Начало отправки запроса');
            console.log('URL:', '/api/warehouse/transfer-item/');
            console.log('Данные запроса:', requestData);

            const response = await fetch('/api/warehouse/transfer-item/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            });

            console.log('Получен ответ:', {
                status: response.status,
                statusText: response.statusText,
                headers: Object.fromEntries(response.headers.entries())
            });

            const data = await response.json();
            console.log('Данные ответа:', data);

            if (!response.ok) {
                throw new Error(data.detail || 'Ошибка при перемещении товара');
            }

            // Показываем сообщение об успехе
            alert(data.message || 'Товар успешно перемещен');

            // Закрываем модальное окно и обновляем страницу
            window.closeTransferModal();
            window.location.reload();
        } catch (error) {
            console.error('Подробная ошибка:', {
                name: error.name,
                message: error.message,
                stack: error.stack
            });
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