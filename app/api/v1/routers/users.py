from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.schemas import user as user_schemas
from app.services import user as user_service

router = APIRouter()


@router.get("/", response_model=List[user_schemas.User])
async def get_users(db: AsyncSession = Depends(deps.get_db_async), skip: int = 0, limit: int = 100) -> Any:
    """Retrieve all users."""
    users = await user_service.get_users(db, skip=skip, limit=limit)
    return users


@router.get("/{user_id}", response_model=user_schemas.User)
async def get_user(*, db: AsyncSession = Depends(deps.get_db_async), user_id: int) -> Any:
    """Get User by ID."""
    user = await user_service.get_user_by_id(db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this ID does not exist in the system",
        )
    return user


@router.post("/", response_model=user_schemas.User)
async def create_user(*, db: AsyncSession = Depends(deps.get_db_async), user_in: user_schemas.UserCreate) -> Any:
    """Create new user."""
    user = await user_service.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    user = await user_service.create_user(db, user=user_in)
    return user


@router.patch("/{user_id}", response_model=user_schemas.User)
async def update_user(*, db: AsyncSession = Depends(deps.get_db_async), user_id: int,
                      user_in: user_schemas.UserUpdate) -> Any:
    """Update User by ID"""
    user = await user_service.get_user_by_id(db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system",
        )
    user = await user_service.update_user(db, db_user=user, user=user_in)
    return user

