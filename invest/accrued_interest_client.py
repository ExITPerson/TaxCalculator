"""Клиент T-Invest API для получения НКД по облигациям.

Метод: InstrumentsService/GetAccruedInterests
https://developer.tbank.ru/invest/api/instruments-service-get-accrued-interests
"""
import logging
import time
from datetime import date, datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import INVEST_TOKEN, API_TIMEOUT, API_RETRIES, CA_BUNDLE

logger = logging.getLogger(__name__)


URL_ACCRUED_INTERESTS = (
    "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
    ".InstrumentsService/GetAccruedInterests"
)


class TInvestAccruedInterestClient:
    """Получение НКД по облигациям через T-Invest API."""

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

    def fetch_accrued_interests(
            self,
            instrument_uid: str,
            date_from: date,
            date_to: date,
    ) -> dict[date, float]:
        """
        Возвращает {date: НКД в рублях за 1 бумагу}.

        :param instrument_uid: UID облигации (НЕ FIGI!)
        :param date_from: начало периода
        :param date_to: конец периода
        """
        payload = {
            'instrumentId': instrument_uid,
            'from': datetime.combine(date_from, datetime.min.time()).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'to': datetime.combine(date_to, datetime.max.time()).strftime('%Y-%m-%dT%H:%M:%SZ'),
        }

        try:
            response = self._session.post(
                URL_ACCRUED_INTERESTS,
                json=payload,
                timeout=self._timeout,
                verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("НКД %s: сеть: %s", instrument_uid, e)
            return {}

        if response.status_code == 404:
            logger.debug("НКД %s: 404 (не облигация или нет данных)",
                         instrument_uid)
            return {}

        if response.status_code == 400:
            # Не облигация или другая причина — не логируем как warning
            logger.debug("НКД %s: 400 (не облигация)", instrument_uid)
            return {}

        if response.status_code != 200:
            logger.warning("НКД %s: API %s: %s",
                           instrument_uid, response.status_code,
                           response.text[:200])
            return {}

        try:
            data = response.json()
        except Exception:
            return {}

        accrued_list = data.get('accruedInterests', [])
        result: dict[date, float] = {}

        for item in accrued_list:
            try:
                date_str = item.get('date', '')
                d = datetime.fromisoformat(
                    date_str.replace('Z', '+00:00')
                ).date()

                value_obj = item.get('value') or {}
                units = float(value_obj.get('units', 0) or 0)
                nano = float(value_obj.get('nano', 0) or 0)
                value = units + nano / 1e9

                result[d] = value
            except Exception as e:
                logger.debug("НКД %s: ошибка парсинга: %s", instrument_uid, e)
                continue

        return result

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()