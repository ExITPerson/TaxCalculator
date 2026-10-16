"""CRUD для кэша НКД."""
import logging
from datetime import date, datetime, timedelta

from database.db import AccruedInterestCacheDB

logger = logging.getLogger(__name__)


class AccruedInterestCrud:
    def __init__(self, session):
        self.__session = session

    def save(self, figi: str, date: date, value: float,
             nominal: float = None, value_percent: float = None) -> None:
        """Сохраняет НКД за конкретный день."""
        dt = datetime.combine(date, datetime.min.time())

        existing = (
            self.__session.query(AccruedInterestCacheDB)
            .filter_by(figi=figi, date=dt)
            .first()
        )

        if existing:
            existing.value = value
            existing.nominal = nominal
            existing.value_percent = value_percent
            existing.updated_at = datetime.utcnow()
        else:
            self.__session.add(AccruedInterestCacheDB(
                figi=figi,
                date=dt,
                value=value,
                nominal=nominal,
                value_percent=value_percent,
            ))

        self.__session.commit()

    def save_batch(self, figi: str, data: dict[date, float]) -> int:
        """
        Пакетное сохранение {date: value} для одного FIGI.
        Возвращает количество добавленных/обновлённых записей.
        """
        if not data:
            return 0

        count = 0
        for d, value in data.items():
            self.save(figi, d, value)
            count += 1

        logger.info("НКД %s: сохранено %d дней", figi, count)
        return count

    def get(self, figi: str, date: date) -> float | None:
        """НКД за конкретный день (или None)."""
        dt = datetime.combine(date, datetime.min.time())
        row = (
            self.__session.query(AccruedInterestCacheDB)
            .filter_by(figi=figi, date=dt)
            .first()
        )
        return float(row.value) if row else None

    def get_range(self, figi: str, date_from: date, date_to: date) -> dict[date, float]:
        """{date: value} за диапазон."""
        rows = (
            self.__session.query(AccruedInterestCacheDB)
            .filter(
                AccruedInterestCacheDB.figi == figi,
                AccruedInterestCacheDB.date >= datetime.combine(date_from, datetime.min.time()),
                AccruedInterestCacheDB.date <= datetime.combine(date_to, datetime.max.time()),
            )
            .all()
        )
        return {r.date.date(): float(r.value) for r in rows}

    def missing_dates(self, figi: str, date_from: date, date_to: date) -> set[date]:
        """Даты, за которые НКД ещё не загружен."""
        cached = set(self.get_range(figi, date_from, date_to).keys())

        all_days = set()
        current = date_from
        while current <= date_to:
            all_days.add(current)
            current += timedelta(days=1)

        return all_days - cached