# invest/backfill.py

import logging
from datetime import date, timedelta

from sqlalchemy import func

from config.settings import ACCOUNTS_ID
from database.db import Session, InvestOperationDB
from database.snapshot_crud import SnapshotCrud
from invest.index_builder import build_snapshots_for_period
from invest.start_state import compute_start_state

logger = logging.getLogger(__name__)


def get_first_operation_date(session) -> date | None:
    row = session.query(func.min(InvestOperationDB.date)).scalar()
    return row.date() if row else None


def backfill_from_date(target_date: date, account_id: str = 'all') -> dict:
    previous_day = target_date - timedelta(days=1)
    start_positions, start_cash = compute_start_state(previous_day, ACCOUNTS_ID)

    # --- ЗАЩИТА ---
    if start_positions is None or start_cash is None:
        logger.error("backfill_from_date: compute_start_state вернул None — пропускаем")
        return {'added': 0, 'updated': 0, 'skipped': 0, 'error': 'start_state failed'}

    with Session() as session:
        crud = SnapshotCrud(session)

        start_index = 100.0
        for s in crud.get_snapshots(account_id):
            if s.date.date() < target_date:
                start_index = float(s.index_value) or 100.0
            else:
                break

        logger.info(
            "Backfill from %s: %d FIGI, start_cash=%.2f, start_index=%.4f",
            target_date, len(start_positions), start_cash, start_index,
        )

        today = date.today()
        stats = build_snapshots_for_period(
            session, target_date, today,
            account_id=account_id,
            start_cash=start_cash,
            start_positions=start_positions,
            start_index=start_index,
        )

    return stats


def backfill_incremental(account_id: str = 'all') -> dict:
    """Инкрементальный backfill с защитой от обнуления."""
    with Session() as session:
        crud = SnapshotCrud(session)
        last_date = crud.get_last_snapshot_date(account_id)
        today = date.today()

        if last_date:
            if last_date > today:
                logger.warning("Последняя дата %s > сегодня %s — пропускаем",
                               last_date, today)
                return {'added': 0, 'updated': 0, 'skipped': 0}

            start_positions, start_cash = compute_start_state(
                last_date - timedelta(days=1), ACCOUNTS_ID,
            )

            # --- ЗАЩИТА: если start_state вернул None — не трогаем snapshots ---
            if start_positions is None or start_cash is None:
                logger.error(
                    "compute_start_state вернул None — "
                    "пропускаем backfill, чтобы не затереть snapshots"
                )
                return {'added': 0, 'updated': 0, 'skipped': 0,
                        'error': 'compute_start_state failed'}

            # Дополнительная защита от пустого состояния (как было)
            if not start_positions and abs(start_cash) < 1e-6:
                logger.error(
                    "compute_start_state вернул пусто (0 FIGI, cash=0) — "
                    "пропускаем backfill, чтобы не затереть snapshots"
                )
                return {'added': 0, 'updated': 0, 'skipped': 0,
                        'error': 'compute_start_state failed'}

            last_snapshot = crud.get_snapshots(account_id)[-1]
            start_index = float(last_snapshot.index_value) or 100.0
            date_from = last_date

            logger.info(
                "Incremental backfill: с %s по %s "
                "(старт: %d FIGI, cash=%.2f, index=%.4f)",
                date_from, today, len(start_positions), start_cash, start_index,
            )
        else:
            first_date = get_first_operation_date(session)
            if not first_date:
                logger.warning("Нет операций в БД")
                return {'added': 0, 'updated': 0, 'skipped': 0}

            start_positions, start_cash = compute_start_state(
                first_date - timedelta(days=1), ACCOUNTS_ID,
            )

            if start_positions is None or start_cash is None:
                logger.error("Первый backfill: compute_start_state вернул None — пропускаем")
                return {'added': 0, 'updated': 0, 'skipped': 0,
                        'error': 'compute_start_state failed'}

            date_from = first_date
            start_index = 100.0

            logger.info(
                "Первый backfill: с %s (старт: %d FIGI, cash=%.2f)",
                date_from, len(start_positions), start_cash,
            )

        stats = build_snapshots_for_period(
            session, date_from, today,
            account_id=account_id,
            start_cash=start_cash,
            start_positions=start_positions,
            start_index=start_index,
        )

    logger.info("Incremental backfill завершён: %s", stats)
    return stats


def backfill_all(account_id: str = 'all') -> dict:
    with Session() as session:
        first_date = get_first_operation_date(session)
        if not first_date:
            return {'added': 0, 'updated': 0, 'skipped': 0}
        today = date.today()
        stats = build_snapshots_for_period(
            session, first_date, today,
            account_id=account_id,
            start_index=100.0,
        )
    return stats


def rebuild_all(account_id: str = 'all') -> dict:
    """Очищает snapshots и делает полный backfill."""
    with Session() as session:
        crud = SnapshotCrud(session)
        deleted = crud.clear(account_id)
        logger.info("Очищено %d старых snapshots", deleted)

    return backfill_all(account_id)


def backfill_last_days(days: int = 30, account_id: str = 'all') -> dict:
    target = date.today() - timedelta(days=days)
    start_positions, start_cash = compute_start_state(
        target - timedelta(days=1), ACCOUNTS_ID,
    )

    if start_positions is None or start_cash is None:
        logger.error("backfill_last_days: compute_start_state вернул None — пропускаем")
        return {'added': 0, 'updated': 0, 'skipped': 0,
                'error': 'compute_start_state failed'}

    if not start_positions and abs(start_cash) < 1e-6:
        logger.error("compute_start_state вернул пусто — пропускаем")
        return {'added': 0, 'updated': 0, 'skipped': 0,
                'error': 'compute_start_state failed'}

    with Session() as session:
        crud = SnapshotCrud(session)

        start_index = 100.0
        for s in crud.get_snapshots(account_id):
            if s.date.date() < target:
                start_index = float(s.index_value) or 100.0
            else:
                break

        today = date.today()
        stats = build_snapshots_for_period(
            session, target, today,
            account_id=account_id,
            start_cash=start_cash,
            start_positions=start_positions,
            start_index=start_index,
        )
    return stats