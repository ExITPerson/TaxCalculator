from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from clients.normalized import NormalizedOperation, OperationCategory
from database.db import (
    OperationsDB, CounterpartyDB, Role, UserDB,
    CashWithdrawalDB, InvestOperationDB, BalanceAdjustmentDB,
)
from invest.models import BaseOperation

SKIP_COUNTERPARTY_CATEGORIES = {
    OperationCategory.INTERNAL_TRANSFER,
    OperationCategory.OVERNIGHT_RETURN,
    OperationCategory.OVERNIGHT_DEPOSIT,
    OperationCategory.OVERNIGHT_INCOME,
    OperationCategory.CARD_PAYMENT,
    OperationCategory.CARD_TRANSFER,
    OperationCategory.CARD_DEPOSIT,
    OperationCategory.CASH_WITHDRAWAL,
    OperationCategory.COMMISSION,
    OperationCategory.SALARY_COMMISSION,
    OperationCategory.OWN_FUNDS_TRANSFER,
}


class CrudDB:
    def __init__(self, session: Session) -> None:
        self.__session = session

    def save_operations(self, operations: Iterable[NormalizedOperation]) -> dict:
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
                'total': inc + exp + int_,
                'net': inc - exp,
            })

        return sorted(result, key=lambda x: x['total'], reverse=True)


class UserCrud:
    def __init__(self, session):
        self.__session = session

    def get_or_create(self, user_id: int, username: str = '', full_name: str = '') -> UserDB:
        user = self.__session.query(UserDB).filter_by(user_id=user_id).first()
        if user:
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
        q = self.__session.query(UserDB)
        if query.isdigit():
            q = q.filter(UserDB.user_id == int(query))
        else:
            username = query.lstrip('@')
            q = q.filter(UserDB.username.ilike(f'%{username}%'))
        return q.all()

    def count_by_role(self) -> dict[str, int]:
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
        result = self.__session.query(
            func.coalesce(func.sum(CashWithdrawalDB.amount), 0)
        ).scalar()
        return float(result or 0)

    def delete(self, item_id: int) -> bool:
        item = self.__session.query(CashWithdrawalDB).get(item_id)
        if not item:
            return False
        self.__session.delete(item)
        self.__session.commit()
        return True


class BalanceAdjustmentCrud:
    """Ручные корректировки остатка (только для админа)."""

    def __init__(self, session: Session) -> None:
        self.__session = session

    def add(self, amount: float, created_by: int = 0, comment: str = '') -> BalanceAdjustmentDB:
        item = BalanceAdjustmentDB(
            amount=amount,
            created_by=created_by,
            comment=comment or None,
        )
        self.__session.add(item)
        self.__session.commit()
        return item

    def get_all(self, limit: int = 50) -> list[BalanceAdjustmentDB]:
        return (
            self.__session.query(BalanceAdjustmentDB)
            .order_by(BalanceAdjustmentDB.created_at.desc())
            .limit(limit)
            .all()
        )

    def total(self) -> float:
        result = self.__session.query(
            func.coalesce(func.sum(BalanceAdjustmentDB.amount), 0)
        ).scalar()
        return float(result or 0)

    def delete(self, item_id: int) -> bool:
        item = self.__session.query(BalanceAdjustmentDB).get(item_id)
        if not item:
            return False
        self.__session.delete(item)
        self.__session.commit()
        return True


