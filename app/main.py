import uvicorn
import logging
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import FileResponse, RedirectResponse
from app.api.v1.api import api_router as api_router_v1, web_router
from app.core.config import settings
from app.utils.logging_config import setup_project_logging
from app.api import deps
from app.models.user import User as UserModel
from sqlalchemy.orm import Session
from app.core import security
from app.services.warehouse import manager
from datetime import datetime, timedelta
from app.models.operations import Operation, OperationType
from uuid import uuid4
from app.services.operations_service import get_operations_service
from app.templates.filters import operation_type_label
from app.tg_app import router as tg_router


# Настраиваем логирование при запуске приложения
from app.utils.logging_config import setup_project_logging, get_logger
setup_project_logging()

app = FastAPI(title=settings.PROJECT_NAME,
              openapi_url=f"{settings.API_V1_STR}/openapi.json",
              docs_url=f"{settings.API_V1_STR}/docs")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Настройка шаблонов и статических файлов
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["operation_type_label"] = operation_type_label
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Настройка логирования
logger = get_logger(__name__)


# Маршруты для веб-интерфейса
@app.get("/")
async def home(
    request: Request,
    current_user: Optional[UserModel] = Depends(deps.get_current_user_optional)
):
    if not current_user:
        return RedirectResponse(url="/login?next=/catalog", status_code=302)

    # Перенаправляем авторизованных пользователей на каталог
    return RedirectResponse(url="/catalog", status_code=302)

@app.get("/status")
async def status_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})



# Подключаем веб-маршруты (без API префикса)
app.include_router(web_router)

# Подключаем Telegram Web App роутер
app.include_router(tg_router)

# API маршруты
app.include_router(api_router_v1, prefix=settings.API_V1_STR)

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True, port=8787)
