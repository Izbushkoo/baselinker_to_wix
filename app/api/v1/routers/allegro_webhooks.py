import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlmodel import Session
from uuid import UUID

from app.api.deps import get_session
from app.schemas.stock_synchronization import (
    StockDeductionWebhookRequest,
    StockDeductionWebhookResponse
)
from app.services.stock_synchronization_service import StockSynchronizationService
from app.services.stock_validation_service import StockValidationService
from app.services.stock_sync_notifications import get_notification_service
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.warehouse.manager import get_manager
from app.core.security import create_access_token
from app.core.config import settings

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
    Получает сигнал с token_id и order_id, запрашивает детали заказа у микросервиса
    и обрабатывает все позиции заказа.
    
    Args:
        webhook_data: token_id и order_id для обработки
        background_tasks: Фоновые задачи для дополнительной обработки
        session: Сессия базы данных
        
    Returns:
        StockDeductionWebhookResponse: Результат обработки вебхука
    """
    client_ip = request.client.host if request.client else "unknown"
    
    logger.info(
        f"Received stock deduction webhook from {client_ip}: "
        f"token_id={webhook_data.token_id}, order_id={webhook_data.order_id}"
    )
    
    try:
        # Создаем клиент для получения данных заказа из микросервиса
        orders_client = OrdersClient(
            jwt_token=create_access_token(user_id=settings.PROJECT_NAME),
            base_url=settings.MICRO_SERVICE_URL
        )
        
        # Получаем детали заказа
        try:
            order_response = orders_client.get_order_by_id(
                token_id=UUID(webhook_data.token_id),
                order_id=webhook_data.order_id
            )
            order_data = order_response.order
        except Exception as e:
            logger.error(f"Failed to get order details: token_id={webhook_data.token_id}, order_id={webhook_data.order_id}, error={str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to get order details from microservice: {str(e)}"
            )
        
        # Проверяем наличие позиций в заказе
        line_items = order_data.get("lineItems", [])
        if not line_items:
            logger.warning(f"No line items found in order {webhook_data.order_id}")
            return StockDeductionWebhookResponse(
                success=True,
                operations_created=0,
                operations_processed=0,
                message="No line items to process in order",
                order_details={"order_id": webhook_data.order_id, "line_items_count": 0}
            )
        
        # Инициализируем сервисы
        warehouse_manager = get_manager()
        validation_service = StockValidationService(session=session, inventory_manager=warehouse_manager)
        
        # ВАЛИДАЦИЯ: Проверяем доступность всех товаров в заказе ПЕРЕД списанием
        warehouse = "Ирина"  # Дефолтный склад
        validation_result = validation_service.validate_order_stock_availability(
            order_data=order_data,
            warehouse=warehouse
        )
        
        # Если валидация провалена - останавливаем обработку заказа целиком
        if not validation_result.valid:
            error_details = {
                "validation_failed": True,
                "total_items": validation_result.total_items,
                "valid_items": validation_result.valid_items,
                "invalid_items": validation_result.invalid_items,
                "validation_success_rate": f"{validation_result.validation_success_rate:.1f}%",
                "errors": validation_result.error_summary,
                "item_details": {
                    sku: {
                        "available_quantity": result.available_quantity,
                        "required_quantity": result.required_quantity,
                        "shortage_quantity": result.shortage_quantity,
                        "error_message": result.error_message
                    }
                    for sku, result in validation_result.validation_details.items()
                    if not result.valid
                }
            }
            
            logger.warning(
                f"Stock validation failed for order {webhook_data.order_id}: "
                f"{validation_result.invalid_items} of {validation_result.total_items} items unavailable"
            )
            
            # Отправляем уведомление о провале валидации с контролем спама
            try:
                # Получаем имя аккаунта
                from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
                tokens_client = AllegroTokenMicroserviceClient(
                    jwt_token=create_access_token(user_id=settings.PROJECT_NAME)
                )
                token_response = tokens_client.get_token(UUID(webhook_data.token_id))
                account_name = token_response.account_name if token_response else f"Unknown({webhook_data.token_id})"
                
                # Отправляем уведомление с контролем дублирования
                notification_service = get_notification_service(session)
                notification_service.notify_order_validation_failure(
                    token_id=webhook_data.token_id,
                    order_id=webhook_data.order_id,
                    account_name=account_name,
                    validation_errors=validation_result.error_summary,
                    order_details={
                        "line_items_count": len(line_items),
                        "order_status": order_data.get("status"),
                        "buyer_email": order_data.get("buyer", {}).get("email"),
                        "validation_details": error_details
                    }
                )
            except Exception as e:
                logger.error(f"Failed to send validation failure notification: {e}")
            
            return StockDeductionWebhookResponse(
                success=False,  # Валидация провалена - заказ не обработан
                operations_created=0,
                operations_processed=0,
                message=f"Stock validation failed: {validation_result.invalid_items} of {validation_result.total_items} items unavailable",
                details=error_details,
                order_details={
                    "order_id": webhook_data.order_id,
                    "line_items_count": len(line_items),
                    "order_status": order_data.get("status"),
                    "buyer_email": order_data.get("buyer", {}).get("email")
                }
            )
        
        # Валидация успешна - инициализируем сервис синхронизации
        sync_service = StockSynchronizationService(session=session)
        
        # Обрабатываем каждую позицию заказа
        operations_created = 0
        operations_processed = 0
        processing_results = []
        
        for line_item in line_items:
            offer = line_item.get("offer", {})
            sku = offer.get("external", {}).get("id")  # SKU товара
            quantity = line_item.get("quantity", 1)
            
            if not sku:
                logger.warning(f"No SKU found for line item in order {webhook_data.order_id}")
                continue
            
            logger.info(f"Processing line item: sku={sku}, quantity={quantity}")
            
            # Создаем операцию списания для каждой позиции
            # (валидацию мы уже прошли, поэтому товар должен быть доступен)
            sync_result = sync_service.sync_stock_deduction(
                token_id=webhook_data.token_id,
                order_id=webhook_data.order_id,
                sku=sku,
                quantity=quantity,
                warehouse=warehouse
            )
            
            operations_created += 1
            if sync_result.success:
                operations_processed += 1
            
            processing_results.append({
                "sku": sku,
                "quantity": quantity,
                "operation_id": str(sync_result.operation_id) if sync_result.operation_id else None,
                "success": sync_result.success,
                "error": sync_result.error,
                "details": sync_result.details
            })
        
        logger.info(
            f"Stock deduction webhook processed: "
            f"order_id={webhook_data.order_id}, "
            f"operations_created={operations_created}, "
            f"operations_processed={operations_processed}"
        )
        
        return StockDeductionWebhookResponse(
            success=True,
            operations_created=operations_created,
            operations_processed=operations_processed,
            message=f"Processed {operations_created} line items from order",
            details={
                "validation_passed": True,
                "validation_summary": {
                    "total_items": validation_result.total_items,
                    "valid_items": validation_result.valid_items,
                    "validation_success_rate": f"{validation_result.validation_success_rate:.1f}%"
                },
                "processing_results": processing_results,
                "immediate_sync_success_rate": f"{(operations_processed/operations_created*100):.1f}%" if operations_created > 0 else "0%"
            },
            order_details={
                "order_id": webhook_data.order_id,
                "line_items_count": len(line_items),
                "order_status": order_data.get("status"),
                "buyer_email": order_data.get("buyer", {}).get("email")
            }
        )
            
    except HTTPException:
        # Перебрасываем HTTP исключения как есть
        raise
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