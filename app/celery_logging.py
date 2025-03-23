import logging
from app.utils.logging_config import setup_project_logging

# Настраиваем логирование для Celery
logger = setup_project_logging()

# Настраиваем логирование для Celery Beat
celery_logger = logging.getLogger('celery')
celery_beat_logger = logging.getLogger('celery.beat')

# Используем тот же форматтер и хендлеры, что и в основном приложении
celery_logger.handlers = logger.handlers
celery_beat_logger.handlers = logger.handlers 