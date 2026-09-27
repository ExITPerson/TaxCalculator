from typing import List

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
            cp_rows = {
                self.__session.query(CounterpartyDB)
                .filter(CounterpartyDB.inn.in_(needed_inns))
                .all()
            }
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