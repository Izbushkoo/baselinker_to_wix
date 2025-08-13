"""
 * @file: localization.py
 * @description: Локализация текстов для системы синхронизации складов
 * @dependencies: typing
 * @created: 2024-12-28
"""

from typing import Dict, Any

# Словарь локализации действий
ACTION_TRANSLATIONS = {
    "stock_validation_failed": "Провал валидации остатков",
    "processing_started": "Начата обработка",
    "stock_deduction_retry_scheduled": "Запланирована повторная попытка списания",
    "operation_created": "Операция создана",
    "operation_completed": "Операция завершена", 
    "operation_failed": "Операция провалена",
    "stock_deduction_completed": "Списание выполнено успешно",
    "account_name_updated": "Имя аккаунта обновлено",
    "processing_started": "Начата обработка"
}

# Словарь локализации статусов
STATUS_TRANSLATIONS = {
    "pending": "В ожидании",
    "processing": "В обработке", 
    "completed": "Завершено",
    "failed": "Провалено",
    "cancelled": "Отменено",
    "info": "Информация",
    "warning": "Предупреждение",
    "error": "Ошибка"
}

def localize_action(action: str) -> str:
    """
    Локализация названия действия на русский язык.
    
    Args:
        action: Название действия на английском
        
    Returns:
        Локализованное название действия
    """
    return ACTION_TRANSLATIONS.get(action, action)

def localize_status(status: str) -> str:
    """
    Локализация статуса на русский язык.
    
    Args:
        status: Статус на английском
        
    Returns:
        Локализованный статус
    """
    return STATUS_TRANSLATIONS.get(status, status)

def localize_log_message(action: str, message: str, details: Dict[str, Any] = None) -> str:
    """
    Локализация сообщения лога на русский язык.
    
    Args:
        action: Действие
        message: Исходное сообщение
        details: Дополнительные детали
        
    Returns:
        Локализованное сообщение
    """
    # Базовые шаблоны сообщений
    message_templates = {
        "stock_validation_failed": "Провал валидации остатков: {invalid_items} из {total_items} позиций недоступно для списания",
        "processing_started": "Попытка обработки #{retry_count} для аккаунта {account_name} - загрузка данных заказа и выполнение списания",
        "stock_deduction_retry_scheduled": "Списание провалено, повторная попытка запланирована через {delay}: {error}",
        "operation_created": "Операция создана для заказа {order_id}",
        "operation_completed": "Операция успешно завершена",
        "operation_failed": "Операция провалена: {error}",
        "stock_deduction_completed": "Списание выполнено успешно для {items_count} позиций",
        "account_name_updated": "Имя аккаунта обновлено на: {account_name}"
    }
    
    # Если есть шаблон для данного действия, используем его
    if action in message_templates and details:
        try:
            # Извлекаем нужные параметры из details или message
            template = message_templates[action]
            
            if action == "stock_validation_failed":
                invalid_items = details.get("invalid_items", 0)
                total_items = details.get("total_items", 0)
                return template.format(invalid_items=invalid_items, total_items=total_items)
            
            elif action == "processing_started":
                # Извлекаем номер попытки и имя аккаунта из сообщения
                import re
                retry_match = re.search(r"attempt (\d+)", message)
                account_match = re.search(r"account ([^-]+)", message)
                retry_count = retry_match.group(1) if retry_match else "N/A"
                account_name = account_match.group(1).strip() if account_match else "Неизвестен"
                return template.format(retry_count=retry_count, account_name=account_name)
            
            elif action == "stock_deduction_retry_scheduled":
                # Извлекаем задержку и ошибку из сообщения
                import re
                delay_match = re.search(r"retry scheduled in ([^:]+):", message)
                error_match = re.search(r": (.+)$", message)
                delay = delay_match.group(1) if delay_match else "неизвестно"
                error = error_match.group(1) if error_match else "неизвестная ошибка"
                return template.format(delay=delay, error=error)
            
            elif action == "account_name_updated":
                # Извлекаем имя аккаунта из сообщения
                import re
                name_match = re.search(r"to: (.+)$", message)
                account_name = name_match.group(1) if name_match else "неизвестно"
                return template.format(account_name=account_name)
            
        except Exception:
            # Если не удалось применить шаблон, возвращаем исходное сообщение
            pass
    
    # Базовые замены в сообщениях
    localized_message = message
    
    # Замены терминов
    replacements = {
        "Stock validation failed": "Провал валидации остатков",
        "Processing attempt": "Попытка обработки",
        "for account": "для аккаунта",
        "loading order data": "загрузка данных заказа",
        "performing stock deduction": "выполнение списания",
        "Stock deduction failed": "Списание провалено",
        "retry scheduled in": "повторная попытка через",
        "Updated account name to": "Имя аккаунта обновлено на",
        "items unavailable": "позиций недоступно",
        "of": "из"
    }
    
    for en_text, ru_text in replacements.items():
        localized_message = localized_message.replace(en_text, ru_text)
    
    return localized_message

