# Импорты для регистрации задач в Celery
from . import stock_sync_tasks
from . import publication_update_tasks

__all__ = [
    "stock_sync_tasks",
    "publication_update_tasks"
]
