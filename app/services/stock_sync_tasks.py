"""
Celery задачи для системы синхронизации складских остатков.
Включает обработку очереди, периодическую сверку, мониторинг и уведомления.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from uuid import UUID

from app.celery_shared import celery, SessionLocal, get_allegro_token
from app.services.stock_synchronization_service import StockSynchronizationService
from app.services.stock_validation_service import StockValidationService
from app.services.stock_sync_notifications import stock_sync_notifications
from app.services.warehouse.manager import get_manager
from app.services.Allegro_Microservice.orders_endpoint import OrdersClient
from app.services.Allegro_Microservice.tokens_endpoint import AllegroTokenMicroserviceClient
from app.core.security import create_access_token
from app.core.config import settings
from app.core.stock_sync_config import stock_sync_config

logger = logging.getLogger(__name__)


@celery.task(
    bind=True,
    name="app.services.stock_sync_tasks.process_pending_stock_operations",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 60}
)
def process_pending_stock_operations(self, limit: int = 50):
    """
    Обрабатывает операции из очереди с retry логикой.
    Запускается периодически для обработки неудачных синхронизаций.
    
    Args:
        limit: Максимальное количество операций для обработки за раз
    
    Returns:
        Dict: Результат обработки с детальной статистикой
    """
    try:
        session = SessionLocal()
        try:
            # Создаем JWT токен для работы с микросервисом
            jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
            
            # Инициализируем клиенты и сервисы
            orders_client = OrdersClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            tokens_client = AllegroTokenMicroserviceClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            inventory_manager = get_manager()
            
            # Создаем основной сервис синхронизации
            sync_service = StockSynchronizationService(
                session=session,
                orders_client=orders_client,
                tokens_client=tokens_client,
                inventory_manager=inventory_manager
            )
            
            # Обрабатываем pending операции
            result = sync_service.process_pending_operations(limit=limit)
            
            # Отправляем уведомление о результате
            if result.processed > 0:
                stock_sync_notifications.notify_processing_summary(result)
            
            logger.info(f"Обработано {result.processed} операций: {result.succeeded} успешно, {result.failed} неудачно")
            
            return {
                "status": "success",
                "processed": result.processed,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "max_retries_reached": result.max_retries_reached,
                "task_id": self.request.id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при обработке pending операций: {e}")
        # Отправляем уведомление об ошибке
        stock_sync_notifications.notify_custom_alert(
            title="Ошибка обработки очереди синхронизации",
            details=f"Задача process_pending_stock_operations упала с ошибкой: {str(e)}",
            priority="high"
        )
        raise


@celery.task(
    bind=True,
    name="app.services.stock_sync_tasks.reconcile_stock_states",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 2, 'countdown': 300}
)
def reconcile_stock_states(self, token_id: Optional[str] = None, limit: int = 100):
    """
    Периодическая сверка состояний между локальной системой и микросервисом.
    
    Args:
        token_id: ID конкретного токена для сверки (если None - проверяются все)
        limit: Максимальное количество заказов для проверки
        
    Returns:
        Dict: Результат сверки
    """
    try:
        session = SessionLocal()
        try:
            # Создаем JWT токен для работы с микросервисом
            jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
            
            # Инициализируем клиенты и сервисы
            orders_client = OrdersClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            tokens_client = AllegroTokenMicroserviceClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            inventory_manager = get_manager()
            
            # Создаем основной сервис синхронизации
            sync_service = StockSynchronizationService(
                session=session,
                orders_client=orders_client,
                tokens_client=tokens_client,
                inventory_manager=inventory_manager
            )
            
            # Выполняем сверку
            token_uuid = UUID(token_id) if token_id else None
            result = sync_service.reconcile_stock_status(
                token_id=token_uuid,
                limit=limit
            )
            
            # Получаем список проверенных аккаунтов для уведомления
            account_names = []
            if token_id:
                # Для одного токена получаем его название
                try:
                    token_response = tokens_client.get_token(token_uuid)
                    if token_response:
                        account_names = [getattr(token_response, 'account_name', 'Unknown')]
                except Exception:
                    account_names = ['Unknown']
            else:
                # Для всех токенов - обобщенное описание
                account_names = ['Multiple accounts']
            
            # Отправляем уведомление о результатах сверки
            if result.discrepancies_found > 0 or result.total_checked > 0:
                stock_sync_notifications.notify_reconciliation_discrepancies(
                    result, account_names
                )
            
            logger.info(f"Сверка завершена: проверено {result.total_checked}, найдено расхождений {result.discrepancies_found}")
            
            return {
                "status": "success",
                "total_checked": result.total_checked,
                "discrepancies_found": result.discrepancies_found,
                "auto_fixed": result.auto_fixed,
                "requires_manual_review": result.requires_manual_review,
                "task_id": self.request.id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при сверке состояний: {e}")
        # Отправляем уведомление об ошибке
        stock_sync_notifications.notify_custom_alert(
            title="Ошибка сверки состояний синхронизации",
            details=f"Задача reconcile_stock_states упала с ошибкой: {str(e)}",
            priority="high"
        )
        raise


@celery.task(
    bind=True,
    name="app.services.stock_sync_tasks.monitor_sync_system_health",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 2, 'countdown': 180}
)
def monitor_sync_system_health(self):
    """
    Мониторинг "здоровья" системы синхронизации.
    Проверяет количество pending операций, застрявших операций и общее состояние.
    
    Returns:
        Dict: Статистика состояния системы
    """
    try:
        session = SessionLocal()
        try:
            # Создаем JWT токен для работы с микросервисом
            jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
            
            # Инициализируем клиенты и сервисы
            orders_client = OrdersClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            tokens_client = AllegroTokenMicroserviceClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            inventory_manager = get_manager()
            
            # Создаем основной сервис синхронизации
            sync_service = StockSynchronizationService(
                session=session,
                orders_client=orders_client,
                tokens_client=tokens_client,
                inventory_manager=inventory_manager
            )
            
            # Получаем статистику системы
            health_stats = sync_service.get_sync_statistics()
            
            # Проверяем пороговые значения и отправляем уведомления при необходимости
            if health_stats.get("health_status") in ["warning", "error"]:
                stock_sync_notifications.notify_system_health(health_stats)
            
            logger.info(f"Мониторинг системы: статус {health_stats.get('health_status', 'unknown')}")
            
            return {
                "status": "success",
                "health_data": health_stats,
                "task_id": self.request.id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при мониторинге системы: {e}")
        # Отправляем критическое уведомление об ошибке мониторинга
        stock_sync_notifications.notify_custom_alert(
            title="КРИТИЧНО: Ошибка системы мониторинга",
            details=f"Система мониторинга синхронизации недоступна: {str(e)}",
            priority="critical"
        )
        raise


@celery.task(
    bind=True,
    name="app.services.stock_sync_tasks.send_daily_sync_summary"
)
def send_daily_sync_summary(self):
    """
    Отправляет ежедневную сводку по работе системы синхронизации.
    Запускается один раз в день в утренние часы.
    
    Returns:
        Dict: Результат отправки сводки
    """
    try:
        session = SessionLocal()
        try:
            # Создаем JWT токен для работы с микросервисом
            jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
            
            # Инициализируем клиенты и сервисы
            orders_client = OrdersClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            tokens_client = AllegroTokenMicroserviceClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            inventory_manager = get_manager()
            
            # Создаем основной сервис синхронизации
            sync_service = StockSynchronizationService(
                session=session,
                orders_client=orders_client,
                tokens_client=tokens_client,
                inventory_manager=inventory_manager
            )
            
            # Получаем статистику
            daily_stats = sync_service.get_sync_statistics()
            
            # Добавляем количество активных аккаунтов
            try:
                tokens_response = tokens_client.get_tokens(active_only=True, per_page=1000)
                active_accounts = len(tokens_response.items) if tokens_response else 0
                daily_stats['active_accounts'] = active_accounts
            except Exception:
                daily_stats['active_accounts'] = 0
            
            # Отправляем ежедневную сводку
            stock_sync_notifications.notify_daily_summary(daily_stats)
            
            logger.info("Ежедневная сводка отправлена")
            
            return {
                "status": "success",
                "summary_sent": True,
                "daily_stats": daily_stats,
                "task_id": self.request.id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневной сводки: {e}")
        stock_sync_notifications.notify_custom_alert(
            title="Ошибка отправки ежедневной сводки",
            details=f"Не удалось отправить ежедневную сводку: {str(e)}",
            priority="normal"
        )
        return {
            "status": "error",
            "error": str(e),
            "task_id": self.request.id
        }


@celery.task(
    bind=True,
    name="app.services.stock_sync_tasks.cleanup_old_sync_logs"
)
def cleanup_old_sync_logs(self, days_to_keep: int = 30):
    """
    Очистка старых логов синхронизации.
    Удаляет записи старше указанного количества дней.
    
    Args:
        days_to_keep: Количество дней для сохранения логов
        
    Returns:
        Dict: Результат очистки
    """
    try:
        from app.models.stock_synchronization import StockSynchronizationLog, OperationStatus
        from sqlmodel import select
        
        session = SessionLocal()
        try:
            # Вычисляем дату отсечки
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            
            # Удаляем старые логи
            old_logs = session.exec(
                select(StockSynchronizationLog).where(
                    StockSynchronizationLog.timestamp < cutoff_date
                )
            ).all()
            
            deleted_count = len(old_logs)
            
            for log in old_logs:
                session.delete(log)
            
            session.commit()
            
            logger.info(f"Удалено {deleted_count} старых записей логов (старше {days_to_keep} дней)")
            
            return {
                "status": "success",
                "deleted_logs": deleted_count,
                "cutoff_date": cutoff_date.isoformat(),
                "task_id": self.request.id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при очистке старых логов: {e}")
        return {
            "status": "error",
            "error": str(e),
            "task_id": self.request.id
        }


@celery.task(
    bind=True,
    name="app.services.stock_sync_tasks.validate_pending_operations",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 2, 'countdown': 120}
)
def validate_pending_operations(self, limit: int = 100):
    """
    Валидация pending операций перед их обработкой.
    Проверяет наличие товаров на складах и отправляет предупреждения.
    
    Args:
        limit: Максимальное количество операций для валидации
        
    Returns:
        Dict: Результат валидации
    """
    try:
        from app.models.stock_synchronization import PendingStockOperation, OperationStatus
        from sqlmodel import select
        
        session = SessionLocal()
        try:
            inventory_manager = get_manager()
            
            # Создаем сервис валидации
            validation_service = StockValidationService(
                session=session,
                inventory_manager=inventory_manager
            )
            
            # Создаем JWT токен для работы с микросервисом
            jwt_token = create_access_token(user_id=settings.PROJECT_NAME)
            tokens_client = AllegroTokenMicroserviceClient(
                jwt_token=jwt_token,
                base_url=settings.MICRO_SERVICE_URL
            )
            
            # Получаем pending операции
            pending_operations = session.exec(
                select(PendingStockOperation).where(
                    PendingStockOperation.status == OperationStatus.PENDING
                ).limit(limit)
            ).all()
            
            validated_count = 0
            invalid_count = 0
            
            for operation in pending_operations:
                try:
                    # Валидируем операцию
                    validation_result = validation_service.validate_stock_deduction(
                        sku=operation.sku,
                        warehouse=operation.warehouse,
                        required_quantity=operation.quantity
                    )
                    
                    validated_count += 1
                    
                    if not validation_result.valid:
                        invalid_count += 1
                        
                        # Получаем имя аккаунта для уведомления
                        try:
                            token_response = tokens_client.get_token(UUID(operation.token_id))
                            account_name = getattr(token_response, 'account_name', 'Unknown')
                        except Exception:
                            account_name = 'Unknown'
                        
                        # Отправляем уведомление о проблеме с валидацией
                        stock_sync_notifications.notify_stock_validation_failure(
                            validation_result=validation_result,
                            account_name=account_name,
                            order_id=operation.order_id
                        )
                        
                except Exception as e:
                    logger.error(f"Ошибка при валидации операции {operation.id}: {e}")
                    continue
            
            logger.info(f"Валидировано {validated_count} операций, {invalid_count} недействительных")
            
            return {
                "status": "success",
                "validated_count": validated_count,
                "invalid_count": invalid_count,
                "task_id": self.request.id
            }
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Ошибка при валидации pending операций: {e}")
        raise


# Регистрация задач в Celery
def register_stock_sync_tasks():
    """
    Регистрирует задачи синхронизации складов в расписании Celery Beat.
    Вызывается при инициализации приложения.
    """
    from celery.schedules import crontab
    
    # Определяем расписание для задач синхронизации
    STOCK_SYNC_SCHEDULE = {
        # Обработка pending операций каждые 5 минут
        'process-pending-stock-operations': {
            'task': 'app.services.stock_sync_tasks.process_pending_stock_operations',
            'schedule': 300.0,  # 5 минут
            'kwargs': {'limit': 50}
        },
        
        # Валидация pending операций каждые 15 минут  
        'validate-pending-operations': {
            'task': 'app.services.stock_sync_tasks.validate_pending_operations',
            'schedule': 900.0,  # 15 минут
            'kwargs': {'limit': 100}
        },
        
        # Сверка состояний каждый час
        'reconcile-stock-states': {
            'task': 'app.services.stock_sync_tasks.reconcile_stock_states',
            'schedule': 3600.0,  # 1 час
            'kwargs': {'limit': 200}
        },
        
        # Мониторинг системы каждые 10 минут
        'monitor-sync-system-health': {
            'task': 'app.services.stock_sync_tasks.monitor_sync_system_health',
            'schedule': 600.0  # 10 минут
        },
        
        # Ежедневная сводка в 8:00 утра UTC
        'send-daily-sync-summary': {
            'task': 'app.services.stock_sync_tasks.send_daily_sync_summary',
            'schedule': crontab(hour=8, minute=0).__repr__()
        },
        
        # Очистка старых логов каждые 24 часа в 02:00 UTC
        'cleanup-old-sync-logs': {
            'task': 'app.services.stock_sync_tasks.cleanup_old_sync_logs',
            'schedule': crontab(hour=2, minute=0).__repr__(),
            'kwargs': {'days_to_keep': 30}
        }
    }
    
    return STOCK_SYNC_SCHEDULE