def format_log_details(details: Dict[str, Any]) -> str:
    """
    Форматирует детали лога для красивого отображения в HTML.
    
    Args:
        details: Словарь с деталями лога
        
    Returns:
        HTML-строка с отформатированными деталями
    """
    if not details or not isinstance(details, dict):
        return "<p class='text-gray-500 italic'>Нет данных</p>"
    
    html_parts = []
    
    def format_value(key: str, value: Any, level: int = 0) -> str:
        indent = "  " * level
        key_class = "font-semibold text-gray-700"
        
        if isinstance(value, dict):
            if not value:
                return f"<div class='ml-{level*4}'><span class='{key_class}'>{key}:</span> <span class='text-gray-500 italic'>пусто</span></div>"
            
            items = []
            items.append(f"<div class='ml-{level*4}'><span class='{key_class}'>{key}:</span></div>")
            
            for sub_key, sub_value in value.items():
                items.append(format_value(sub_key, sub_value, level + 1))
            
            return "\n".join(items)
        
        elif isinstance(value, list):
            if not value:
                return f"<div class='ml-{level*4}'><span class='{key_class}'>{key}:</span> <span class='text-gray-500 italic'>пустой список</span></div>"
            
            items = []
            items.append(f"<div class='ml-{level*4}'><span class='{key_class}'>{key}:</span></div>")
            
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    items.append(f"<div class='ml-{(level+1)*4} border-l-2 border-gray-200 pl-3 my-2'>")
                    items.append(f"<span class='text-sm font-medium text-gray-600'>Элемент {i+1}:</span>")
                    for sub_key, sub_value in item.items():
                        items.append(format_value(sub_key, sub_value, level + 2))
                    items.append("</div>")
                else:
                    formatted_item = format_single_value(item)
                    items.append(f"<div class='ml-{(level+1)*4}'>• {formatted_item}</div>")
            
            return "\n".join(items)
        
        else:
            formatted_value = format_single_value(value)
            return f"<div class='ml-{level*4}'><span class='{key_class}'>{key}:</span> {formatted_value}</div>"
    
    def format_single_value(value: Any) -> str:
        """Форматирует отдельное значение."""
        if value is None:
            return "<span class='text-gray-500 italic'>null</span>"
        elif isinstance(value, bool):
            color = "text-green-600" if value else "text-red-600"
            return f"<span class='{color} font-medium'>{'да' if value else 'нет'}</span>"
        elif isinstance(value, (int, float)):
            return f"<span class='text-blue-600 font-mono'>{value}</span>"
        elif isinstance(value, str):
            # Обрабатываем SKU - делаем их копируемыми
            if any(key in ['sku', 'id', 'external'] for key in ['sku']):
                if len(value) > 3 and value.replace('_', '').replace('-', '').isalnum():
                    return f"<span class='font-mono bg-gray-100 px-2 py-1 rounded text-sm select-all cursor-pointer' onclick='copyToClipboard(\"{value}\")' title='Нажмите для копирования'>{value}</span>"
            
            # Декодируем Unicode последовательности
            try:
                if '\\u' in value:
                    import codecs
                    decoded_value = codecs.decode(value, 'unicode_escape')
                    return f"<span class='text-gray-800'>{decoded_value}</span>"
            except Exception:
                pass
            
            # Обычный текст
            if len(value) > 100:
                return f"<span class='text-gray-800'>{value[:100]}...</span>"
            return f"<span class='text-gray-800'>{value}</span>"
        else:
            return f"<span class='text-gray-600'>{str(value)}</span>"
    
    # Специальная обработка для разных типов деталей
    if "validation_errors" in details:
        html_parts.append("<div class='mb-4'>")
        html_parts.append("<h4 class='font-bold text-red-600 mb-2'>🚫 Ошибки валидации:</h4>")
        for error in details["validation_errors"]:
            html_parts.append(f"<div class='ml-4 text-red-700'>• {error}</div>")
        html_parts.append("</div>")
    
    if "items_details" in details:
        html_parts.append("<div class='mb-4'>")
        html_parts.append("<h4 class='font-bold text-blue-600 mb-2'>📦 Детали товаров:</h4>")
        
        for item in details["items_details"]:
            status_color = "text-green-600" if item.get("valid") else "text-red-600"
            status_text = "✓ Доступен" if item.get("valid") else "✗ Недоступен"
            
            html_parts.append("<div class='ml-4 border-l-2 border-gray-200 pl-4 py-2 mb-3'>")
            html_parts.append(f"<div class='flex items-center gap-2 mb-2'>")
            html_parts.append(f"<span class='font-mono bg-gray-100 px-2 py-1 rounded text-sm select-all cursor-pointer' onclick='copyToClipboard(\"{item.get('sku', '')}\")' title='Нажмите для копирования'>{item.get('sku', 'Неизвестно')}</span>")
            html_parts.append(f"<span class='{status_color} font-medium'>{status_text}</span>")
            html_parts.append("</div>")
            
            if item.get("required_quantity") is not None:
                html_parts.append(f"<div class='text-sm text-gray-600'>Требуется: <span class='font-medium'>{item['required_quantity']}</span></div>")
            if item.get("available_quantity") is not None:
                html_parts.append(f"<div class='text-sm text-gray-600'>Доступно: <span class='font-medium'>{item['available_quantity']}</span></div>")
            if item.get("shortage_quantity", 0) > 0:
                html_parts.append(f"<div class='text-sm text-red-600'>Недостает: <span class='font-medium'>{item['shortage_quantity']}</span></div>")
            if item.get("error_message"):
                html_parts.append(f"<div class='text-sm text-red-600 mt-1'>Ошибка: {item['error_message']}</div>")
            
            html_parts.append("</div>")
        
        html_parts.append("</div>")
    
    # Обрабатываем остальные поля
    processed_keys = {"message", "validation_errors", "items_details"}
    remaining_details = {k: v for k, v in details.items() if k not in processed_keys}
    
    if remaining_details:
        html_parts.append("<div class='mb-4'>")
        html_parts.append("<h4 class='font-bold text-gray-700 mb-2'>ℹ️ Дополнительная информация:</h4>")
        
        for key, value in remaining_details.items():
            # Переводим ключи на русский
            key_translations = {
                "total_items": "Всего позиций",
                "valid_items": "Валидных позиций", 
                "invalid_items": "Невалидных позиций",
                "operation_id": "ID операции",
                "order_id": "ID заказа",
                "warehouse": "Склад",
                "account_name": "Имя аккаунта"
            }
            
            display_key = key_translations.get(key, key)
            html_parts.append(format_value(display_key, value))
        
        html_parts.append("</div>")
    
    if not html_parts:
        return "<p class='text-gray-500 italic'>Нет дополнительной информации</p>"
    
    return "\n".join(html_parts)
