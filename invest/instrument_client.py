"""Клиент для получения информации об инструментах через T-Invest API."""
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import INVEST_TOKEN, API_TIMEOUT, API_RETRIES, CA_BUNDLE

logger = logging.getLogger(__name__)


URL_INSTRUMENT = (
    "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
    ".InstrumentsService/GetInstrumentBy"
)

URL_BONDS = (
    "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
    ".InstrumentsService/Bonds"
)


class TInvestInstrumentClient:
    """Получение информации об инструменте по figi."""

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

    def fetch_instrument(self, figi: str) -> dict | None:
        """
        Возвращает {'ticker': ..., 'name': ..., 'instrument_type': ..., 'sector': ...}
        или None.
        """
        payload = {
            'idType': 'INSTRUMENT_ID_TYPE_FIGI',
            'id': figi,
        }

        try:
            r = self._session.post(
                URL_INSTRUMENT, json=payload,
                timeout=self._timeout, verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Сеть: %s: %s", figi, e)
            return None

        if r.status_code != 200:
            logger.warning("API %s для %s: %s", r.status_code, figi, r.text[:200])
            return None

        try:
            data = r.json().get('instrument', {})
        except Exception:
            return None

        return {
            'ticker': data.get('ticker'),
            'name': data.get('name'),
            'instrument_type': (data.get('instrumentType') or '').lower(),
            'sector': data.get('sector'),
            'instrument_uid': data.get('uid'),  # ← НОВОЕ
        }

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def fetch_bond_by_isin(self, isin: str) -> dict | None:
        """
        Ищет облигацию по ISIN через InstrumentsService/Bonds.
        Возвращает данные основной записи (приоритет — TQCB / TQOB).
        """
        payload = {'instrumentStatus': 'INSTRUMENT_STATUS_ALL'}

        try:
            r = self._session.post(
                URL_BONDS, json=payload,
                timeout=self._timeout, verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Сеть: Bonds: %s", e)
            return None

        if r.status_code != 200:
            logger.warning("Bonds API: %s", r.status_code)
            return None

        try:
            data = r.json()
        except Exception:
            return None

        bonds = data.get('instruments', [])
        matches = [b for b in bonds if b.get('isin') == isin]

        if not matches:
            return None

        # Приоритет: TQCB (основной режим MOEX) → TQOB → первый
        priority = ['TQCB', 'TQOB', 'TQIF', 'TQTC']
        main = None
        for code in priority:
            for b in matches:
                if b.get('classCode') == code:
                    main = b
                    break
            if main:
                break

        if not main:
            main = matches[0]

        return {
            'figi': main.get('figi'),
            'ticker': main.get('ticker'),
            'isin': main.get('isin'),
            'name': main.get('name'),
            'instrument_type': 'bond',
            'sector': main.get('sector'),
            'instrument_uid': main.get('uid'),
            'class_code': main.get('classCode'),
        }