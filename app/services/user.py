from typing import Optional, Sequence

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.security import get_password_hash, verify_password
from app.models import user as user_models
from app.schemas import user as user_schemas


async def authenticate(db: AsyncSession, email: str, password: str) -> Optional[user_schemas.User]:
    user = await get_user_by_email(db, email=email)
    if not user:
        return None
    if not verify_password(plain_password=password, hashed_password=user.password):  # noqa
        return None
    return user


async def get_user_by_id(db: AsyncSession, user_id: int) -> user_schemas.User:
    async with db as session:
        statement = select(user_models.User).where(user_models.User.id == user_id)
        res = await session.exec(statement=statement)
        return res.first()


async def get_user_by_email(db: AsyncSession, email: str) -> user_schemas.User:
    async with db as session:
        result = await session.exec(select(user_models.User).where(user_models.User.email == email))
        return result.first()


async def get_users(db: AsyncSession, skip: int = 0, limit: int = 100) -> Sequence[user_schemas.User]:
    async with db as session:
        results = await session.exec(select(user_models.User).offset(skip).limit(limit))
        return results.all()


async def create_user(db: AsyncSession, user: user_schemas.UserCreate) -> user_schemas.User:
    user.password = get_password_hash(user.password)
    db_user = user_models.User(**user.model_dump())
    async with db as session:
        session.add(db_user)
        await session.commit()
        await session.refresh(db_user)
        return db_user


async def update_user(db: AsyncSession, db_user: user_models.User, user: user_schemas.UserUpdate) -> user_schemas.User:
    # Update model class variable from requested fields
    for var, value in vars(user).items():
        setattr(db_user, var, value) if value is not None else None
    db_user.password = get_password_hash(user.password)
    async with db as session:
        session.add(db_user)
        await session.commit()
        await session.refresh(db_user)
        return db_user
