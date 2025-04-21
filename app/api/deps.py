from typing import Generator, AsyncGenerator, Optional
import logging
from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Session
from typing import AsyncGenerator
from app.core import security
from app.core.config import settings
from app.database import get_db, get_async_db
from app.models.user import User as UserModel
from app.schemas.token_ import TokenPayload
from app.services.user import get_user_by_id

logger = logging.getLogger(__name__)

# Изменяем конфигурацию OAuth2, чтобы избежать рекурсии
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token",
    auto_error=False
)


def get_session() -> Generator[Session, None, None]:
    return get_db()

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_async_db():
        yield session


async def get_token_from_header(request: Request) -> Optional[str]:
    """Extract token from Authorization header without using OAuth2PasswordBearer."""
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.replace("Bearer ", "")

async def get_current_user(
    db: AsyncSession = Depends(get_async_session),
    token: str = Depends(reusable_oauth2)
) -> UserModel:
    """Get current user from token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
        token_data = TokenPayload(**payload)
    except (jwt.exceptions.PyJWTError, ValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Could not validate credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await get_user_by_id(db, user_id=token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user_optional(
    access_token: str = Cookie(None),       # читаем cookie
    db: AsyncSession = Depends(get_async_session),
) -> UserModel:
    if not access_token:
        return None
    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM]
        )
        user_id: int = int(payload.get("sub"))
    except (jwt.exceptions.PyJWTError, ValidationError):
        return None
    user = await db.get(UserModel, user_id)
    if not user:
        return None
    return user

async def get_current_user_from_cookie(
    access_token: str = Cookie(None),
    db: AsyncSession = Depends(get_async_session)
) -> UserModel:
    """Get current user from cookie token."""
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = jwt.decode(
            access_token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM]
        )
        user_id: int = int(payload.get("sub"))
    except (jwt.exceptions.PyJWTError, ValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Could not validate credentials: {str(e)}"
        )
    user = await get_user_by_id(db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user