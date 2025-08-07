import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlmodel import Session

from app.api.deps import get_session
from app.schemas.stock_synchronization import (
    StockDeductionWebhookRequest,
    StockDeductionWebhookResponse
)
from app.services.stock_synchronization_service import StockSynchronizationService

logger = logging.getLogger("allegro.webhooks")

router = APIRouter(prefix="/webhook", tags=["allegro-webhooks"])


@router.post("/stock-deduction", response_model=StockDeductionWebhookResponse)
async def handle_stock_deduction_webhook(
    request: Request,
    webhook_data: StockDeductionWebhookRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
) -> StockDeductionWebhookResponse:
    """
    Обработка вебхука списания товара от микросервиса Allegro.
    
    Args:
        webhook_data: Данные о списании товара
        background_tasks: Фоновые задачи для дополнительной обработки
        session: Сессия базы данных
        
    Returns:
        StockDeductionWebhookResponse: Результат обработки вебхука
    """
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(
        f"Received stock deduction webhook from {client_ip}: "
        f"token_id={webhook_data.token_id}, order_id={webhook_data.order_id}, "
        f"sku={webhook_data.sku}, quantity={webhook_data.quantity}, "
        f"warehouse={webhook_data.warehouse}"
    )
    
    try:
        # Инициализируем сервис синхронизации
        sync_service = StockSynchronizationService(session=session)
        
        # Выполняем синхронное списание
        sync_result = sync_service.sync_stock_deduction(
            token_id=webhook_data.token_id,
            order_id=webhook_data.order_id,
            sku=webhook_data.sku,
            quantity=webhook_data.quantity,
            warehouse=webhook_data.warehouse
        )
        
        if sync_result.success:
            logger.info(
                f"Stock deduction processed successfully: "
                f"operation_id={sync_result.operation_id}, "
                f"order_id={webhook_data.order_id}"
            )
            
            return StockDeductionWebhookResponse(
                success=True,
                operation_id=sync_result.operation_id,
                message="Stock deduction processed successfully",
                details=sync_result.details
            )
        else:
            # Операция создана, но синхронизация не удалась - будет повторена
            logger.warning(
                f"Stock deduction queued for retry: "
                f"operation_id={sync_result.operation_id}, "
                f"order_id={webhook_data.order_id}, "
                f"error={sync_result.error}"
            )
            
            return StockDeductionWebhookResponse(
                success=True,  # Операция принята, даже если не синхронизирована сразу
                operation_id=sync_result.operation_id,
                message="Stock deduction queued for processing",
                details=sync_result.details
            )
            
    except Exception as e:
        logger.error(
            f"Error processing stock deduction webhook: "
            f"order_id={webhook_data.order_id}, "
            f"sku={webhook_data.sku}, "
            f"error={str(e)}"
        )
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process stock deduction: {str(e)}"
        )


@router.post("/test-connectivity")
async def test_webhook_connectivity(
    request: Request
) -> Dict[str, Any]:
    """
    Тестовый эндпоинт для проверки связности с микросервисом.
    
    Returns:
        Dict[str, Any]: Информация о статусе подключения
    """
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(f"Webhook connectivity test from {client_ip}")
    
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",
        "client_ip": client_ip,
        "timestamp": "2025-01-01T00:00:00Z"  # Будет заменено на актуальное время
    }


@router.get("/health")
async def webhook_health_check() -> Dict[str, Any]:
    """
    Проверка здоровья вебхук-эндпоинта.
    
    Returns:
        Dict[str, Any]: Статус здоровья сервиса
    """
    return {
        "status": "healthy",
        "service": "allegro-webhooks",
        "version": "1.0.0",
        "endpoints": [
            "/webhook/stock-deduction",
            "/webhook/test-connectivity",
            "/webhook/health"
        ]
    }