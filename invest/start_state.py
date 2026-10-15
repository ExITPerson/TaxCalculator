"""Вычисляет начальные позиции и кэш на заданную дату."""
import logging
from datetime import date, datetime

from sqlalchemy import func

from config.settings import ACCOUNTS_ID
from database.db import Session, InvestOperationDB
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio

logger = logging.getLogger(__name__)


CURRENCY_FIGIS = {'RUB000UTSTOM'}


def compute_start_state(target_date: date,
                        accounts: list[str] | None = None) -> tuple[dict, float]:
    """
    Возвращает (start_positions, start_cash) на конец target_date.

    start_positions — {figi: quantity} на конец дня.
    start_cash — кэш на конец дня (уже включает валютные позиции из API).
    """
    accounts = accounts or ACCOUNTS_ID

    current_positions: dict[str, float] = {}
    current_cash = 0.0

    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)

            for pos in p['positions']:
                figi = pos['figi']
                qty = pos['quantity']

                if figi in CURRENCY_FIGIS:
                    # Рубли уже в total_amount_currencies — не считаем повторно
                    continue

                if qty == 0:
                    continue

                current_positions[figi] = current_positions.get(figi, 0.0) + qty

            current_cash += p['total_amount_currencies']

    logger.info("Текущий портфель: %d FIGI, кэш=%.2f",
                len(current_positions), current_cash)

    # Откат сделок
    with Session() as s:
        trades = (
            s.query(InvestOperationDB)
            .filter(
                InvestOperationDB.kind.in_(['buy', 'sell']),
                InvestOperationDB.figi.isnot(None),
                InvestOperationDB.date > datetime.combine(target_date, datetime.max.time()),
            )
            .all()
        )

        start_positions = dict(current_positions)
        for t in trades:
            qty = float(t.quantity or 0)
            delta = qty if t.kind == 'buy' else -qty
            start_positions[t.figi] = start_positions.get(t.figi, 0.0) - delta

        start_positions = {
            k: v for k, v in start_positions.items()
            if abs(v) > 1e-6 and k not in CURRENCY_FIGIS
        }

        # Откат кэша
        total_after = (
            s.query(func.coalesce(func.sum(InvestOperationDB.payment_amount), 0))
            .filter(
                InvestOperationDB.date > datetime.combine(target_date, datetime.max.time()),
            )
            .scalar()
        )
        start_cash = current_cash - float(total_after or 0)

    logger.info("Начальное состояние на %s: %d FIGI, start_cash=%.2f",
                target_date, len(start_positions), start_cash)

    return start_positions, start_cash