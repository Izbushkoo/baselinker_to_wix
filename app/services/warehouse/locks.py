"""
 * @file: locks.py
 * @description: Утилиты для работы с блокировками синхронизации товаров по SKU
 * @dependencies: ProductSyncLock, SessionLocal, SQLModel
 * @created: 2024-06-13
"""
from typing import Optional
from datetime import datetime, timedelta
from sqlmodel import select
from app.models.product_sync_lock import ProductSyncLock
from app.celery_app import SessionLocal

LOCK_TIMEOUT = timedelta(minutes=10)  # сколько времени лок считается активным


def acquire_product_sync_lock(sku: str, owner: str) -> bool:
    """
    Пытается установить блокировку на товар. Возвращает True, если успешно.
    """
    with SessionLocal() as session:
        lock = session.exec(select(ProductSyncLock).where(ProductSyncLock.sku == sku)).first()
        now = datetime.utcnow()
        if lock:
            # Если лок устарел — можно перехватить
            if lock.status == "in_progress" and (now - lock.locked_at) < LOCK_TIMEOUT:
                return False
            # Перехватываем лок
            lock.locked_at = now
            lock.lock_owner = owner
            lock.status = "in_progress"
            lock.last_error = None
            lock.updated_at = now
            session.add(lock)
            session.commit()
            return True
        # Нет лока — создаём
        new_lock = ProductSyncLock(
            sku=sku,
            locked_at=now,
            lock_owner=owner,
            status="in_progress",
            last_error=None,
            updated_at=now
        )
        session.add(new_lock)
        session.commit()
        return True

def release_product_sync_lock(sku: str, owner: str, status: str, error: Optional[str] = None) -> None:
    """
    Снимает блокировку с товара, обновляет статус и ошибку.
    """
    with SessionLocal() as session:
        lock = session.exec(select(ProductSyncLock).where(ProductSyncLock.sku == sku)).first()
        if lock and lock.lock_owner == owner:
            lock.status = status
            lock.last_error = error
            lock.updated_at = datetime.utcnow()
            session.add(lock)
            session.commit()

def is_product_locked(sku: str) -> bool:
    """
    Проверяет, есть ли активная блокировка на товар.
    """
    with SessionLocal() as session:
        lock = session.exec(select(ProductSyncLock).where(ProductSyncLock.sku == sku)).first()
        if not lock:
            return False
        if lock.status == "in_progress" and (datetime.utcnow() - lock.locked_at) < LOCK_TIMEOUT:
            return True
        return False 