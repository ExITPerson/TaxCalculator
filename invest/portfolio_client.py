import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import (
    INVEST_TOKEN, API_TIMEOUT, API_RETRIES, CA_BUNDLE,
)
from invest.models import Money

logger = logging.getLogger(__name__)


# URL метода GetPortfolio (тот же OperationsService, другой метод)
URL_PORTFOLIO = (
    "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
    ".OperationsService/GetPortfolio"
)


class TInvestPortfolioClient:
    """Получение текущего портфеля по счёту."""

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

    def fetch_portfolio(self, account_id: str) -> dict | None:
        """Забирает портфель по счёту."""
        payload = {'accountId': account_id, 'currency': 'RUB'}

        try:
            response = self._session.post(
                URL_PORTFOLIO,
                json=payload,
                timeout=self._timeout,
                verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Сеть: счёт %s: %s", account_id, e)
            return None

        if response.status_code == 401:
            logger.error("401 Unauthorized — проверь INVEST_TOKEN")
            return None
        if response.status_code != 200:
            logger.warning(
                "Счёт %s: API вернул %s: %s",
                account_id, response.status_code, response.text[:300],
            )
            return None

        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as e:
            logger.error("JSON-ошибка для счёта %s: %s", account_id, e)
            return None

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def parse_portfolio(raw: dict) -> dict:
    """Превращает сырой ответ в нормализованный словарь."""
    positions = []

    for p in raw.get('positions', []):
        # Пропускаем валютные позиции (money) — там нет figi
        figi = p.get('figi', '')
        if not figi:
            continue

        positions.append({
            'figi': figi,
            'instrument_uid': p.get('instrumentUid', ''),
            'instrument_type': p.get('instrumentType', ''),
            'quantity': float(Money.from_api(p.get('quantity')).amount),
            'average_price': float(Money.from_api(p.get('averagePositionPrice')).amount),
            'current_price': float(Money.from_api(p.get('currentPrice')).amount),
            'expected_yield': float(Money.from_api(p.get('expectedYield')).amount),
            'currency': p.get('averagePositionPrice', {}).get('currency', 'rub'),
        })

    return {
        'total_amount_portfolio': float(Money.from_api(raw.get('totalAmountPortfolio')).amount),
        'total_amount_shares': float(Money.from_api(raw.get('totalAmountShares')).amount),
        'total_amount_bonds': float(Money.from_api(raw.get('totalAmountBonds')).amount),
        'total_amount_etf': float(Money.from_api(raw.get('totalAmountEtf')).amount),
        'total_amount_currencies': float(Money.from_api(raw.get('totalAmountCurrencies')).amount),
        'expected_yield': float(Money.from_api(raw.get('expectedYield')).amount),
        'positions': positions,
    }

def fetch_current_prices(accounts: list[str] | None = None) -> dict[str, float]:
    """
    {figi: current_price} по всем счетам.
    Используется для коррекции свечей.
    """
    from config.settings import ACCOUNTS_ID
    accounts = accounts or ACCOUNTS_ID

    prices: dict[str, float] = {}

    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)
            for pos in p['positions']:
                figi = pos['figi']
                price = pos['current_price']
                qty = pos['quantity']
                if qty > 0 and price > 0:
                    prices[figi] = price

    return prices