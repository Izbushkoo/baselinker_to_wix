from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.templating import Jinja2Templates
from datetime import datetime
from app.api import deps
from app.models.operations import Operation, OperationType
from app.models.user import User
from app.services.warehouse.manager import Warehouses
from sqlmodel import select, or_, func
from app.templates.filters import operation_type_label

router = APIRouter()
web_router = APIRouter()

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["operation_type_label"] = operation_type_label


@web_router.get("/import-export")
async def import_export_page(
    request: Request,
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Страница импорта/экспорта
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/import-export", status_code=302)

    warehouses = [w.value for w in Warehouses]

    return templates.TemplateResponse(
        "operations.html",
        {
            "request": request,
            "user": current_user,
            "current_user": current_user,
            "warehouses": warehouses
        }
    )


@web_router.get("/operations")
async def operations_page(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    warehouse: Optional[str] = None,
    type: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_optional)
):
    """
    Страница операций с фильтрами: по типу, складу, поиску и диапазону дат
    """
    if not current_user:
        return RedirectResponse(url=f"/login?next=/operations", status_code=302)

    query = select(Operation)

    # Фильтр по складу
    if warehouse:
        query = query.where(Operation.warehouse_id == warehouse)

    # Фильтр по типу операции
    if type:
        query = query.where(Operation.operation_type == type)

    # Фильтр по поиску (номер заказа, email исполнителя)
    if search:
        search = search.strip()
        query = query.where(
            or_(
                Operation.order_id == search,
                Operation.user_email.ilike(f"%{search}%")
            )
        )

    # Фильтр по диапазону дат
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
            query = query.where(Operation.created_at >= date_from_dt)
        except Exception:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
            query = query.where(Operation.created_at <= date_to_dt)
        except Exception:
            pass

    # Получаем общее количество операций для пагинации
    total_count_query = select(func.count()).select_from(query.subquery())
    result = await db.exec(total_count_query)
    total_count = result.first() or 0

    # Пагинация и сортировка
    query = (
        query.order_by(Operation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.exec(query)
    operations = result.all()

    warehouses = [w.value for w in Warehouses]
    operation_types = [ot.value for ot in OperationType]

    return templates.TemplateResponse(
        "operations_list.html",
        {
            "request": request,
            "user": current_user,
            "operations": operations,
            "warehouses": warehouses,
            "operation_types": operation_types,
            "page": page,
            "page_size": page_size,
            "total_operations": total_count,
            "total_pages": (total_count + page_size - 1) // page_size,
            "current_user": current_user,
            "selected_warehouse": warehouse,
            "selected_type": type,
            "search": search or "",
            "date_from": date_from or "",
            "date_to": date_to or ""
        }
    ) 