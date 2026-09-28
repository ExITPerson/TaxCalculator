from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from clients.normalized import NormalizedOperation, OperationCategory
from database.db import OperationsDB, CounterpartyDB


SKIP_COUNTERPARTY_CATEGORIES = {
    OperationCategory.INTERNAL_TRANSFER,
    # OperationCategory.OVERNIGHT_INCOME,
    OperationCategory.OVERNIGHT_RETURN,
    OperationCategory.OVERNIGHT_DEPOSIT,
    OperationCategory.CARD_PAYMENT,
    OperationCategory.CARD_TRANSFER,
    OperationCategory.CASH_WITHDRAWAL,
    OperationCategory.COMMISSION,
}


class CrudDB:
    def __init__(self, session: Session) -> None:
        self.__session = session

    def save_operations(self, operations: Iterable[NormalizedOperation]) -> dict:
        """
        Добавляет операции и контрагентов в БД.
        Возвращает статистику.
        """
        stats = {'added_ops': 0, 'skipped_ops': 0, 'added_cp': 0, 'updated_cp': 0}

        operations = list(operations)
        if not operations:
            return stats

        last_date = self.__session.query(func.max(OperationsDB.date)).scalar()

        existing_ids: set[str] = set()
        if last_date:
            boundary_ids = {op.operation_id for op in operations if op.date == last_date}
            if boundary_ids:
                rows = (
                    self.__session.query(OperationsDB.operation_id)
                    .filter(OperationsDB.operation_id.in_(boundary_ids))
                    .all()
                )
                existing_ids = {row[0] for row in rows}

        needed_inns = {
            op.counterparty.inn
            for op in operations
            if op.date >= (last_date or op.date)
            and op.category not in SKIP_COUNTERPARTY_CATEGORIES
            and op.counterparty.inn
        }

        existing_cp: dict[str, CounterpartyDB] = {}
        if needed_inns:
            rows = (
                self.__session.query(CounterpartyDB)
                .filter(CounterpartyDB.inn.in_(needed_inns))
                .all()
            )
            existing_cp = {cp.inn: cp for cp in rows if cp.inn}

        for op in operations:
            if last_date and op.date < last_date:
                stats['skipped_ops'] += 1
                continue

            if op.operation_id in existing_ids:
                stats['skipped_ops'] += 1
                continue

            counterparty_db: CounterpartyDB | None = None

            if op.category not in SKIP_COUNTERPARTY_CATEGORIES and op.counterparty.inn:
                inn = op.counterparty.inn
                cp = existing_cp.get(inn)

                if cp is not None:
                    # обновляем только непустыми значениями
                    if op.counterparty.name:
                        cp.name = op.counterparty.name
                    if op.counterparty.kpp:
                        cp.kpp = op.counterparty.kpp
                    if op.counterparty.account:
                        cp.account = op.counterparty.account
                    if op.counterparty.corr_account:
                        cp.corr_account = op.counterparty.corr_account
                    if op.counterparty.bic:
                        cp.bic = op.counterparty.bic
                    if op.counterparty.bank:
                        cp.bank = op.counterparty.bank
                    stats["updated_cp"] += 1
                    counterparty_db = cp
                else:
                    counterparty_db = CounterpartyDB(
                        name=op.counterparty.name,
                        inn=op.counterparty.inn,
                        kpp=op.counterparty.kpp,
                        account=op.counterparty.account,
                        corr_account=op.counterparty.corr_account,
                        bic=op.counterparty.bic,
                        bank=op.counterparty.bank,
                    )
                    self.__session.add(counterparty_db)
                    # flush ля быстроты
                    self.__session.flush()
                    existing_cp[inn] = counterparty_db
                    stats["added_cp"] += 1

            op_db = OperationsDB(
                operation_id=op.operation_id,
                date=op.date,
                amount=op.amount,
                category=op.category.value,
                direction=op.direction,
                description=op.description,
                merchant=op.merchant,
                counterparty_id=counterparty_db.id if counterparty_db else None,
            )
            self.__session.add(op_db)
            stats["added_ops"] += 1

        self.__session.commit()
        return stats

    def get_all_operations(self):
        return self.__session.query(OperationsDB).all()

    def get_all_counterparties(self):
        return self.__session.query(CounterpartyDB).all()

    def get_operations_by_counterparty(self, inn: str):
        return (
            self.__session.query(OperationsDB)
            .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
            .filter(CounterpartyDB.inn == inn)
            .order_by(OperationsDB.date.desc())
            .all()
        )

    def get_sums_by_counterparty(self) -> list[dict]:
        """ Суммы по контрагентам (для статистики) """
        income = func.coalesce(
            func.sum(case((OperationsDB.direction == 'IN', OperationsDB.amount), else_=0)), 0
        )
        expense = func.coalesce(
            func.sum(case((OperationsDB.direction == 'OUT', OperationsDB.amount), else_=0)), 0
        )
        income_count = func.sum(case((OperationsDB.direction == 'IN', 1), else_=0))
        expense_count = func.sum(case((OperationsDB.direction == 'OUT', 1), else_=0))

        rows = (
            self.__session.query(
                CounterpartyDB.name.label('name'),
                CounterpartyDB.inn.label('inn'),
                income.label('income'),
                expense.label('expense'),
                income_count.label('income_count'),
                expense_count.label('expense_count'),
            )
            .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
            .group_by(CounterpartyDB.id, CounterpartyDB.name, CounterpartyDB.inn)
            .all()
        )

        result = []
        for row in rows:
            inc = float(row.income or 0)
            exp = float(row.expense or 0)
            result.append({
                'name': row.name,
                'inn': row.inn,
                'income': inc,
                'expense': exp,
                'income_count': int(row.income_count or 0),
                'expense_count': int(row.expense_count or 0),
                'turnover': inc + exp,
                'balance': inc - exp,
            })

        return sorted(result, key=lambda x: x['turnover'], reverse=True)

    def get_sums_by_category_and_counterparty(self, category: str) -> list[dict]:
        """ Суммы по категориям и контрагентам """
        rows = (
            self.__session.query(
                CounterpartyDB.name.label('name'),
                CounterpartyDB.inn.label('inn'),
                func.sum(OperationsDB.amount).label('total'),
                func.count(OperationsDB.operation_id).label('count'),
            )
            .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
            .filter(OperationsDB.category == category)
            .group_by(CounterpartyDB.id, CounterpartyDB.name, CounterpartyDB.inn)
            .order_by(func.sum(OperationsDB.amount).desc())
            .all()
        )

        return [
            {
                'name': row.name,
                'inn': row.inn,
                'total': float(row.total or 0),
                'count': int(row.count or 0),
            }
            for row in rows
        ]

    def get_sums_by_category(
            self,
            date_from: Optional[datetime] = None,
            date_to: Optional[datetime] = None,
    ) -> list[dict]:
        """ Суммы по категориям """
        income = func.coalesce(
            func.sum(case((OperationsDB.direction == 'IN', OperationsDB.amount), else_=0)), 0
        )
        expense = func.coalesce(
            func.sum(case((OperationsDB.direction == 'OUT', OperationsDB.amount), else_=0)), 0
        )
        # FIX: внутренние переводы (овернайт) не IN и не OUT — учитываем отдельно
        internal = func.coalesce(
            func.sum(case((OperationsDB.direction == 'INTERNAL', OperationsDB.amount), else_=0)), 0
        )
        income_count = func.sum(case((OperationsDB.direction == 'IN', 1), else_=0))
        expense_count = func.sum(case((OperationsDB.direction == 'OUT', 1), else_=0))
        internal_count = func.sum(case((OperationsDB.direction == 'INTERNAL', 1), else_=0))

        query = (
            self.__session.query(
                OperationsDB.category.label('category'),
                income.label('income'),
                expense.label('expense'),
                internal.label('internal'),
                income_count.label('income_count'),
                expense_count.label('expense_count'),
                internal_count.label('internal_count'),
            )
            .group_by(OperationsDB.category)
        )

        if date_from:
            query = query.filter(OperationsDB.date >= date_from)
        if date_to:
            query = query.filter(OperationsDB.date <= date_to)

        rows = query.all()

        result = []
        for row in rows:
            inc = float(row.income or 0)
            exp = float(row.expense or 0)
            int_ = float(row.internal or 0)
            result.append({
                'category': row.category,
                'income': inc,
                'expense': exp,
                'internal': int_,
                'income_count': int(row.income_count or 0),
                'expense_count': int(row.expense_count or 0),
                'internal_count': int(row.internal_count or 0),
                'total': inc + exp + int_,  # FIX: total учитывает всё
                'net': inc - exp,
            })

        return sorted(result, key=lambda x: x['total'], reverse=True)