from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from clients.normalized import OperationCategory
from database.db import OperationsDB, CounterpartyDB


class CrudDB:
    def __init__(self, session: Session) -> None:
        self.__session = session

    def save_operations(self, operations: List) -> dict:
        """
        Добавляет операции и контрагентов в БД.
            - Контрагенты: если ИНН существует — обновляет поля.
            - Операции: отсекает по последней дате, для пограничных — проверка по operation_id.

        Returns:
            dict: added_ops, skipped_ops, added_cp, updated_cp
        """

        skip_categories = {
            OperationCategory.INTERNAL_TRANSFER,
            OperationCategory.OVERNIGHT_INCOME,
            OperationCategory.OVERNIGHT_RETURN,
            OperationCategory.OVERNIGHT_DEPOSIT,
            OperationCategory.CARD_PAYMENT,
            OperationCategory.COMMISSION
        }

        stats = {'added_ops': 0, 'skipped_ops': 0, 'added_cp': 0, 'updated_cp': 0}

        #Последняя дата операции, записанной в БД
        last_date = self.__session.query(func.max(OperationsDB.date)).scalar()

        #Фильтруем новые операции, что бы не перенагружать БД добавлениями
        if last_date:
            new_ops = [op for op in operations if op.date >= last_date]
            old_ops_count = len(operations) - len(new_ops)
            stats['skipped_ops'] += old_ops_count

        else:
            new_ops = operations

        #Фильтруем по id пограничные операции
        if last_date:
            boundary_ids = [op.operation_id for op in operations if op.date == last_date]
            if boundary_ids:
                existing_boundary_ids = set(
                    self.__session.query(OperationsDB.operation_id)
                    .filter(OperationsDB.operation_id.in_(boundary_ids))
                    .all()
                )
                existing_boundary_ids = {row[0] for row in existing_boundary_ids}
            else:
                existing_boundary_ids = set()
        else:
            existing_boundary_ids = set()

        #Перезагрузка контрагентов по ИНН
        needed_inns = {
            op.counterparty.inn
            for op in new_ops
            if op.category not in skip_categories and op.counterparty.inn
        }
        existing_cp = {}

        if needed_inns:
            cp_rows = (
                self.__session.query(CounterpartyDB)
                .filter(CounterpartyDB.inn.in_(needed_inns))
                .all()
            )
            existing_cp = {cp.inn: cp for cp in cp_rows if cp.inn}

        #Обработка
        for op in new_ops:
            if op.operation_id in existing_boundary_ids:
                stats['skipped_ops'] += 1
                continue

            counterparty_db = None
            if op.category not in skip_categories and op.counterparty.inn:
                inn = op.counterparty.inn

                if inn in existing_cp:
                    #Обновляем информацию о существующем в БД контрагента
                    cp = existing_cp[inn]
                    cp.name = op.counterparty.name or cp.name
                    cp.kpp = op.counterparty.kpp or cp.kpp
                    cp.account = op.counterparty.account or cp.account
                    cp.corr_account = op.counterparty.corr_account or cp.corr_account
                    cp.bic = op.counterparty.bic or cp.bic
                    cp.bank = op.counterparty.bank or cp.bank
                    stats["updated_cp"] += 1
                    counterparty_db = cp

                else:
                    #Новый контрагент
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
        """ Получение всех операций из БД """
        operations = (self.__session
                      .query(OperationsDB)
                      .all())
        return operations

    def get_all_counterparties(self):
        """ Получение всех контрагентов их БД """
        counterparties = (self.__session
                          .query(CounterpartyDB)
                          .all()
                          )
        return counterparties

    def get_operations_by_counterparty(self, inn: str) -> List[OperationsDB]:
        operations = (self.__session.query(OperationsDB)
                      .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
                      .filter(CounterpartyDB.inn == inn)
                      .order_by(OperationsDB.date.desc())
                      .all()
                      )
        return operations

    def get_sums_by_counterparty(self) -> List[dict]:
        """
        Группирует суммы по контрагентам.
        Разделяет на поступления и расходы.
        """
        results = (
            self.__session.query(
                CounterpartyDB.name.label("name"),
                CounterpartyDB.inn.label("inn"),
                OperationsDB.direction.label("direction"),
                func.sum(OperationsDB.amount).label("total"),
                func.count(OperationsDB.operation_id).label("count"),
            )
            .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
            .group_by(CounterpartyDB.id, CounterpartyDB.name, CounterpartyDB.inn, OperationsDB.direction)
            .all()
        )

        counterparties: dict[str, dict] = {}

        for row in results:
            key = row.inn
            if key not in counterparties:
                counterparties[key] = {
                    "name": row.name,
                    "inn": row.inn,
                    "income": 0.0,
                    "expense": 0.0,
                    "income_count": 0,
                    "expense_count": 0,
                }
            if row.direction == "IN":
                counterparties[key]["income"] += float(row.total)
                counterparties[key]["income_count"] += row.count
            else:
                counterparties[key]["expense"] += float(row.total)
                counterparties[key]["expense_count"] += row.count

        # Добавляем оборот и сальдо
        for cp in counterparties.values():
            cp["turnover"] = cp["income"] + cp["expense"]
            cp["balance"] = cp["income"] - cp["expense"]

        return sorted(
            counterparties.values(),
            key=lambda x: x["turnover"],
            reverse=True,
        )

    def get_sums_by_category_and_counterparty(self, category: str) -> List[dict]:
        """
        Группирует суммы по контрагентам внутри конкретной категории.
        Полезно для анализа: «показать все поступления по контрагентам».
        """
        results = (
            self.__session.query(
                CounterpartyDB.name.label("name"),
                CounterpartyDB.inn.label("inn"),
                func.sum(OperationsDB.amount).label("total"),
                func.count(OperationsDB.operation_id).label("count"),
            )
            .join(CounterpartyDB, OperationsDB.counterparty_id == CounterpartyDB.id)
            .filter(OperationsDB.category == category)
            .group_by(CounterpartyDB.id, CounterpartyDB.name, CounterpartyDB.inn)
            .order_by(func.sum(OperationsDB.amount).desc())
            .all()
        )

        return [
            {
                "name": row.name,
                "inn": row.inn,
                "total": float(row.total),
                "count": row.count,
            }
            for row in results
        ]

    def get_sums_by_category(self, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> List[
        dict]:
        """
        Группирует суммы по категориям операций.
        Опционально фильтрует по периоду.
        """
        query = (
            self.__session.query(
                OperationsDB.category.label("category"),
                OperationsDB.direction.label("direction"),
                func.sum(OperationsDB.amount).label("total"),
                func.count(OperationsDB.operation_id).label("count"),
            )
            .group_by(OperationsDB.category, OperationsDB.direction)
        )

        if date_from:
            query = query.filter(OperationsDB.date >= date_from)
        if date_to:
            query = query.filter(OperationsDB.date <= date_to)

        results = query.all()

        categories: dict[str, dict] = {}

        for row in results:
            cat = row.category
            if cat not in categories:
                categories[cat] = {
                    "category": cat,
                    "income": 0.0,
                    "expense": 0.0,
                    "income_count": 0,
                    "expense_count": 0,
                }
            if row.direction == "IN":
                categories[cat]["income"] += float(row.total)
                categories[cat]["income_count"] += row.count
            else:
                categories[cat]["expense"] += float(row.total)
                categories[cat]["expense_count"] += row.count

        for cat in categories.values():
            cat["total"] = cat["income"] + cat["expense"]
            cat["net"] = cat["income"] - cat["expense"]

        return sorted(categories.values(), key=lambda x: x["total"], reverse=True)


