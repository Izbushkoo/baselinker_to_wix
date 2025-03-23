from typing import Generator, AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import AsyncGenerator
from app.core import security
from app.core.config import settings
from app.database import get_db, get_async_db
from app.models.user import User as UserModel
from app.schemas.token_ import TokenPayload
from app.services.user import get_user_by_id
from sqlmodel import Session

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token")


def get_session() -> Generator[Session, None, None]:
    return get_db()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_async_db():
        yield session


async def get_current_user(db: AsyncSession = Depends(get_async_session),
                           token: str = Depends(reusable_oauth2)) -> UserModel:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
        token_data = TokenPayload(**payload)
    except (jwt.exceptions.PyJWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = await get_user_by_id(db, user_id=token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
