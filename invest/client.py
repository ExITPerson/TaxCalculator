import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import (
    INVEST_TOKEN, INVEST_URL, ACCOUNTS_ID,
    API_TIMEOUT, API_RETRIES, CA_BUNDLE,
    INVEST_DATE_FROM,
)
from invest.date_windows import split_period

logger = logging.getLogger(__name__)


class TInvestClient:
    """HTTP-клиент T-Invest с разбивкой периода на окна и пагинацией."""

    def __init__(self):
        self._headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {INVEST_TOKEN}',
        }
        self._url = INVEST_URL
        self._timeout = API_TIMEOUT
        self._session = requests.Session()
        self._session.headers.update(self._headers)

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

    def _fetch_page(
        self,
        account_id: str,
        date_from: str,
        date_to: str,
        cursor: str | None = None,
    ) -> dict | None:
        """Одна страница одного окна."""
        payload = {
            'accountId': account_id,
            'from': date_from,
            'to': date_to,
        }
        if cursor:
            payload['cursor'] = cursor

        try:
            response = self._session.post(
                self._url,
                json=payload,
                timeout=self._timeout,
                verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Сеть: счёт %s, окно %s–%s: %s",
                         account_id, date_from, date_to, e)
            return None

        if response.status_code == 401:
            logger.error("401 Unauthorized — проверь INVEST_TOKEN")
            return None
        if response.status_code == 400:
            # 400 при слишком широком окне / неверном формате
            logger.warning(
                "400 Bad Request: счёт %s, окно %s–%s: %s",
                account_id, date_from, date_to, response.text[:300],
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "API вернул %s: счёт %s: %s",
                response.status_code, account_id, response.text[:300],
            )
            return None

        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as e:
            logger.error("JSON-ошибка: счёт %s: %s", account_id, e)
            return None

    def _fetch_window(
        self,
        account_id: str,
        date_from: str,
        date_to: str,
    ) -> list[dict]:
        """Все страницы одного окна."""
        result: list[dict] = []
        cursor: str | None = None
        page = 0

        while True:
            page += 1
            data = self._fetch_page(account_id, date_from, date_to, cursor)
            if not data:
                break

            ops = data.get('operations') or []
            result.extend(ops)

            logger.info(
                "Счёт %s: окно %s–%s, стр. %d, %d операций",
                account_id, date_from[:10], date_to[:10], page, len(ops),
            )

            cursor = data.get('nextCursor')
            if not cursor or not ops:
                break

            time.sleep(0.2)

        return result

    def fetch_operations(self) -> list[dict]:
        """Забирает все операции со всех счетов, разбивая период на окна ≤ 31 день."""
        all_ops: list[dict] = []
        windows = split_period(INVEST_DATE_FROM)
        logger.info("Период разбит на %d окон", len(windows))

        for acc_id in ACCOUNTS_ID:
            logger.info("Счёт %s: старт...", acc_id)

            for date_from, date_to in windows:
                ops = self._fetch_window(acc_id, date_from, date_to)

                for op in ops:
                    op['_account_id'] = acc_id
                all_ops.extend(ops)

                time.sleep(0.3)   # мягкая пауза между окнами

        logger.info("Всего загружено операций: %d", len(all_ops))
        return all_ops

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "TInvestClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()