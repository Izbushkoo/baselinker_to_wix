from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.templating import Jinja2Templates
from app.api import deps
from app.models.warehouse import Stock, Sale
from app.models.user import User
from app.services.warehouse.manager import Warehouses

router = APIRouter()
web_router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

@web_router.get("/operations")
async def operations_page(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    warehouse: Optional[str] = None,
    type: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Отображение страницы операций с историей и фильтрацией
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/operations", status_code=302)

    # Базовый запрос для получения операций
    query = select(Sale)
    
    # Применяем фильтры
    if warehouse:
        query = query.where(Sale.warehouse == warehouse)
    
    if type:
        query = query.where(Sale.type == type)
    
    # Получаем общее количество операций для пагинации
    total_count_query = select(func.count()).select_from(query.subquery())
    result = await db.exec(total_count_query)
    total_count = result.first()
    
    # Применяем пагинацию и сортировку по дате
    query = (
        query.order_by(Sale.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    # Получаем операции
    result = await db.exec(query)
    operations = result.all()
    
    # Используем список складов из перечисления вместо запроса к базе
    warehouses = [w.value for w in Warehouses]
    
    return templates.TemplateResponse(
        "operations.html",
        {
            "request": request,
            "user": current_user,
            "operations": operations,
            "warehouses": warehouses,
            "page": page,
            "page_size": page_size,
            "total_operations": total_count,
            "total_pages": (total_count + page_size - 1) // page_size,
            "current_user": current_user
        }
    ) 