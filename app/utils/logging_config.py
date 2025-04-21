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
    
    # Очищаем все существующие хендлеры
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
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
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Отключаем пропагацию логов для некоторых модулей
    for logger_name in ["uvicorn", "sqlalchemy", "celery"]:
        module_logger = logging.getLogger(logger_name)
        module_logger.propagate = False
        module_logger.setLevel(logging.WARNING)
    
    # Настраиваем логгер для нашего приложения
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False  # Отключаем пропагацию для app логгера
    
    # Добавляем хендлеры для app логгера
    app_logger.addHandler(console_handler)
    app_logger.addHandler(file_handler)
    
    return app_logger

# Создаем глобальный логгер
logger = setup_project_logging() 