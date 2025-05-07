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
    current_user: Optional[UserModel] = Depends(deps.get_current_user_optional),
    inventory_manager: manager.InventoryManager = Depends(manager.get_manager)
):
    total_items = await inventory_manager.count_products()
    low_stock = await inventory_manager.get_low_stock_products()
    logger.info(f"Total items: {total_items}")
    logger.info(f"Low stock: {low_stock}")

    # Тестовые данные
    test_operations = [
        Operation(
            id=1,
            operation_type=OperationType.PRODUCT_CREATE,
            created_at=datetime.now() - timedelta(hours=2),
            warehouse_id="WH001",
            user_email="admin@example.com",
            products_data={
                "sku": "TEST-SKU-001",
                "name": "Новый тестовый товар",
                "initial_quantity": 100
            },
        ),
        Operation(
            id=2,
            operation_type=OperationType.PRODUCT_DELETE,
            created_at=datetime.now() - timedelta(hours=1),
            user_email="admin@example.com",
            products_data={
                "sku": "TEST-SKU-002"
            },
            comment="Удаление устаревшего товара"
        ),
        # Приход товара
        Operation(
            id=uuid4(),
            operation_type=OperationType.STOCK_IN.value,
            created_at=datetime.now() - timedelta(hours=1),
            warehouse_id="main",
            products_data={"sku": "TEST-SKU-001", "quantity": 10},
            user_email="user@example.com",
            comment="Тестовый приход товара"
        ),
        
        # Массовый приход через файл
        Operation(
            id=uuid4(),
            operation_type=OperationType.STOCK_IN_FILE.value,
            created_at=datetime.now() - timedelta(hours=2),
            warehouse_id="main",
            products_data={
                "products": [
                    {"sku": "TEST-SKU-001", "quantity": 5},
                    {"sku": "TEST-SKU-002", "quantity": 3},
                    {"sku": "TEST-SKU-003", "quantity": 7}
                ]
            },
            user_email="admin@example.com",
            file_name="import_20240306.xlsx",
            comment="Массовый импорт товаров"
        ),
        
        # Списание по заказу
        Operation(
            id=uuid4(),
            operation_type=OperationType.STOCK_OUT_ORDER.value,
            created_at=datetime.now() - timedelta(hours=3),
            warehouse_id="main",
            products_data={"sku": "TEST-SKU-002", "quantity": 1},
            order_id="ORDER-123",
            comment="Списание по заказу"
        ),
        
        # Ручное списание
        Operation(
            id=uuid4(),
            operation_type=OperationType.STOCK_OUT_MANUAL.value,
            created_at=datetime.now() - timedelta(hours=4),
            warehouse_id="main",
            products_data={"sku": "TEST-SKU-003", "quantity": 2},
            user_email="manager@example.com",
            comment="Списание брака"
        ),
        
        # Перемещение между складами
        Operation(
            id=uuid4(),
            operation_type=OperationType.TRANSFER.value,
            created_at=datetime.now() - timedelta(hours=5),
            warehouse_id="main",
            target_warehouse_id="secondary",
            products_data={"sku": "TEST-SKU-001", "quantity": 3},
            user_email="warehouse@example.com",
            comment="Перемещение на другой склад"
        ),
        
        # Массовое перемещение через файл
        Operation(
            id=uuid4(),
            operation_type=OperationType.TRANSFER_FILE.value,
            created_at=datetime.now() - timedelta(hours=6),
            warehouse_id="main",
            target_warehouse_id="secondary",
            products_data={
                "products": [
                    {"sku": "TEST-SKU-001", "quantity": 2},
                    {"sku": "TEST-SKU-002", "quantity": 4},
                    {"sku": "TEST-SKU-003", "quantity": 1}
                ]
            },
            user_email="admin@example.com",
            file_name="transfer_20240306.xlsx",
            comment="Массовое перемещение товаров"
        )
    ]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": current_user,
        "stats": {
            "total_items": total_items,
            "low_stock": low_stock,
            "today_operations": len(test_operations)
        },
        "recent_operations": test_operations
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
