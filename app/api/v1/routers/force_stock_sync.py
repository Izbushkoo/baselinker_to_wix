"""
 * @file: force_stock_sync.py
 * @description: API эндпоинты для принудительной синхронизации остатков с WebSocket поддержкой
 * @dependencies: ForceSyncWebSocketManager, FastAPI WebSocket
 * @created: 2025-01-19
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from pydantic import BaseModel

from app.database import SessionLocal
from app.models.warehouse import Product
from app.models.allegro_token import AllegroToken
from app.services.force_sync_websocket_manager import websocket_manager


# Модели данных
class StartForceSyncRequest(BaseModel):
    account_names: Optional[List[str]] = None
    account_ids: Optional[List[str]] = None
    selected_products: Optional[List[str]] = None  # Просто список SKU


class ForceSyncResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


# Создаем роутеры
router = APIRouter()
web_router = APIRouter()


@router.get("/accounts")
async def get_available_accounts():
    """Получение списка доступных аккаунтов для синхронизации"""
    try:
        logging.info("Запрос токенов из микросервиса...")
        tokens_response = websocket_manager.token_client.get_tokens(active_only=True)
        logging.info(f"Получено токенов: {len(tokens_response.items) if tokens_response.items else 0}")
        
        accounts = [
            {
                "id": token["id"],
                "name": token["account_name"],
                "status": "active"
            }
            for token in tokens_response.items
        ]
        logging.info(f"Возвращаем аккаунты: {accounts}")
        return {"accounts": accounts}
    except Exception as e:
        logging.error(f"Ошибка получения аккаунтов: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка получения аккаунтов: {str(e)}")


@router.post("/start", response_model=ForceSyncResponse)
async def start_force_sync(request: StartForceSyncRequest):
    """Создание сессии для принудительной синхронизации"""
    try:
        session_id = str(uuid4())
        
        # Сохраняем параметры синхронизации для WebSocket
        websocket_manager.pending_sessions[session_id] = {
            "account_names": request.account_names,
            "account_ids": request.account_ids,
            "selected_products": request.selected_products,  # Просто список SKU
            "created_at": time.time()
        }
        
        return ForceSyncResponse(
            success=True,
            session_id=session_id,
            message=f"Сессия создана. Подключитесь к WebSocket: /ws/force-sync/{session_id}"
        )
        
    except Exception as e:
        logging.error(f"Ошибка создания сессии синхронизации: {e}")
        return ForceSyncResponse(
            success=False,
            error=str(e)
        )


@router.post("/pause/{session_id}")
async def pause_sync_session(session_id: str):
    """Приостановка сессии синхронизации"""
    try:
        await websocket_manager.pause_session(session_id)
        return {"success": True, "message": "Сессия приостановлена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка приостановки сессии: {str(e)}")


@router.post("/resume/{session_id}")
async def resume_sync_session(session_id: str):
    """Возобновление сессии синхронизации"""
    try:
        await websocket_manager.resume_session(session_id)
        return {"success": True, "message": "Сессия возобновлена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка возобновления сессии: {str(e)}")


@router.post("/cancel/{session_id}")
async def cancel_sync_session(session_id: str):
    """Отмена сессии синхронизации"""
    try:
        await websocket_manager.cancel_session(session_id)
        return {"success": True, "message": "Сессия отменена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка отмены сессии: {str(e)}")


@router.post("/rollback-task/{session_id}/{task_key}")
async def rollback_task(session_id: str, task_key: str):
    """Откат стока для отдельной задачи"""
    try:
        result = await websocket_manager.rollback_task(session_id, task_key)
        return result
    except Exception as e:
        logging.error(f"Ошибка отката задачи {task_key} в сессии {session_id}: {e}")
        return {"success": False, "error": str(e)}


@router.post("/rollback-session/{session_id}")
async def rollback_session(session_id: str):
    """Откат стока для всей сессии"""
    try:
        result = await websocket_manager.rollback_session(session_id)
        return result
    except Exception as e:
        logging.error(f"Ошибка отката сессии {session_id}: {e}")
        return {"success": False, "error": str(e)}


@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    """Получение данных сессии синхронизации"""
    try:
        session = websocket_manager.active_sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Сессия не найдена"}
        
        # Конвертируем Pydantic модели в словари
        session_data = session.model_dump()
        session_data['tasks'] = {k: v.model_dump() for k, v in session.tasks.items()}
        
        return {"success": True, "data": session_data}
    except Exception as e:
        logging.error(f"Ошибка получения данных сессии {session_id}: {e}")
        return {"success": False, "error": str(e)}


@router.post("/retry/{session_id}/{task_key}")
async def retry_task(session_id: str, task_key: str):
    """Повторный запуск задачи синхронизации"""
    try:
        await websocket_manager.retry_task(session_id, task_key)
        return {"success": True, "message": "Задача перезапущена"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка перезапуска задачи: {str(e)}")


@router.get("/status/{session_id}")
async def get_session_status(session_id: str):
    """Получение статуса сессии синхронизации"""
    try:
        status = await websocket_manager.get_session_status(session_id)
        if not status:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения статуса: {str(e)}")


@web_router.websocket("/ws/force-sync/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket эндпоинт для мониторинга принудительной синхронизации"""
    await websocket_manager.connect(websocket, session_id)
    
    try:
        while True:
            # Получаем сообщения от клиента
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Обрабатываем команды от клиента
            command = message.get("command")
            
            if command == "pause":
                await websocket_manager.pause_session(session_id)
            elif command == "resume":
                await websocket_manager.resume_session(session_id)
            elif command == "cancel":
                await websocket_manager.cancel_session(session_id)
            elif command == "retry":
                task_key = message.get("task_key")
                if task_key:
                    await websocket_manager.retry_task(session_id, task_key)
            elif command == "get_status":
                status = await websocket_manager.get_session_status(session_id)
                await websocket_manager.send_message(session_id, {
                    "type": "status_response",
                    "data": status
                })
                
    except WebSocketDisconnect:
        await websocket_manager.disconnect(session_id)
    except Exception as e:
        logging.error(f"Ошибка WebSocket для сессии {session_id}: {e}")
        await websocket_manager.disconnect(session_id)