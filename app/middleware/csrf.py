import uuid
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.templating import _TemplateResponse

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            # Получаем сессию из запроса
            session = request.session
            csrf_token = session.get('csrf_token')

            if request.method == "GET":
                # Генерируем новый CSRF токен для GET запросов, если его нет
                if not csrf_token:
                    csrf_token = str(uuid.uuid4())
                    session['csrf_token'] = csrf_token
                # Сохраняем токен в request.state для использования в шаблонах
                request.state.csrf_token = csrf_token
            elif request.method in ["POST", "PUT", "DELETE", "PATCH"]:
                # Проверяем CSRF токен для небезопасных методов
                client_token = request.headers.get("X-CSRF-Token")
                if not client_token or client_token != csrf_token:
                    raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
            
            response = await call_next(request)
            
            # Добавляем CSRF токен в контекст шаблона
            if isinstance(response, _TemplateResponse):
                response.context['csrf_token'] = csrf_token
                
            return response
        except AttributeError:
            # Если сессия недоступна, пропускаем CSRF проверку
            return await call_next(request) 