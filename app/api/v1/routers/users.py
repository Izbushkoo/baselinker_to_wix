from typing import Any, List

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic.networks import EmailStr
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.core.config import settings
from app.services.user import (
    get_user_by_id,
    get_user_by_email,
    create_user,
    get_users,
    update_user,
    delete_user,
    toggle_admin_status_by_id,
)
from app.models.user import User as UserModel
from app.schemas.user import User, UserCreate, UserUpdate

router = APIRouter()


@router.get("/", response_model=List[User])
async def read_users(
    db: AsyncSession = Depends(deps.get_async_session),
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve users.
    """
    users = await get_users(db, skip=skip, limit=limit)
    return users


@router.post("/", response_model=User)
async def create_user_route(
    *,
    db: AsyncSession = Depends(deps.get_async_session),
    user_in: UserCreate,
) -> Any:
    """
    Create new user.
    """
    user = await get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    user = await create_user(db, user_in)
    return user


@router.put("/me", response_model=User)
async def update_user_me(
    *,
    db: AsyncSession = Depends(deps.get_async_session),
    password: str = Body(None),
    full_name: str = Body(None),
    email: EmailStr = Body(None),
    current_user: UserModel = Depends(deps.get_current_user),
) -> Any:
    """
    Update own user.
    """
    current_user_data = jsonable_encoder(current_user)
    user_in = UserUpdate(**current_user_data)
    if password is not None:
        user_in.password = password
    if full_name is not None:
        user_in.full_name = full_name
    if email is not None:
        user_in.email = email
    user = await update_user(db, db_obj=current_user, obj_in=user_in)
    return user

@router.put("/{email}/toggle-admin", response_model=User)
async def toggle_admin_status(
    email: str,
    *,
    db: AsyncSession = Depends(deps.get_async_session),
) -> Any:
    """
    Переключение статуса администратора для пользователя.
    Только для администраторов.
    """
    user = await get_user_by_email(db, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден"
        )

    # Создаем объект обновления с противоположным значением is_admin
    return await toggle_admin_status_by_id(db, user.id)


@router.get("/me", response_model=User)
async def read_user_me(
    current_user: UserModel = Depends(deps.get_current_user),
) -> Any:
    """
    Get current user.
    """
    return current_user


@router.delete("/me", response_model=User)
async def delete_user_me(
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: UserModel = Depends(deps.get_current_user),
) -> Any:
    """
    Delete own user.
    """
    user = await delete_user(db, current_user.id)
    return user

