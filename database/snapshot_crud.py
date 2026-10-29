from datetime import date, datetime

from database.db import PortfolioSnapshotDB, CandleCacheDB


class SnapshotCrud:
    def __init__(self, session):
        self.__session = session

    # ---------- Snapshot ----------

    def upsert_snapshot(self, d: date, account_id: str, data: dict,
                        force_update: bool = False) -> str:
        """
        Возвращает: 'added' | 'updated' | 'skipped'.
        force_update=True — обновлять всегда.
        force_update=False — обновлять только если дата >= сегодня.
        """
        dt = datetime.combine(d, datetime.min.time())
        existing = (
            self.__session.query(PortfolioSnapshotDB)
            .filter_by(date=dt, account_id=account_id)
            .first()
        )

        if existing:
            today = date.today()
            if force_update or d >= today:
                existing.total_value = data.get('total_value', 0)
                existing.paper_value = data.get('paper_value', 0)
                existing.cash_value = data.get('cash_value', 0)
                existing.external_flow = data.get('external_flow', 0)
                existing.index_value = data.get('index_value', 100)
                existing.pnl_value = data.get('pnl_value', 0)
                existing.positions_count = data.get('positions_count', 0)
                existing.calculated_at = datetime.utcnow()
                self.__session.commit()
                return 'updated'
            return 'skipped'

        self.__session.add(PortfolioSnapshotDB(
            date=dt,
            account_id=account_id,
            total_value=data.get('total_value', 0),
            paper_value=data.get('paper_value', 0),
            cash_value=data.get('cash_value', 0),
            external_flow=data.get('external_flow', 0),
            index_value=data.get('index_value', 100),
            pnl_value=data.get('pnl_value', 0),
            positions_count=data.get('positions_count', 0),
        ))
        self.__session.commit()
        return 'added'

    def get_snapshots(self, account_id: str = 'all') -> list[PortfolioSnapshotDB]:
        return (
            self.__session.query(PortfolioSnapshotDB)
            .filter_by(account_id=account_id)
            .order_by(PortfolioSnapshotDB.date)
            .all()
        )

    def get_last_snapshot_date(self, account_id: str = 'all') -> date | None:
        row = (
            self.__session.query(PortfolioSnapshotDB)
            .filter_by(account_id=account_id)
            .order_by(PortfolioSnapshotDB.date.desc())
            .first()
        )
        return row.date.date() if row else None

    def get_last_index_value(self, account_id: str = 'all') -> float | None:
        row = (
            self.__session.query(PortfolioSnapshotDB)
            .filter_by(account_id=account_id)
            .order_by(PortfolioSnapshotDB.date.desc())
            .first()
        )
        return float(row.index_value) if row else None

    def clear(self, account_id: str = 'all') -> int:
        deleted = (
            self.__session.query(PortfolioSnapshotDB)
            .filter_by(account_id=account_id)
            .delete()
        )
        self.__session.commit()
        return deleted

    # ---------- Candle cache ----------

    def get_cached_candles(self, figi: str, date_from: date, date_to: date) -> dict:
        rows = (
            self.__session.query(CandleCacheDB)
            .filter(
                CandleCacheDB.figi == figi,
                CandleCacheDB.date >= datetime.combine(date_from, datetime.min.time()),
                CandleCacheDB.date <= datetime.combine(date_to, datetime.max.time()),
            )
            .all()
        )
        return {r.date.date(): float(r.close_price) for r in rows}

    def save_candles(self, figi: str, candles: dict) -> int:
        if not candles:
            return 0

        existing = {
            r.date.date() for r in
            self.__session.query(CandleCacheDB.date)
            .filter(
                CandleCacheDB.figi == figi,
                CandleCacheDB.date.in_([
                    datetime.combine(d, datetime.min.time()) for d in candles
                ]),
            )
            .all()
        }

        added = 0
        for d, price in candles.items():
            if d in existing:
                continue
            self.__session.add(CandleCacheDB(
                figi=figi,
                date=datetime.combine(d, datetime.min.time()),
                close_price=price,
            ))
            added += 1

        self.__session.commit()
        return added


    def get_snapshot(self, d: date, account_id: str = 'all') -> PortfolioSnapshotDB | None:
        """Возвращает снапшот за конкретную дату (или None)."""
        dt = datetime.combine(d, datetime.min.time())
        return (
            self.__session.query(PortfolioSnapshotDB)
            .filter_by(date=dt, account_id=account_id)
            .first()
        )