"""Метрики по каждой позиции: волатильность, Sharpe."""
import logging
import math
from datetime import date, datetime, timedelta

from config.settings import ACCOUNTS_ID
from database.db import Session
from database.instrument_crud import InstrumentCrud
from database.snapshot_crud import SnapshotCrud
from invest.candles_client import TInvestCandlesClient
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio

logger = logging.getLogger(__name__)


def _daily_returns(prices: list[float]) -> list[float]:
    result = []
    for i in range(1, len(prices)):
        prev, curr = prices[i - 1], prices[i]
        if prev > 0:
            result.append(curr / prev - 1)
    return result


def _annualized_volatility(prices: list[float]) -> float:
    returns = _daily_returns(prices)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


def _sharpe(prices: list[float], rf: float = 0.16) -> float:
    returns = _daily_returns(prices)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    annual_ret = (1 + mean) ** 252 - 1
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    annual_vol = math.sqrt(var) * math.sqrt(252)
    if annual_vol == 0:
        return 0.0
    return (annual_ret - rf) / annual_vol


def build_position_metrics(account_id: str | None = None,
                           days: int = 90) -> list[dict]:
    """
    Возвращает список метрик по каждой позиции:
      [{figi, ticker, name, quantity, current_price, value,
        volatility, sharpe}, ...]
    """
    accounts = [account_id] if account_id else ACCOUNTS_ID
    positions: list[dict] = []

    # 1. Текущие позиции из API
    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)
            for pos in p['positions']:
                if pos['quantity'] > 0 and pos['current_price'] > 0:
                    positions.append(pos)

    if not positions:
        return []

    # 2. Обогащаем тикерами из кэша
    with Session() as s:
        instr_info = InstrumentCrud(s).get_all()

    for pos in positions:
        info = instr_info.get(pos['figi'])
        if info:
            pos['ticker'] = info.ticker
            pos['name'] = info.name
            pos['sector'] = info.sector
        else:
            pos['ticker'] = None
            pos['name'] = None
            pos['sector'] = None

    # 3. Считаем метрики по свечам
    date_to = date.today()
    date_from = date_to - timedelta(days=days)

    with Session() as session:
        crud = SnapshotCrud(session)
        with TInvestCandlesClient() as client:
            for pos in positions:
                figi = pos['figi']

                try:
                    cached = crud.get_cached_candles(figi, date_from, date_to)

                    all_days = set()
                    current = date_from
                    while current <= date_to:
                        all_days.add(current)
                        current += timedelta(days=1)

                    missing = all_days - set(cached.keys())
                    if missing:
                        fetched = client.fetch_candles(
                            figi,
                            datetime.combine(min(missing), datetime.min.time()),
                            datetime.combine(max(missing), datetime.min.time()),
                        )
                        if fetched:
                            crud.save_candles(figi, fetched)
                            cached.update(fetched)

                    prices = [p for d, p in sorted(cached.items())]

                    if len(prices) < 5:
                        pos['volatility'] = None
                        pos['sharpe'] = None
                        continue

                    pos['volatility'] = round(_annualized_volatility(prices), 2)
                    pos['sharpe'] = round(_sharpe(prices), 3)

                except Exception as e:
                    logger.warning("Ошибка метрик для %s: %s", figi, e)
                    pos['volatility'] = None
                    pos['sharpe'] = None

    return positions