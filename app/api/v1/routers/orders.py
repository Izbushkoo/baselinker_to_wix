from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Header, Request
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import Session, select, func, text
from datetime import timedelta, datetime
from fastapi.templating import Jinja2Templates
import os
import logging
import redis
import json
from app.api.deps import get_db, get_session
from app.models.allegro_token import AllegroToken
from app.models.allegro_order import (
    AllegroOrder, AllegroBuyer, AllegroLineItem, OrderLineItem
)
from app.schemas.user import User
from app.services.allegro.data_access import get_token_by_id_sync, get_tokens_list_sync, get_token_by_id
from app.celery_app import celery
from app.utils.date_utils import parse_date
from app.api import deps
from app.services.allegro.allegro_api_service import AsyncAllegroApiService
from app.data_access.allegro_order_repository import AllegroOrderRepository
from app.services.allegro.tokens import check_token
from app.utils.logging_config import logger

web_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@web_router.get("/orders")
async def get_orders(
    request: Request,
    db: AsyncSession = Depends(deps.get_async_session),
    current_user: User = Depends(deps.get_current_user_from_cookie)
):
    return templates.TemplateResponse("orders.html", {"request": request})
