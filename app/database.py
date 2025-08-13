from sqlmodel import create_engine, Session
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


as_engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI_ASYNC.unicode_string())
AsyncSessLocal = async_sessionmaker(bind=as_engine, autoflush=False, expire_on_commit=False, class_=AsyncSession)

# Основной движок с увеличенным пулом соединений
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI.unicode_string(), 
    pool_pre_ping=True,
    pool_size=20,  # Увеличено с 5 до 20
    max_overflow=30,  # Увеличено с 10 до 30 (итого 50 соединений)
    pool_timeout=60,  # Увеличен таймаут до 60 секунд
    pool_recycle=3600,  # Переиспользовать соединения через 1 час
    echo=False  # Отключаем SQL логирование для производительности
)
SessionLocal = sessionmaker(bind=engine, class_=Session)

# Отдельный движок для Celery с собственным пулом
celery_engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI.unicode_string(),
    pool_pre_ping=True,
    pool_size=20,  # Меньший пул для Celery
    max_overflow=30,  # Итого 30 соединений для Celery
    pool_timeout=30,
    pool_recycle=3600,
    echo=False
)
CelerySessionLocal = sessionmaker(bind=celery_engine, class_=Session)


# Dependency
def get_db():
    with Session(engine) as session:
        try:
            yield session
        finally:
            session.close()


async def get_async_db():
    async with AsyncSessLocal() as db:
        yield db
        await db.close()
