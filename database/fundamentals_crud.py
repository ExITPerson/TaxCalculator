"""CRUD для фундаментала акций (Smart-Lab).

Особенности:
- Ключевые метрики — колонками (CORE_FIELDS).
- Остальные — в extra_metrics (JSON).
- Флаги аномалий — в anomaly_flags (JSON) + has_anomaly (Boolean).
- При update создаём НОВЫЙ dict для JSON — иначе SQLAlchemy не видит изменений.
"""
import json
import logging
from datetime import datetime, timedelta

from database.db import StockFundamentalsDB

logger = logging.getLogger(__name__)


# ============================================================
# Поля, которые хранятся КОЛОНКАМИ
# ============================================================

CORE_FIELDS = {
    "revenue", "ebitda", "net_profit", "fcf",
    "roe", "roa", "roic",
    "debt_to_ebitda", "payout_ratio",
    "net_operating_income", "net_interest_income", "net_fee_income",
}


# ============================================================
# Флаги аномалий (Boolean)
# ============================================================

ANOMALY_FLAGS = {
    "roe_anomaly", "roa_anomaly", "payout_anomaly",
    "loss_making", "negative_equity",
    "revenue_anomaly", "ebitda_anomaly",
}


# ============================================================
# CRUD
# ============================================================

class StockFundamentalsCrud:
    def __init__(self, session):
        self.__session = session

    # ------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------

    def upsert(self, ticker: str, year: int, **metrics) -> None:
        """
        Вставляет или обновляет запись.

        metrics — словарь {field: value}:
        - CORE_FIELDS → колонки,
        - ANOMALY_FLAGS → anomaly_flags (JSON),
        - остальное → extra_metrics (JSON).
        """
        ticker = ticker.strip().upper()

        row = (
            self.__session.query(StockFundamentalsDB)
            .filter_by(ticker=ticker, year=year)
            .first()
        )

        # Разделяем входные метрики по назначению
        core_values: dict = {}
        extra_values: dict = {}
        anomaly_values: dict = {}

        for field, value in metrics.items():
            if value is None:
                continue

            if field in ANOMALY_FLAGS:
                anomaly_values[field] = bool(value)
            elif field in CORE_FIELDS:
                core_values[field] = value
            else:
                extra_values[field] = value

        if row:
            # ---- Update ----
            for k, v in core_values.items():
                setattr(row, k, v)

            # ВАЖНО: создаём НОВЫЙ dict, а не мутируем на месте
            existing_extra = dict(row.extra_metrics or {})
            existing_extra.update(extra_values)
            row.extra_metrics = existing_extra

            existing_flags = dict(row.anomaly_flags or {})
            existing_flags.update(anomaly_values)
            row.anomaly_flags = existing_flags
            row.has_anomaly = bool(existing_flags)

            row.updated_at = datetime.utcnow()
        else:
            # ---- Insert ----
            row = StockFundamentalsDB(
                ticker=ticker,
                year=year,
                **core_values,
                extra_metrics=dict(extra_values) if extra_values else None,
                anomaly_flags=dict(anomaly_values) if anomaly_values else None,
                has_anomaly=bool(anomaly_values),
            )
            self.__session.add(row)

        self.__session.commit()

    # ------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------

    def get(self, ticker: str, year: int) -> StockFundamentalsDB | None:
        return (
            self.__session.query(StockFundamentalsDB)
            .filter_by(ticker=ticker.strip().upper(), year=year)
            .first()
        )

    def get_history(self, ticker: str, years: int = 10) -> list:
        return (
            self.__session.query(StockFundamentalsDB)
            .filter(StockFundamentalsDB.ticker == ticker.strip().upper())
            .order_by(StockFundamentalsDB.year.desc())
            .limit(years)
            .all()
        )

    def get_latest(self, ticker: str) -> StockFundamentalsDB | None:
        return (
            self.__session.query(StockFundamentalsDB)
            .filter(StockFundamentalsDB.ticker == ticker.strip().upper())
            .order_by(StockFundamentalsDB.year.desc())
            .first()
        )

    def get_all_tickers(self) -> list[str]:
        rows = (
            self.__session.query(StockFundamentalsDB.ticker)
            .distinct()
            .all()
        )
        return [r[0] for r in rows]

    # ------------------------------------------------------------
    # Свежесть
    # ------------------------------------------------------------

    def is_stale(self, ticker: str, ttl_days: int = 7) -> bool:
        latest = self.get_latest(ticker)
        if not latest:
            return True
        age = datetime.utcnow() - latest.updated_at
        return age > timedelta(days=ttl_days)

    # ------------------------------------------------------------
    # Очистка
    # ------------------------------------------------------------

    def clear(self, ticker: str | None = None) -> int:
        q = self.__session.query(StockFundamentalsDB)
        if ticker:
            q = q.filter(StockFundamentalsDB.ticker == ticker.strip().upper())
        deleted = q.delete()
        self.__session.commit()
        return deleted

    def count(self) -> int:
        return self.__session.query(StockFundamentalsDB).count()