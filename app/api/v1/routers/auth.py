from datetime import timedelta
from typing import Any
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.templating import Jinja2Templates

from app.core import security
from app.core.config import settings
from app.api import deps
from app.services.user import authenticate, create_user, get_user_by_email
from app.schemas.user import User, UserCreate
from app.schemas.token_ import Token

logger = logging.getLogger(__name__)

# Роутер для API
router = APIRouter()

# Роутер для веб-страниц
web_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@web_router.get("/login", name="login")
async def login_page(request: Request):
    """
    Страница входа
    """
    return templates.TemplateResponse("login.html", {"request": request})

@web_router.get("/register", name="register")
async def register_page(request: Request):
    """
    Страница регистрации
    """
    return templates.TemplateResponse("register.html", {"request": request})

# API endpoints
@router.post("/login/access-token")
async def login_access_token(
    response: Response,
    db: AsyncSession = Depends(deps.get_async_session),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> JSONResponse:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    logger.info(f"Login attempt for user: {form_data.username}")
    
    try:
        user = await authenticate(db, email=form_data.username, password=form_data.password)
        if not user:
            logger.warning(f"Authentication failed for user: {form_data.username}")
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"}
            )
        elif not user.is_active:
            logger.warning(f"Inactive user attempted to login: {form_data.username}")
            raise HTTPException(
                status_code=400,
                detail="Inactive user",
                headers={"WWW-Authenticate": "Bearer"}
            )
            
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
        response.set_cookie(
                key="access_token",                # имя cookie
                value=token,                # само значение JWT
                httponly=True,                     # нельзя достать из JS
                secure=False,                       # true в продакшене (HTTPS)
                samesite="lax",                    # защищает от CSRF при кросс-сайтовых GET
                max_age=60 * 60 * 24 * 7,          # живёт неделю
                path="/",                          # доступно на всём сайте
            )
        logger.info(f"Login successful for user: {form_data.username}")
        return {
                    "access_token": token,
                    "token_type": "bearer"
                },
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login for user {form_data.username}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )

@router.post("/register", response_model=User)
async def register_user(
    *,
    db: AsyncSession = Depends(deps.get_async_session),
    user_in: UserCreate,
) -> Any:
    """
    Create new user.
    """
    logger.info(f"Registration attempt for email: {user_in.email}")
    
    try:
        user = await get_user_by_email(db, email=user_in.email)
        if user:
            logger.warning(f"Registration failed - user already exists: {user_in.email}")
            raise HTTPException(
                status_code=400,
                detail="The user with this username already exists in the system.",
            )
        user = await create_user(db, user_in)
        logger.info(f"User registered successfully: {user_in.email}")
        return user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during registration for email {user_in.email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return JSONResponse({"msg": "Logged out"})