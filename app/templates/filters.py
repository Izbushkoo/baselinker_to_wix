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
        'product_delete': 'Удаление товара'
    }
    return labels.get(operation_type, operation_type) 