import logging
import os
from logging.handlers import RotatingFileHandler

# Создаём директорию для логов, если её нет
LOG_PATH = "/app/logs"
os.makedirs(LOG_PATH, exist_ok=True)

def setup_logging(logger_name: str, log_file: str):
    """
    Настраивает логирование для указанного логгера.
    
    Args:
        logger_name: Имя логгера
        log_file: Имя файла для логов
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    
    # Форматтер для логов
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Хендлер для вывода в консоль (stdout)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Хендлер для записи в файл с ротацией
    file_handler = RotatingFileHandler(
        os.path.join(LOG_PATH, log_file),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger 