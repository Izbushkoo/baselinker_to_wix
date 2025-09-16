"""
 * @file: force_sync_websocket_manager.py
 * @description: Единый WebSocket менеджер для принудительной синхронизации остатков
 * @dependencies: FastAPI WebSocket, Allegro Microservice, Database models
 * @created: 2025-01-16
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Set
from enum import Enum

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import SessionLocal
from app.models.warehouse import Product
from app.models.allegro_token import AllegroToken
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.services.Allegro_Microservice.offers_endpoint import AllegroOffersMicroserviceClient
from app.core.config import settings
from app.core.security import create_access_token

class TaskStatus(str, Enum):
    """Статусы задач синхронизации"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class SessionStatus(str, Enum):
    """Статусы сессии синхронизации"""
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class SyncTask(BaseModel):
    """Задача синхронизации товара с аккаунтом"""
    sku: str
    account_name: str
    account_id: str
    status: TaskStatus = TaskStatus.PENDING
    error_message: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    old_stock: Optional[int] = None
    new_stock: Optional[int] = None


class SyncSession(BaseModel):
    """Сессия синхронизации"""
    session_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    total_tasks: int = 0
    completed_tasks: int = 0
    error_tasks: int = 0
    processing_tasks: int = 0
    tasks: Dict[str, SyncTask] = Field(default_factory=dict)
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class ForceSyncWebSocketManager:
    """Единый менеджер WebSocket для принудительной синхронизации остатков"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.active_sessions: Dict[str, SyncSession] = {}
        self.pending_sessions: Dict[str, dict] = {}  # Ожидающие сессии
        self.logger = logging.getLogger("force_sync.websocket")
        
        # Инициализируем клиенты микросервиса
        jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
        self.token_client = AllegroTokenMicroserviceClient(jwt_token)
        self.offers_client = AllegroOffersMicroserviceClient(jwt_token)
        
    async def connect(self, websocket: WebSocket, session_id: str):
        """Подключение WebSocket клиента"""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.logger.info(f"WebSocket подключен для сессии {session_id}")
        
        # Если есть ожидающая сессия, запускаем синхронизацию
        if session_id in self.pending_sessions:
            pending_data = self.pending_sessions[session_id]
            del self.pending_sessions[session_id]
            
            self.logger.info(f"Запуск синхронизации для ожидающей сессии {session_id}")
            await self.start_force_sync(
                session_id=session_id,
                account_names=pending_data["account_names"]
            )
        
    async def disconnect(self, session_id: str):
        """Отключение WebSocket клиента"""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
        self.logger.info(f"WebSocket отключен для сессии {session_id}")
        
    async def send_message(self, session_id: str, message: dict):
        """Отправка сообщения клиенту"""
        if session_id in self.active_connections:
            try:
                self.logger.info(f"Отправка сообщения для сессии {session_id}: {message['type']}")
                await self.active_connections[session_id].send_text(json.dumps(message))
            except Exception as e:
                self.logger.error(f"Ошибка отправки сообщения для сессии {session_id}: {e}")
                await self.disconnect(session_id)
        else:
            self.logger.warning(f"Нет активного соединения для сессии {session_id}")
                
    async def start_force_sync(self, session_id: str, account_names: List[str] = None) -> dict:
        """Запуск принудительной синхронизации всех товаров"""
        try:
            self.logger.info(f"Запуск принудительной синхронизации для сессии {session_id}")
            
            # Создаем сессию
            session = SyncSession(
                session_id=session_id,
                start_time=time.time()
            )
            self.active_sessions[session_id] = session
            
            # Получаем все товары из базы
            with SessionLocal() as db:
                products_query = select(Product)
                products = db.exec(products_query).all()
                self.logger.info(f"Найдено товаров в базе: {len(products)}")
                
            # Получаем токены из микросервиса
            tokens_response = self.token_client.get_tokens(active_only=True)
            tokens = tokens_response.items
            self.logger.info(f"Получено токенов: {len(tokens)}")
            
            # Фильтруем токены по выбранным аккаунтам
            if account_names:
                tokens = [token for token in tokens if token['account_name'] in account_names]
                self.logger.info(f"Отфильтровано токенов: {len(tokens)}")
            
            # Создаем задачи синхронизации
            tasks = []
            for product in products:
                for token in tokens:
                    task_key = f"{product.sku}_{token['account_name']}"
                    task = SyncTask(
                        sku=product.sku,
                        account_name=token['account_name'],
                        account_id=token['id']
                    )
                    session.tasks[task_key] = task
                    tasks.append(task_key)
            
            session.total_tasks = len(tasks)
            self.logger.info(f"Создано задач: {session.total_tasks}")
            
            # Отправляем начальную информацию
            await self.send_session_update(session_id)
            
            # Запускаем обработку задач
            asyncio.create_task(self._process_tasks(session_id, tasks))
            self.logger.info(f"Запущена обработка задач для сессии {session_id}")
            
            return {
                "success": True,
                "session_id": session_id,
                "total_tasks": session.total_tasks,
                "message": f"Запущена принудительная синхронизация {len(products)} товаров для {len(tokens)} аккаунтов"
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска синхронизации для сессии {session_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _process_tasks(self, session_id: str, task_keys: List[str]):
        """Обработка задач синхронизации"""
        self.logger.info(f"Начало обработки {len(task_keys)} задач для сессии {session_id}")
        session = self.active_sessions.get(session_id)
        if not session:
            self.logger.error(f"Сессия {session_id} не найдена")
            return
            
        for i, task_key in enumerate(task_keys):
            self.logger.info(f"Обработка задачи {i+1}/{len(task_keys)}: {task_key}")
            
            if session.status == SessionStatus.CANCELLED:
                self.logger.info(f"Сессия {session_id} отменена, прерываем обработку")
                break
                
            if session.status == SessionStatus.PAUSED:
                self.logger.info(f"Сессия {session_id} приостановлена, ждем возобновления")
                # Ждем возобновления
                while session.status == SessionStatus.PAUSED:
                    await asyncio.sleep(0.5)
                    
            task = session.tasks[task_key]
            
            # Добавляем задержку перед обработкой каждого товара (временно увеличено для тестирования)
            await asyncio.sleep(0.2)
            
            await self._process_single_task(session_id, task_key, task)
            
        # Завершаем сессию
        self.logger.info(f"Завершение сессии {session_id}")
        session.status = SessionStatus.COMPLETED
        session.end_time = time.time()
        await self.send_session_update(session_id)
        
    async def _process_single_task(self, session_id: str, task_key: str, task: SyncTask):
        """Обработка одной задачи синхронизации"""
        self.logger.info(f"Начало обработки задачи {task_key}: {task.sku} для {task.account_name}")
        session = self.active_sessions.get(session_id)
        if not session:
            self.logger.error(f"Сессия {session_id} не найдена для задачи {task_key}")
            return
            
        try:
            # Обновляем статус на "обрабатывается"
            task.status = TaskStatus.PROCESSING
            task.start_time = time.time()
            session.processing_tasks += 1
            
            await self.send_task_update(session_id, task_key, task)
            
            # Выполняем синхронизацию через микросервис
            self.logger.info(f"Вызов синхронизации для {task.sku} с токеном {task.account_id}")
            result = await self._sync_product_stock(task.sku, task.account_id)
            
            self.logger.info(f"Результат синхронизации для {task.sku}: {result}")
            
            if result.get("success"):
                task.status = TaskStatus.SUCCESS
                task.new_stock = result.get("new_stock")
                task.old_stock = result.get("old_stock")
                session.completed_tasks += 1
                self.logger.info(f"Задача {task_key} завершена успешно")
            else:
                task.status = TaskStatus.ERROR
                error_msg = result.get("error", "Неизвестная ошибка")
                # Улучшаем сообщение об ошибке
                if "404 Client Error" in error_msg and "offers/update-stock-single" in error_msg:
                    task.error_message = "Товар не найден в аккаунте Allegro"
                elif "404 Client Error" in error_msg:
                    task.error_message = "Микросервис недоступен - проверьте подключение"
                elif "Connection" in error_msg:
                    task.error_message = "Ошибка подключения к микросервису"
                elif "timeout" in error_msg.lower():
                    task.error_message = "Превышено время ожидания ответа"
                elif "500" in error_msg:
                    task.error_message = "Внутренняя ошибка сервера микросервиса"
                else:
                    task.error_message = error_msg
                session.error_tasks += 1
                self.logger.error(f"Задача {task_key} завершена с ошибкой: {task.error_message}")
                
        except Exception as e:
            task.status = TaskStatus.ERROR
            error_msg = str(e)
            # Улучшаем сообщение об ошибке для исключений
            if "404 Client Error" in error_msg and "offers/update-stock-single" in error_msg:
                task.error_message = "Товар не найден в аккаунте Allegro"
            elif "404 Client Error" in error_msg:
                task.error_message = "Микросервис недоступен - проверьте подключение"
            elif "Connection" in error_msg:
                task.error_message = "Ошибка подключения к микросервису"
            elif "timeout" in error_msg.lower():
                task.error_message = "Превышено время ожидания ответа"
            elif "500" in error_msg:
                task.error_message = "Внутренняя ошибка сервера микросервиса"
            else:
                task.error_message = f"Системная ошибка: {error_msg}"
            session.error_tasks += 1
            self.logger.error(f"Ошибка обработки задачи {task_key}: {task.error_message}")
            
        finally:
            task.end_time = time.time()
            session.processing_tasks -= 1
            await self.send_task_update(session_id, task_key, task)
            await self.send_session_update(session_id)
            
    async def _sync_product_stock(self, sku: str, token_id: str, custom_stock: Optional[int] = None) -> dict:
        """Синхронизация остатков товара через микросервис"""
        try:
            if custom_stock is not None:
                # Используем кастомное значение стока (для отката)
                total_stock = custom_stock
                self.logger.info(f"Использование кастомного стока для {sku}: {total_stock}")
            else:
                # Получаем текущий остаток товара из базы
                self.logger.info(f"Получение товара {sku} из базы")
                with SessionLocal() as db:
                    # Получаем товар с остатками в одной сессии
                    product_query = select(Product).where(Product.sku == sku)
                    product = db.exec(product_query).first()
                    
                    if not product:
                        self.logger.error(f"Товар {sku} не найден в базе")
                        return {"success": False, "error": f"Товар {sku} не найден в базе"}
                    
                    # Получаем общий остаток по всем складам в той же сессии
                    total_stock = sum(stock.quantity for stock in product.stocks)
                    self.logger.info(f"Товар {sku} найден, общий остаток: {total_stock}")
            
            # Вызываем микросервис для обновления остатков
            self.logger.info(f"Вызов микросервиса для обновления остатков {sku}")
            result = self.offers_client.update_stock_single(
                token_id=token_id,
                external_id=sku,
                stock=total_stock
            )
            
            self.logger.info(f"Результат микросервиса для {sku}: success={result.success}")
            
            if result.success:
                # Получаем данные из первого оффера (если есть)
                old_stock = None
                new_stock = None
                if result.offers and len(result.offers) > 0:
                    first_offer = result.offers[0]
                    old_stock = first_offer.old_stock
                    new_stock = first_offer.new_stock
                
                self.logger.info(f"Успешная синхронизация {sku}: {old_stock} -> {new_stock}")
                return {
                    "success": True,
                    "old_stock": old_stock,
                    "new_stock": new_stock,
                    "updated_offers": result.updated_offers,
                    "total_offers": result.total_offers
                }
            else:
                self.logger.error(f"Ошибка синхронизации {sku}: {result}")
                return {
                    "success": False,
                    "error": "Ошибка синхронизации"
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def pause_session(self, session_id: str):
        """Приостановка сессии синхронизации"""
        session = self.active_sessions.get(session_id)
        if session and session.status == SessionStatus.ACTIVE:
            session.status = SessionStatus.PAUSED
            await self.send_session_update(session_id)
            
    async def resume_session(self, session_id: str):
        """Возобновление сессии синхронизации"""
        session = self.active_sessions.get(session_id)
        if session and session.status == SessionStatus.PAUSED:
            session.status = SessionStatus.ACTIVE
            await self.send_session_update(session_id)
            
    async def cancel_session(self, session_id: str):
        """Отмена сессии синхронизации"""
        session = self.active_sessions.get(session_id)
        if session:
            session.status = SessionStatus.CANCELLED
            await self.send_session_update(session_id)
            
    async def retry_task(self, session_id: str, task_key: str):
        """Повторный запуск задачи"""
        session = self.active_sessions.get(session_id)
        if session and task_key in session.tasks:
            task = session.tasks[task_key]
            
            # Убираем задачу из счетчиков, если она была завершена
            if task.status == TaskStatus.SUCCESS:
                session.completed_tasks -= 1
            elif task.status == TaskStatus.ERROR:
                session.error_tasks -= 1
            
            # Сбрасываем статус задачи
            task.status = TaskStatus.PENDING
            task.error_message = None
            task.start_time = None
            task.end_time = None
            task.old_stock = None
            task.new_stock = None
            
            # Отправляем обновление сессии
            await self.send_session_update(session_id)
            
            # Запускаем обработку задачи
            asyncio.create_task(self._process_single_task(session_id, task_key, task))
            
    async def rollback_task(self, session_id: str, task_key: str):
        """Откат стока для отдельной задачи"""
        session = self.active_sessions.get(session_id)
        if session and task_key in session.tasks:
            task = session.tasks[task_key]
            
            # Проверяем, что задача была успешной и есть данные для отката
            if task.status == TaskStatus.SUCCESS and task.old_stock is not None:
                self.logger.info(f"Откат стока для задачи {task_key}: {task.new_stock} -> {task.old_stock}")
                
                # Выполняем откат через микросервис
                result = await self._sync_product_stock(task.sku, task.account_id, custom_stock=task.old_stock)
                
                if result.get("success"):
                    # Обновляем данные задачи
                    task.new_stock = task.old_stock
                    task.old_stock = result.get("old_stock", task.old_stock)
                    
                    # Отправляем обновление
                    await self.send_task_update(session_id, task_key, task)
                    await self.send_session_update(session_id)
                    
                    return {"success": True, "message": f"Сток откачен: {task.new_stock} -> {task.old_stock}"}
                else:
                    return {"success": False, "error": "Ошибка отката стока"}
            else:
                return {"success": False, "error": "Нет данных для отката"}
        else:
            return {"success": False, "error": "Задача не найдена"}
            
    async def rollback_session(self, session_id: str):
        """Откат стока для всей сессии"""
        session = self.active_sessions.get(session_id)
        if not session:
            return {"success": False, "error": "Сессия не найдена"}
            
        rollback_results = []
        successful_rollbacks = 0
        
        for task_key, task in session.tasks.items():
            if task.status == TaskStatus.SUCCESS and task.old_stock is not None:
                result = await self.rollback_task(session_id, task_key)
                rollback_results.append({
                    "task_key": task_key,
                    "sku": task.sku,
                    "account_name": task.account_name,
                    "result": result
                })
                
                if result.get("success"):
                    successful_rollbacks += 1
                    
                # Небольшая задержка между откатами
                await asyncio.sleep(0.1)
        
        return {
            "success": True,
            "message": f"Откат завершен: {successful_rollbacks}/{len(rollback_results)} задач",
            "results": rollback_results
        }
            
    async def send_session_update(self, session_id: str):
        """Отправка обновления сессии клиенту"""
        session = self.active_sessions.get(session_id)
        if not session:
            return
            
        message = {
            "type": "session_update",
            "data": {
                "session_id": session_id,
                "status": session.status.value,
                "total_tasks": session.total_tasks,
                "completed_tasks": session.completed_tasks,
                "error_tasks": session.error_tasks,
                "processing_tasks": session.processing_tasks,
                "progress_percent": ((session.completed_tasks + session.error_tasks) / session.total_tasks * 100) if session.total_tasks > 0 else 0,
                "start_time": session.start_time,
                "end_time": session.end_time
            }
        }
        
        await self.send_message(session_id, message)
        
    async def send_task_update(self, session_id: str, task_key: str, task: SyncTask):
        """Отправка обновления задачи клиенту"""
        self.logger.info(f"Отправка обновления задачи {task_key} для сессии {session_id}")
        message = {
            "type": "task_update",
            "data": {
                "task_key": task_key,
                "task": task.model_dump()
            }
        }
        
        await self.send_message(session_id, message)
        
    async def get_session_status(self, session_id: str) -> Optional[dict]:
        """Получение статуса сессии"""
        session = self.active_sessions.get(session_id)
        if not session:
            return None
            
        return {
            "session_id": session_id,
            "status": session.status.value,
            "total_tasks": session.total_tasks,
            "completed_tasks": session.completed_tasks,
            "error_tasks": session.error_tasks,
            "processing_tasks": session.processing_tasks,
            "progress_percent": (session.completed_tasks / session.total_tasks * 100) if session.total_tasks > 0 else 0,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "tasks": {key: task.model_dump() for key, task in session.tasks.items()}
        }


# Глобальный экземпляр менеджера
websocket_manager = ForceSyncWebSocketManager()
