from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.product import ProductCreate, ProductResponse
from app.db.database import get_db
from app.db.crud import create_product, get_products

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/products/add", response_class=HTMLResponse)
async def add_product_form(request: Request):
    """Отображает форму добавления нового товара."""
    return templates.TemplateResponse(
        "add_product.html",
        {"request": request}
    )

@router.post("/api/products", response_model=ProductResponse)
async def create_new_product(
    product: ProductCreate,
    db: AsyncSession = Depends(get_db)
):
    """Создает новый товар в базе данных."""
    try:
        db_product = await create_product(db, product)
        return db_product
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось создать товар: {str(e)}"
        )

@router.get("/api/products")
async def get_product_list(
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Получает список товаров с пагинацией и поиском."""
    try:
        products, total = await get_products(
            db,
            page=page,
            page_size=page_size,
            search=search
        )
        
        return {
            "products": products,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Ошибка при получении списка товаров: {str(e)}"
        ) 