from datetime import datetime
from typing import Optional

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Парсит дату из строки формата DD-MM-YYYY в объект datetime.
    
    Args:
        date_str: Строка с датой в формате DD-MM-YYYY или None
        
    Returns:
        datetime объект или None. Если дата указана, время будет установлено в 00:00:00,
        что означает начало указанного дня.
        
    Example:
        >>> parse_date("20-03-2025")
        datetime(2025, 3, 20, 0, 0, 0)  # Начало дня 20 марта 2025
    """
    if not date_str:
        return None
        
    try:
        # Создаем datetime объект с временем 00:00:00 (начало дня)
        return datetime.strptime(date_str, "%d-%m-%Y")
    except ValueError:
        raise ValueError("Дата должна быть в формате DD-MM-YYYY") 