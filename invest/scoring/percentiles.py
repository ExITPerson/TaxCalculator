"""Перцентиль P/E за 10 лет."""
import logging
from datetime import date

from database.db import Session
from database.fundamentals_crud import StockFundamentalsCrud
from invest.fundamentals.price_history import (
    fetch_price_history, get_price_on_or_before,
)

logger = logging.getLogger(__name__)


def compute_pe_history(ticker: str, years: int = 10) -> list[float]:
    """
    Исторический P/E по годам.
    Использует market_cap / net_profit — это надёжнее price / eps,
    потому что market_cap со Smart-Lab уже скорректирован на сплиты.
    """
    with Session() as s:
        crud = StockFundamentalsCrud(s)
        history = crud.get_history(ticker, years=years)

    if not history:
        return []

    pe_values = []
    for row in history:
        net_profit = _to_float(row.net_profit)
        if not net_profit or net_profit <= 0:
            continue

        extra = row.extra_metrics or {}
        market_cap = _to_float(extra.get("market_cap"))
        if not market_cap or market_cap <= 0:
            continue

        pe = market_cap / net_profit
        if 0 < pe < 100:
            pe_values.append(pe)

    # Отсекаем выбросы: всё, что > 3× медианы
    if len(pe_values) >= 3:
        median = sorted(pe_values)[len(pe_values) // 2]
        pe_values = [p for p in pe_values if p <= 3 * median]

    return pe_values

def pe_percentile(ticker: str, years: int = 10) -> dict | None:
    """
    Перцентиль P/E за N лет.
    """
    with Session() as s:
        crud = StockFundamentalsCrud(s)
        latest = crud.get_latest(ticker)

    if not latest:
        return None

    # pe — только в extra_metrics
    extra = latest.extra_metrics or {}
    current_pe = _to_float(extra.get("pe"))

    # Если нет — считаем сами: market_cap / net_profit
    if current_pe is None or current_pe <= 0:
        market_cap = _to_float(extra.get("market_cap"))
        net_profit = _to_float(latest.net_profit)
        if market_cap and net_profit and net_profit > 0:
            current_pe = market_cap / net_profit

    if current_pe is None or current_pe <= 0:
        return None

    pe_history = compute_pe_history(ticker, years=years)
    if len(pe_history) < 3:
        return None

    below = sum(1 for p in pe_history if p <= current_pe)
    percentile = below / len(pe_history)

    pe_history_sorted = sorted(pe_history)
    median = pe_history_sorted[len(pe_history_sorted) // 2]

    if percentile < 0.3:
        verdict = "cheap"
    elif percentile > 0.7:
        verdict = "expensive"
    else:
        verdict = "fair"

    return {
        "current_pe": round(current_pe, 2),
        "percentile": round(percentile, 3),
        "min": round(min(pe_history), 2),
        "max": round(max(pe_history), 2),
        "median": round(median, 2),
        "n_years": len(pe_history),
        "verdict": verdict,
    }


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None