class InvestCrud:
    def __init__(self, session):
        self.__session = session

    def save_operations(self, operations: list[BaseOperation],
                        tickers: dict | None = None) -> dict:
        stats = {'added': 0, 'skipped': 0, 'duplicates': 0}
        tickers = tickers or {}

        if not operations:
            return stats

        existing = {
            (row[0], row[1]) for row in
            self.__session.query(
                InvestOperationDB.id,
                InvestOperationDB.account_id,
            ).all()
        }

        seen_in_batch = set()
        to_insert = []

        for op in operations:
            key = (op.id, op.account_id)
            if key in existing:
                stats['skipped'] += 1
                continue
            if key in seen_in_batch:
                stats['duplicates'] += 1
                continue
            seen_in_batch.add(key)
            to_insert.append(op)

        for op in to_insert:
            figi = getattr(op, 'figi', None) or None
            ticker = tickers.get(figi) if figi else None

            self.__session.add(InvestOperationDB(
                id=op.id,
                account_id=op.account_id,
                parent_id=op.parent_id,
                date=op.date,
                kind=op.kind.value,
                raw_type=op.raw_type,
                operation_type=op.operation_type,
                state=op.state,
                payment_amount=float(op.payment.amount),
                payment_currency=op.payment.currency,
                figi=figi,
                ticker=ticker,
                instrument_uid=getattr(op, 'instrument_uid', None) or None,
                instrument_type=(op.instrument_type.value
                                 if hasattr(op, 'instrument_type') else None),
                quantity=float(getattr(op, 'quantity', 0) or 0),
                price_per_unit=(float(getattr(op, 'price_per_unit', None).amount)
                                if hasattr(op, 'price_per_unit') and op.price_per_unit
                                else None),
            ))
            stats['added'] += 1

        self.__session.commit()
        return stats

    def total_deposits(self, account_id: str | None = None) -> float:
        q = self.__session.query(
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0)
        ).filter(InvestOperationDB.kind == 'deposit')
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        return float(q.scalar() or 0)

    def total_withdrawals(self, account_id: str | None = None) -> float:
        q = self.__session.query(
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0)
        ).filter(InvestOperationDB.kind == 'withdraw')
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        return abs(float(q.scalar() or 0))

    def total_income_by_type(self, account_id: str | None = None) -> dict[str, float]:
        q = self.__session.query(
            InvestOperationDB.kind,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        ).filter(InvestOperationDB.kind.in_(
            ['coupon', 'dividend', 'bond_repayment', 'amortization']
        ))
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        rows = q.group_by(InvestOperationDB.kind).all()
        return {kind: float(total or 0) for kind, total in rows}

    def total_fees(self, account_id: str | None = None) -> float:
        q = self.__session.query(
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0)
        ).filter(InvestOperationDB.kind.in_(['fee', 'margin_fee', 'tax']))
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        return abs(float(q.scalar() or 0))

    def get_instruments(self, account_id: str | None = None) -> list[str]:
        q = self.__session.query(InvestOperationDB.figi).filter(
            InvestOperationDB.kind.in_(['buy', 'sell']),
            InvestOperationDB.figi.isnot(None),
        ).distinct()
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        return [row[0] for row in q.all() if row[0]]

    def get_trades_for_instrument(self, figi: str, account_id: str | None = None):
        q = self.__session.query(InvestOperationDB).filter(
            InvestOperationDB.figi == figi,
            InvestOperationDB.kind.in_(['buy', 'sell']),
        ).order_by(InvestOperationDB.date)
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        return q.all()

    def get_position(self, figi: str, account_id: str | None = None) -> Decimal:
        q = self.__session.query(InvestOperationDB).filter(
            InvestOperationDB.figi == figi,
            InvestOperationDB.kind.in_(['buy', 'sell']),
        )
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)

        pos = Decimal("0")
        for op in q.all():
            qty = Decimal(str(op.quantity or 0))
            pos += qty if op.kind == 'buy' else -qty
        return pos

    def count_by_kind(self, account_id: str | None = None) -> dict[str, int]:
        q = self.__session.query(
            InvestOperationDB.kind,
            func.count(InvestOperationDB.id),
        )
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        rows = q.group_by(InvestOperationDB.kind).all()
        return {kind: count for kind, count in rows}

    def income_by_figi(self) -> dict[str, dict[str, float]]:
        rows = (
            self.__session.query(
                InvestOperationDB.figi,
                InvestOperationDB.kind,
                func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
            )
            .filter(
                InvestOperationDB.kind.in_(
                    ['coupon', 'dividend', 'bond_repayment', 'amortization']
                ),
                InvestOperationDB.figi.isnot(None),
            )
            .group_by(InvestOperationDB.figi, InvestOperationDB.kind)
            .all()
        )

        result: dict[str, dict[str, float]] = {}
        for figi, kind, total in rows:
            result.setdefault(figi, {})[kind] = float(total or 0)
        return result

    def income_total_by_figi(self) -> dict[str, float]:
        by_figi = self.income_by_figi()
        return {
            figi: sum(kinds.values())
            for figi, kinds in by_figi.items()
        }