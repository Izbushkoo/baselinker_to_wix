from sqlmodel import create_engine, Session
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as AS
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


as_engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI_ASYNC.unicode_string())
AsyncSessLocal = async_sessionmaker(bind=as_engine, autoflush=False, expire_on_commit=False, class_=AS)

engine = create_engine(settings.SQLALCHEMY_DATABASE_URI.unicode_string(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, class_=Session)


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
