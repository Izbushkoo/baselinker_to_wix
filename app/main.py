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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Настройка логирования
logger = logging.getLogger(__name__)


# Маршруты для веб-интерфейса
@app.get("/")
async def home(
    request: Request,
    current_user: Optional[UserModel] = Depends(deps.get_current_user_optional)
):
    # logger.info(f"request: {request.headers}")
    # logger.info(f"Current user: {current_user.email if current_user else 'Not authenticated'}")
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": current_user,
        "stats": {
            "total_items": 0,  # Здесь должны быть реальные данные
            "pending_items": 0,
            "low_stock": 0,
            "today_operations": 0
        },
        "recent_operations": []  # Здесь должны быть реальные данные
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
