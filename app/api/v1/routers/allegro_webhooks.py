import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Request

from app.database import SessionLocal
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
    webhook_data: StockDeductionWebhookRequest
) -> StockDeductionWebhookResponse:
    """
    Обработка вебхука списания товара от микросервиса Allegro.
    Моментально создаёт операцию обработки заказа для системы синхронизации.
    Детали заказа будут получены позже при обработке операции.
    
    Args:
        webhook_data: token_id и order_id для обработки
        
    Returns:
        StockDeductionWebhookResponse: Результат обработки вебхука
    """
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(
        f"Received stock deduction webhook from {client_ip}: "
        f"token_id={webhook_data.token_id}, order_id={webhook_data.order_id}"
    )
    
    try:
        # Создаём сессию и операцию
        with SessionLocal() as session:
            sync_service = StockSynchronizationService(session=session)
            
            # Создаём одну операцию для обработки заказа
            sync_result = sync_service.create_order_processing_operation(
                token_id=webhook_data.token_id,
                order_id=webhook_data.order_id,
                warehouse="Ирина"
            )
            
            logger.info(
                f"Stock deduction webhook processed: "
                f"order_id={webhook_data.order_id}, "
                f"operation_created={sync_result.success}, "
                f"operation_id={sync_result.operation_id}"
            )
            
            return StockDeductionWebhookResponse(
                success=sync_result.success,
                operations_created=1 if sync_result.success else 0,
                operations_processed=1 if sync_result.success else 0,
                message="Order processing operation created and queued for sync" if sync_result.success else f"Failed to create operation: {sync_result.error}",
                details={
                    "operation_id": str(sync_result.operation_id) if sync_result.operation_id else None,
                    "queued_for_processing": sync_result.success,
                    "error": sync_result.error
                },
                order_details={
                    "order_id": webhook_data.order_id,
                    "token_id": webhook_data.token_id
                }
            )
                
    except Exception as e:
        logger.error(
            f"Unexpected error processing stock deduction webhook: "
            f"token_id={webhook_data.token_id}, "
            f"order_id={webhook_data.order_id}, "
            f"error={str(e)}"
        )
        
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error processing stock deduction: {str(e)}"
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