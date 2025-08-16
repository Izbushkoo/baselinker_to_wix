from app.services.operations_service import OperationType

def operation_type_label(operation_type: str) -> str:
    """Преобразует тип операции в читаемый формат на русском языке."""
    labels = {
        'stock_in': 'Поступление',
        'stock_in_file': 'Поступление из файла',
        'transfer_file': 'Перемещение из файла',
        'stock_out_manual': "Списание товара",
        'stock_out_order': "Списание по заказу",
        'transfer': 'Перемещение',
        'product_create': 'Создание товара',
        'product_delete': 'Удаление товара',
        'product_edit': 'Редактирование товара'
    }
    return labels.get(operation_type, operation_type)

def localize_action(action: str) -> str:
    """Локализация действий операций синхронизации складов."""
    action_labels = {
        'created': 'Создана',
        'processing_started': 'Начата обработка',
        'loading_line_items': 'Загрузка позиций заказа',
        'line_items_loaded': 'Позиции заказа загружены',
        'line_items_load_failed': 'Ошибка загрузки позиций',
        'stock_validation_failed': 'Провал валидации остатков',
        'stock_deducted': 'Товар списан',
        'stock_deduction_completed': 'Списание завершено',
        'stock_deduction_failed': 'Ошибка списания',
        'sales_operation_created': 'Создана операция продажи',
        'sales_operation_failed': 'Ошибка создания операции продажи',
        'sync_success': 'Синхронизация успешна',
        'sync_failed': 'Синхронизация провалена',
        'sync_error': 'Ошибка синхронизации',
        'completed': 'Завершена',
        'retry_failed': 'Повторная попытка провалена',
        'max_retries': 'Достигнуто максимум попыток',
        'rolled_back': 'Операция отменена',
        'already_processed': 'Уже обработан',
        'order_status_check_failed': 'Ошибка проверки статуса заказа',
        'order_not_ready': 'Заказ не готов к обработке',
        'order_cancelled': 'Заказ отменен',
        'manual_completion': 'Ручное завершение',
        'account_name_updated': 'Имя аккаунта обновлено',
        'sync_retry': 'Повторная синхронизация',
        'sync_completed': 'Синхронизация завершена',
        'error': 'Ошибка'
    }
    return action_labels.get(action, action)

def order_status_label(status: str) -> str:
    """Преобразует статус заказа в читаемый формат на русском языке."""
    status_labels = {
        'BOUGHT': 'Куплен',
        'FILLED_IN': 'Заполнен',
        'READY_FOR_PROCESSING': 'Готов к отправке',
        'SENT': 'Отправлен',
        'CANCELLED': 'Отменен покупателем',
        'CANCELLED_BY_SELLER': 'Отменен продавцом'
    }
    return status_labels.get(status, status)

def order_status_color(status: str) -> str:
    """Возвращает CSS классы для цветного отображения статуса заказа."""
    status_colors = {
        'BOUGHT': 'bg-gray-100 text-gray-800',
        'FILLED_IN': 'bg-yellow-100 text-yellow-800',
        'READY_FOR_PROCESSING': 'bg-blue-100 text-blue-800',
        'SENT': 'bg-green-100 text-green-800',
        'CANCELLED': 'bg-red-100 text-red-800',
        'CANCELLED_BY_SELLER': 'bg-red-100 text-red-800'
    }
    return status_colors.get(status, 'bg-gray-100 text-gray-800')

def localize_log_message(action: str, message: str, details: dict = None) -> str:
    """Локализация сообщений в логах операций синхронизации."""
    # Для ручного завершения добавляем особое форматирование
    if action == 'manual_completion' and details:
        completed_by = details.get('completed_by', 'Неизвестно')
        products_count = details.get('products_count', 0)
        return f"Операция завершена вручную пользователем {completed_by}. Обработано товаров: {products_count}"
    
    # Для остальных действий возвращаем оригинальное сообщение
    return message

def format_log_details(details: dict) -> str:
    """Форматирует детали логов для отображения в HTML."""
    if not details or not isinstance(details, dict):
        return "Нет данных"
    
    # Исключаем основное сообщение из детального вывода
    filtered_details = {k: v for k, v in details.items() if k != 'message'}
    
    if not filtered_details:
        return "Нет дополнительных данных"
    
    html_parts = []
    for key, value in filtered_details.items():
        if isinstance(value, dict):
            # Рекурсивно обрабатываем вложенные словари
            nested_html = "<ul>"
            for nested_key, nested_value in value.items():
                nested_html += f"<li><strong>{nested_key}:</strong> {nested_value}</li>"
            nested_html += "</ul>"
            html_parts.append(f"<div><strong>{key}:</strong>{nested_html}</div>")
        elif isinstance(value, list):
            # Обрабатываем списки
            list_html = "<ul>"
            for item in value:
                if isinstance(item, dict):
                    list_html += "<li>" + format_log_details(item) + "</li>"
                else:
                    list_html += f"<li>{item}</li>"
            list_html += "</ul>"
            html_parts.append(f"<div><strong>{key}:</strong>{list_html}</div>")
        else:
            html_parts.append(f"<div><strong>{key}:</strong> {value}</div>")
    
    return "<div>" + "".join(html_parts) + "</div>"
