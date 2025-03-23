import logging
import os
from logging.handlers import RotatingFileHandler

# Создаём директорию для логов, если её нет
LOG_PATH = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_PATH, exist_ok=True)

def setup_project_logging():
    """
    Настраивает логирование для всего проекта.
    """
    # Форматтер для логов
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Хендлер для вывода в консоль (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Хендлер для записи в файл с ротацией
    file_handler = RotatingFileHandler(
        os.path.join(LOG_PATH, "app.log"),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    
    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Отключаем логи от сторонних библиотек
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    
    return root_logger

# Создаем глобальный логгер
logger = setup_project_logging() 