from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from clients.normalized import NormalizedOperation, OperationCategory
from database.db import OperationsDB, CounterpartyDB, Role, UserDB, CashWithdrawalDB

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

# Категории, у которых internal нужно показывать как расход
INTERNAL_TO_EXPENSE = {
    'Внутренний перевод',
}

# Категории, у которых internal нужно показывать как приход
INTERNAL_TO_INCOME = {
    'Доход от депозита',
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

    def get_sums_by_counterparty_or_category(self) -> list[dict]:
        """
        Суммы по контрагентам, где counterparty_id заполнен.
        Для операций без контрагента — группировка по категории.
        Учитывает direction, чтобы вызывающий код мог разложить на доход/расход.
        """
        # С контрагентом
        with_cp = (
            self.__session.query(
                CounterpartyDB.name.label("name"),
                CounterpartyDB.inn.label("inn"),
                OperationsDB.direction.label("direction"),
                OperationsDB.category.label("category"),
                func.sum(OperationsDB.amount).label("total"),
            )
            .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
            .group_by(
                CounterpartyDB.id,
                CounterpartyDB.name,
                CounterpartyDB.inn,
                OperationsDB.direction,
                OperationsDB.category,
            )
            .all()
        )

        # Без контрагента — группируем по категории и направлению
        without_cp = (
            self.__session.query(
                OperationsDB.category.label("category"),
                OperationsDB.direction.label("direction"),
                func.sum(OperationsDB.amount).label("total"),
            )
            .filter(OperationsDB.counterparty_id.is_(None))
            .group_by(OperationsDB.category, OperationsDB.direction)
            .all()
        )

        result = []

        for row in with_cp:
            result.append({
                'name': row.name or row.inn or 'Без имени',
                'inn': row.inn or '',
                'direction': row.direction,
                'category': row.category,
                'total': float(row.total or 0),
            })

        for row in without_cp:
            result.append({
                'name': f'— {row.category} (без контрагента)',
                'inn': '',
                'direction': row.direction,
                'category': row.category,
                'total': float(row.total or 0),
            })

        return result

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
            category = row.category
            inc = float(row.income or 0)
            exp = float(row.expense or 0)
            int_ = float(row.internal or 0)
            inc_cnt = int(row.income_count or 0)
            exp_cnt = int(row.expense_count or 0)
            int_cnt = int(row.internal_count or 0)

            # FIX: переносим internal в income/expense для «расходных» и «доходных» категорий
            if category in INTERNAL_TO_EXPENSE and int_:
                exp += int_
                exp_cnt += int_cnt
                int_ = 0.0
                int_cnt = 0

            if category in INTERNAL_TO_INCOME and int_:
                inc += int_
                inc_cnt += int_cnt
                int_ = 0.0
                int_cnt = 0

            result.append({
                'category': category,
                'income': inc,
                'expense': exp,
                'internal': int_,
                'income_count': inc_cnt,
                'expense_count': exp_cnt,
                'internal_count': int_cnt,
                'total': inc + exp + int_,
                'net': inc - exp,
            })

        return sorted(result, key=lambda x: x['total'], reverse=True)

# database/crud.py
class UserCrud:
    def __init__(self, session):
        self.__session = session

    def get_or_create(self, user_id: int, username: str = '', full_name: str = '') -> UserDB:
        user = self.__session.query(UserDB).filter_by(user_id=user_id).first()
        if user:
            # обновляем «последнее посещение»
            user.last_seen = datetime.utcnow()
            if username:
                user.username = username
            if full_name:
                user.full_name = full_name
        else:
            user = UserDB(
                user_id=user_id,
                username=username,
                full_name=full_name,
                role=Role.USER.value,
            )
            self.__session.add(user)
        self.__session.commit()
        return user

    def get_role(self, user_id: int) -> Role:
        user = self.__session.query(UserDB).filter_by(user_id=user_id).first()
        if not user:
            return Role.USER
        try:
            return Role(user.role)
        except ValueError:
            return Role.USER

    def set_role(self, user_id: int, role: Role) -> bool:
        user = self.__session.query(UserDB).filter_by(user_id=user_id).first()
        if not user:
            return False
        user.role = role.value
        self.__session.commit()
        return True

    def set_banned(self, user_id: int, banned: bool) -> bool:
        user = self.__session.query(UserDB).filter_by(user_id=user_id).first()
        if not user:
            return False
        user.is_banned = banned
        self.__session.commit()
        return True

    def is_banned(self, user_id: int) -> bool:
        user = self.__session.query(UserDB).filter_by(user_id=user_id).first()
        return bool(user and user.is_banned)

    def get_all(self) -> list[UserDB]:
        return (
            self.__session.query(UserDB)
            .order_by(UserDB.last_seen.desc())
            .all()
        )

    def get_by_role(self, role: Role) -> list[UserDB]:
        return (
            self.__session.query(UserDB)
            .filter(UserDB.role == role.value)
            .all()
        )

    def find(self, query: str) -> list[UserDB]:
        """Поиск по ID или username."""
        q = self.__session.query(UserDB)
        if query.isdigit():
            q = q.filter(UserDB.user_id == int(query))
        else:
            username = query.lstrip('@')
            q = q.filter(UserDB.username.ilike(f'%{username}%'))
        return q.all()

    def count_by_role(self) -> dict[str, int]:
        from sqlalchemy import func
        rows = (
            self.__session.query(UserDB.role, func.count(UserDB.user_id))
            .group_by(UserDB.role)
            .all()
        )
        return {role: count for role, count in rows}

class CashWithdrawalCrud:
    def __init__(self, session: Session) -> None:
        self.__session = session

    def add(self, amount: float, created_by: int = 0, comment: str = '') -> CashWithdrawalDB:
        item = CashWithdrawalDB(
            amount=amount,
            created_by=created_by,
            comment=comment or None,
        )
        self.__session.add(item)
        self.__session.commit()
        return item

    def get_all(self) -> list[CashWithdrawalDB]:
        return (
            self.__session.query(CashWithdrawalDB)
            .order_by(CashWithdrawalDB.created_at.desc())
            .all()
        )

    def total(self) -> float:
        from sqlalchemy import func
        result = self.__session.query(func.coalesce(func.sum(CashWithdrawalDB.amount), 0)).scalar()
        return float(result or 0)

    def delete(self, item_id: int) -> bool:
        item = self.__session.query(CashWithdrawalDB).get(item_id)
        if not item:
            return False
        self.__session.delete(item)
        self.__session.commit()
        return True