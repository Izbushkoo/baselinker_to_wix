"""
 * @file: allegro_event_tracker_repository.py
 * @description: Репозиторий для работы с трекером событий Allegro
 * @dependencies: SQLModel, Session, AllegroEventTracker
 * @created: 2025-06-11
"""

from sqlmodel import Session, select
from app.models.allegro_event_tracker import AllegroEventTracker
from datetime import datetime

class AllegroEventTrackerRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_last_event_id(self, token_id: str) -> str | None:
        """
        Получает ID последнего события для указанного токена
        
        Args:
            token_id: ID токена Allegro
            
        Returns:
            str | None: ID последнего события или None, если запись не найдена
        """
        statement = select(AllegroEventTracker).where(AllegroEventTracker.token_id == token_id)
        tracker = self.session.exec(statement).first()
        return tracker.last_event_id if tracker else None

    def update_last_event_id(self, token_id: str, event_id: str) -> AllegroEventTracker:
        """
        Обновляет или создает запись о последнем событии
        
        Args:
            token_id: ID токена Allegro
            event_id: ID последнего события
            
        Returns:
            AllegroEventTracker: Обновленная или созданная запись
        """
        statement = select(AllegroEventTracker).where(AllegroEventTracker.token_id == token_id)
        tracker = self.session.exec(statement).first()
        
        if tracker:
            tracker.last_event_id = event_id
            tracker.updated_at = datetime.utcnow()
        else:
            tracker = AllegroEventTracker(
                token_id=token_id,
                last_event_id=event_id
            )
            self.session.add(tracker)
            
        self.session.commit()
        self.session.refresh(tracker)
        return tracker 