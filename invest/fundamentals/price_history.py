"""История цен с MOEX ISS (для перцентиля P/E за 10 лет)."""
import logging
from datetime import date, datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

MOEX_BASE = "https://iss.moex.com/iss"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    return s


def fetch_price_history(ticker: str, days: int = 3650) -> dict[date, float]:
    """
    Загружает историю цен закрытия с MOEX ISS.

    :param ticker: тикер (SBER, GAZP, ...)
    :param days: сколько дней назад (3650 ≈ 10 лет)
    :return: {date: close_price}
    """
    date_to = date.today()
    date_from = date_to - timedelta(days=days)

    url = (f"{MOEX_BASE}/history/engines/stock/markets/shares/"
           f"boards/TQBR/securities/{ticker}.json")

    session = _make_session()
    prices: dict[date, float] = {}
    start = 0

    while True:
        params = {
            "from": date_from.isoformat(),
            "till": date_to.isoformat(),
            "start": start,
        }
        try:
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
        except Exception as e:
            logger.error("MOEX ISS %s: %s", ticker, e)
            return prices

        data = r.json()
        history = data.get("history", {})
        columns = history.get("columns", [])
        rows = history.get("data", [])

        if not rows:
            break

        idx_date = columns.index("TRADEDATE")
        idx_close = columns.index("CLOSE")

        for row in rows:
            try:
                d = datetime.fromisoformat(row[idx_date]).date()
                p = float(row[idx_close])
                if p > 0:
                    prices[d] = p
            except (ValueError, TypeError, IndexError):
                continue

        start += len(rows)
        if len(rows) < 100:
            break

    logger.info("MOEX ISS %s: загружено %d дней", ticker, len(prices))
    return prices


def get_price_on_or_before(prices: dict[date, float], target: date) -> float | None:
    """Ближайшая цена ≤ target."""
    for d in sorted(prices.keys(), reverse=True):
        if d <= target:
            return prices[d]
    return None