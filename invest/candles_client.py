import logging
import time
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import INVEST_TOKEN, API_TIMEOUT, API_RETRIES, CA_BUNDLE

logger = logging.getLogger(__name__)


URL_CANDLES = (
    "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
    ".MarketDataService/GetCandles"
)

WINDOW_DAYS = 119
PAUSE_BETWEEN = 0.15


class TInvestCandlesClient:
    """Дневные свечи по инструментам."""

    def __init__(self):
        self._headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {INVEST_TOKEN}',
        }
        self._session = requests.Session()
        self._session.headers.update(self._headers)
        self._timeout = API_TIMEOUT

        retry = Retry(
            total=API_RETRIES,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)

    def _fetch_window(self, figi: str, date_from: datetime, date_to: datetime) -> list:
        payload = {
            'instrumentId': figi,
            'from': date_from.strftime('%Y-%m-%dT00:00:00Z'),
            'to': date_to.strftime('%Y-%m-%dT23:59:59Z'),
            'interval': 'CANDLE_INTERVAL_DAY',
        }

        try:
            response = self._session.post(
                URL_CANDLES, json=payload,
                timeout=self._timeout, verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Сеть %s: %s", figi, e)
            return []

        if response.status_code != 200:
            logger.warning("%s: API %s: %s", figi, response.status_code, response.text[:200])
            return []

        try:
            return response.json().get('candles', [])
        except Exception:
            return []

    def fetch_candles(self, figi: str, date_from: datetime, date_to: datetime) -> dict:
        candles: dict = {}
        current = date_from

        while current < date_to:
            window_end = min(current + timedelta(days=WINDOW_DAYS), date_to)
            raw = self._fetch_window(figi, current, window_end)

            for c in raw:
                day = datetime.fromisoformat(c['time'].replace('Z', '+00:00')).date()
                close = c.get('close') or {}
                price = float(close.get('units', 0)) + float(close.get('nano', 0)) / 1e9
                candles[day] = price

            current = window_end + timedelta(days=1)
            time.sleep(PAUSE_BETWEEN)

        return candles

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()