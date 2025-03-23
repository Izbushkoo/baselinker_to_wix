from celery.schedules import crontab
from app.celery_app import celery, check_recent_orders, sync_all_tokens
from app.utils.logging_config import logger

# Настройка периодических задач
celery.conf.beat_schedule = {
}

if __name__ == '__main__':
    logger.info("Запуск Celery Beat")
    celery.start() 