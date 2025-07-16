"""
 * @file: celery_shared.py
 * @description: Общие объекты Celery для использования в других модулях
 * @dependencies: core.config, database, models.allegro_token, services.allegro.tokens, services.allegro.data_access
 * @created: 2024-12-20
"""

import os
from dotenv import load_dotenv
from sqlmodel import Session
from sqlalchemy.orm import sessionmaker
from celery import Celery

# Загружаем переменные окружения перед импортом config
load_dotenv()

# Проверяем, запущено ли приложение в Docker
is_docker = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")

# Если запущено в Docker, перезагружаем переменные из .env.docker
if is_docker:
    load_dotenv(".env.docker", override=True)
    print("Celery: Загружены переменные из .env.docker")

from app.core.config import settings
from app.database import engine
from app.models.allegro_token import AllegroToken
from app.services.allegro.tokens import check_token_sync
from app.services.allegro.data_access import get_token_by_id_sync

# Настройки брокера (Redis)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

# Инициализация Celery
celery = Celery(
    "baselinker_to_wix",
    broker=CELERY_BROKER_URL,
    backend=CELERY_BROKER_URL,
    include=["app.services.allegro.sync_tasks"]
)

celery.conf.result_backend = "redis://redis:6379/1"

# Настройка Celery
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_hijack_root_logger=False,  # Отключаем перехват root логгера
    worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s',
    broker_connection_retry_on_startup=True  # Добавляем эту настройку для устранения предупреждения
)

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

def get_allegro_token(session: Session, token_id: str) -> AllegroToken:
    """
    Получает и проверяет токен Allegro из базы данных.
    
    Args:
        session: Сессия SQLModel
        token_id: ID токена
        
    Returns:
        AllegroToken: Проверенный и обновленный токен
        
    Raises:
        ValueError: Если токен не найден или не удалось его проверить/обновить
    """
    # Получаем токен из базы
    token = get_token_by_id_sync(session, token_id)
    if not token:
        raise ValueError(f"Токен Allegro с ID {token_id} не найден в базе данных")
    
    # Проверяем и при необходимости обновляем токен
    result = check_token_sync(token_id)
    if not result:
        raise ValueError(f"Не удалось проверить/обновить токен с ID {token_id}")
        
    # Обновляем токен в сессии если он был обновлен
    if result.get('access_token') != token.access_token:
        token.access_token = result['access_token']
        token.refresh_token = result['refresh_token']
        session.add(token)
        session.commit()
        session.refresh(token)
        
    return token 