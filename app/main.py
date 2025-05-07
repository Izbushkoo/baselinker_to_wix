import uvicorn
import logging
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.responses import FileResponse
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


# Настраиваем логирование при запуске приложения
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
logger = logging.getLogger(__name__)


# Маршруты для веб-интерфейса
@app.get("/")
async def home(
    request: Request,
    current_user: Optional[UserModel] = Depends(deps.get_current_user_optional),
    inventory_manager: manager.InventoryManager = Depends(manager.get_manager)
):
    total_items = await inventory_manager.count_products()
    low_stock = await inventory_manager.get_low_stock_products()
    logger.info(f"Total items: {total_items}")
    logger.info(f"Low stock: {low_stock}")

    # Получаем сервис операций
    operations_service = get_operations_service()
    
    # Получаем последние 10 операций
    recent_operations = operations_service.get_latest_operations(limit=50)
    
    # Получаем статистику операций за сегодня
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = datetime.now()
    today_stats = operations_service.get_operations_stats(today_start, today_end)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": current_user,
        "stats": {
            "total_items": total_items,
            "low_stock": low_stock,
            "today_operations": today_stats["total"]
        },
        "recent_operations": recent_operations
    })

@app.get("/status")
async def status_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})



# Подключаем веб-маршруты (без API префикса)
app.include_router(web_router)

# API маршруты
app.include_router(api_router_v1, prefix=settings.API_V1_STR)

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True, port=8787)
