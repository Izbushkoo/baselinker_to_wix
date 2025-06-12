"""
 * @file: allegro_event_tracker.py
 * @description: Модель для отслеживания последних обработанных событий Allegro
 * @dependencies: SQLModel, datetime
 * @created: 2025-06-11
"""

from datetime import datetime
from sqlmodel import SQLModel, Field
from typing import Optional

class AllegroEventTracker(SQLModel, table=True):
    """
    Модель для хранения информации о последнем обработанном событии Allegro
    """
    __tablename__ = "allegro_event_trackers"

    id: Optional[int] = Field(default=None, primary_key=True)
    token_id: str = Field(index=True, unique=True)
    last_event_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow) 