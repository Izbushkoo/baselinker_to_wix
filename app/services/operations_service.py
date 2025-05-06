from typing import List, Dict, Optional, Union
from datetime import datetime
from sqlmodel import Session, select, create_engine
from uuid import UUID

from app.models.operations import Operation, OperationType
from app.models.user import User
from app.core.config import settings

def get_operations_service(engine=None):
    dsn = settings.SQLALCHEMY_DATABASE_URI.unicode_string()
    """Получение инстанса сервиса операций"""
    engine = create_engine(dsn)
    return OperationsService(engine)

class OperationsService:
    def __init__(self, engine=None):
        self.engine = engine

    def _get_session(self, session: Optional[Session] = None) -> Session:
        """Получение сессии"""
        if session:
            return session
        if not self.engine:
            raise ValueError("Engine не инициализирован")
        return Session(self.engine)

    def create_single_operation(
        self,
        operation_type: OperationType,
        warehouse_id: str,
        sku: str,
        quantity: int,
        user_email: Optional[str] = None,
        target_warehouse_id: Optional[str] = None,
        order_id: Optional[str] = None,
        comment: Optional[str] = None,
        session: Optional[Session] = None
    ) -> Operation:
        """Создание одиночной операции"""
        session = self._get_session(session)
        
        products_data = {"sku": sku, "quantity": quantity}
        
        operation = Operation(
            operation_type=operation_type,
            warehouse_id=warehouse_id,
            products_data=products_data,
            user_email=user_email,
            target_warehouse_id=target_warehouse_id,
            order_id=order_id,
            comment=comment
        )
        
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return operation

    def create_file_operation(
        self,
        operation_type: OperationType,
        warehouse_id: str,
        products: List[Dict[str, Union[str, int]]],
        file_name: str,
        user_email: str,
        target_warehouse_id: Optional[str] = None,
        comment: Optional[str] = None,
        session: Optional[Session] = None
    ) -> Operation:
        """Создание операции на основе файла"""
        session = self._get_session(session)

        if operation_type not in [OperationType.STOCK_IN_FILE, OperationType.TRANSFER_FILE]:
            raise ValueError("Неверный тип операции для файловой обработки")

        products_data = {"products": products}
        
        operation = Operation(
            operation_type=operation_type,
            warehouse_id=warehouse_id,
            products_data=products_data,
            user_email=user_email,
            target_warehouse_id=target_warehouse_id,
            file_name=file_name,
            comment=comment
        )
        
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return operation

    def create_order_operation(
        self,
        warehouse_id: str,
        sku: str,
        quantity: int,
        order_id: str,
        comment: Optional[str] = None,
        session: Optional[Session] = None
    ) -> Operation:
        """Создание операции списания по заказу"""
        return self.create_single_operation(
            operation_type=OperationType.STOCK_OUT_ORDER,
            warehouse_id=warehouse_id,
            sku=sku,
            quantity=quantity,
            order_id=order_id,
            comment=comment,
            session=session
        )

    def get_operation(self, operation_id: UUID, session: Optional[Session] = None) -> Optional[Operation]:
        """Получение операции по ID"""
        session = self._get_session(session)
        statement = select(Operation).where(Operation.id == operation_id)
        result = session.exec(statement)
        return result.first()

    def get_operations_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        operation_type: Optional[OperationType] = None,
        warehouse_id: Optional[str] = None,
        session: Optional[Session] = None
    ) -> List[Operation]:
        """Получение операций за период с фильтрацией"""
        session = self._get_session(session)
        statement = select(Operation).where(
            Operation.created_at >= start_date,
            Operation.created_at <= end_date
        )
        
        if operation_type:
            statement = statement.where(Operation.operation_type == operation_type)
        if warehouse_id:
            statement = statement.where(Operation.warehouse_id == warehouse_id)
            
        result = session.exec(statement)
        return result.all()

    def get_operations_by_user(
        self,
        user_email: str,
        limit: int = 100,
        session: Optional[Session] = None
    ) -> List[Operation]:
        """Получение последних операций пользователя"""
        session = self._get_session(session)
        statement = select(Operation)\
            .where(Operation.user_email == user_email)\
            .order_by(Operation.created_at.desc())\
            .limit(limit)
        
        result = session.exec(statement)
        return result.all()

    def get_operations_by_order(self, order_id: str, session: Optional[Session] = None) -> List[Operation]:
        """Получение всех операций по заказу"""
        session = self._get_session(session)
        statement = select(Operation).where(Operation.order_id == order_id)
        result = session.exec(statement)
        return result.all()

    def get_latest_operations(
        self,
        limit: int = 50,
        operation_type: Optional[OperationType] = None,
        session: Optional[Session] = None
    ) -> List[Operation]:
        """Получение последних операций с опциональной фильтрацией по типу"""
        session = self._get_session(session)
        statement = select(Operation).order_by(Operation.created_at.desc())
        
        if operation_type:
            statement = statement.where(Operation.operation_type == operation_type)
            
        statement = statement.limit(limit)
        result = session.exec(statement)
        return result.all()

    def get_operations_stats(
        self,
        start_date: datetime,
        end_date: datetime,
        warehouse_id: Optional[str] = None,
        session: Optional[Session] = None
    ) -> Dict:
        """Получение статистики операций за период"""
        session = self._get_session(session)
        statement = select(Operation).where(
            Operation.created_at >= start_date,
            Operation.created_at <= end_date
        )
        
        if warehouse_id:
            statement = statement.where(Operation.warehouse_id == warehouse_id)
            
        result = session.exec(statement)
        operations = result.all()
        
        stats = {
            "total": len(operations),
            "by_type": {},
            "by_user": {},
            "file_operations": 0
        }
        
        for op in operations:
            # Подсчет по типам
            op_type = op.operation_type.value
            stats["by_type"][op_type] = stats["by_type"].get(op_type, 0) + 1
            
            # Подсчет по пользователям
            if op.user_email:
                stats["by_user"][op.user_email] = stats["by_user"].get(op.user_email, 0) + 1
            
            # Подсчет файловых операций
            if op.file_name:
                stats["file_operations"] += 1
        
        return stats