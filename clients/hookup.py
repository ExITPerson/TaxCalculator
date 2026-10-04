import logging
import re
import time
from datetime import datetime
from typing import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from clients.normalized import Counterparty, NormalizedOperation, OperationCategory
from config.settings import (
    BUSINESS_TOKEN, BUSINESS_URL, build_payload, MY_INN, BANK_INN,
    KBK_TAX_PREFIX, KBK_PENSION_PREFIX, KBK_SOCIAL_PREFIX, KBK_ACCIDENT_PREFIX,
    TAX_AUTHORITY_INN, SOCIAL_FUND_INN, OPERATION_TYPE_PAYMENT,
    API_TIMEOUT, API_RETRIES, CA_BUNDLE, OPERATION_TYPE_CARD, INVEST_TOKEN, INVEST_URL, build_invest_payload,
    URL_PORTFOLIO,
)

logger = logging.getLogger(__name__)


SALARY_KEYWORDS = ("аванс", "зарплат", "зп ", "заработн", "оклад", "за вычетом")
SALARY_COMMISSION_KEYWORDS = ("функций агента вк", "вфавк")
BANK_COMMISSION_KEYWORDS = ("плата за", "комиссия")


class TBankClient:
    """ Только HTTP: сессия, ретраи, пагинация """

    def __init__(self) -> None:
        self._headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {BUSINESS_TOKEN}',
        }
        self.url = BUSINESS_URL
        self._timeout = API_TIMEOUT

        self._session = requests.Session()
        self._session.headers.update(self._headers)

        retry = Retry(
            total=API_RETRIES,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)

    def fetch_operations(self) -> list[dict]:
        """ Забирает операции """
        payload = build_payload()
        all_ops: list[dict] = []
        page = 0

        while True:
            page += 1
            try:
                response = self._session.get(
                    self.url,
                    params=payload,
                    timeout=self._timeout,
                    verify=CA_BUNDLE,
                )

            # if response.status_code == 401:
            #     logger.error("401 Unauthorized — проверь BUSINESS_TOKEN")
            #     # break
            # if response.status_code != 200:
            #     logger.warning(
            #         "API вернул %s: %s", response.status_code, response.text[:300]
            #     )
            #
            # data = response.json()
            # ops = data.get('operation', [])
            #
            # return ops

            except requests.RequestException as e:
                logger.error("Ошибка сети при запросе операций: %s", e)
                break

            if response.status_code == 401:
                logger.error("401 Unauthorized — проверь BUSINESS_TOKEN")
                # break
            if response.status_code != 200:
                logger.warning(
                    "API вернул %s: %s", response.status_code, response.text[:300]
                )
                break

            data = response.json()
            ops = data.get('operation', [])
            all_ops.extend(ops)

            logger.info("Страница %d: получено %d операций", page, len(ops))

            next_cursor = data.get('nextCursor') or data.get('cursor')
            if not next_cursor or not ops:
                break

            payload['cursor'] = next_cursor
        #мягкая защита от бесконечного цикла
            time.sleep(0.1)

        return all_ops

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "TBankClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class OperationClassifier:
    """ Класс классификации данных """

    def __init__(self, my_inn: str, bank_inn: str) -> None:
        self._my_inn = my_inn
        self._bank_inn = bank_inn

    def _extract_merchant(self, purpose: str) -> str | None:
        m = re.search(r"\d{4}\.\.\.\d{4}\s+(.+?)\.\s*Договор", purpose)

        if m:
            return m.group(1).strip()

        logger.debug("Не удалось извлечь merchant из: %s", purpose[:120])
        return None

    def build_counterparty(self, raw: dict, direction: str) -> Counterparty:
        prefix = 'payer' if direction == 'IN' else 'recipient'
        return Counterparty(
            name=raw.get(f'{prefix}Name', ''),
            inn=raw.get(f'{prefix}Inn', ''),
            kpp=raw.get(f'{prefix}Kpp', ''),
            account=raw.get(f'{prefix}Account', ''),
            corr_account=raw.get(f'{prefix}CorrAccount', ''),
            bic=raw.get(f'{prefix}Bic', ''),
            bank=raw.get(f'{prefix}Bank', ''),
        )

    def classify(self, raw: dict) -> NormalizedOperation:
        """ Нормализация операций для дальнейшего использования """

        purpose = raw.get('paymentPurpose', '').lower()
        purpose_raw = raw.get('paymentPurpose', '')
        is_self_payer = raw['payerInn'] == self._my_inn
        is_self_recipient = raw['recipientInn'] == self._my_inn
        is_bank_recipient = raw['recipientInn'] == self._bank_inn

        # Направление движения средств
        if not is_self_payer and is_self_recipient:
            direction = "IN"
        elif is_self_payer and not is_self_recipient:
            direction = "OUT"
        else:
            direction = "INTERNAL"

        merchant = None
        kbk = raw.get('kbk', '')

        # Проверка на госорганы
        is_tax_authority = raw['recipientInn'] == TAX_AUTHORITY_INN
        is_social_fund = raw['recipientInn'] == SOCIAL_FUND_INN

        # Ключевые слова для выплаты ЗП
        salary_keywords = ["аванс", "зарплат", "зп ", "заработн", "оклад", "за вычетом"]
        is_salary = (
                direction == "OUT"
                and raw["operationType"] == "01"
                and any(kw in purpose for kw in salary_keywords)
        )

        # ============ Овернайт (operationType == "17", внутренние переводы) ============
        # Идёт ПЕРВЫМ, потому что у овернайта тип 17 и направление INTERNAL,
        # без этой ветки он уедет в EXPENSE/UNKNOWN.
        if "овернайт" in purpose:
            if "возврат процентов" in purpose:
                category = OperationCategory.OVERNIGHT_INCOME
            elif "возврат д/с" in purpose or "возврат" in purpose:
                category = OperationCategory.OVERNIGHT_RETURN
            elif "перевод на депозит" in purpose:
                category = OperationCategory.OVERNIGHT_DEPOSIT
            else:
                category = OperationCategory.INTERNAL_TRANSFER

        # ============ Операции по карте (operationType == "17") ============
        # Овернайт уже пойман выше. Здесь — снятие, переводы через МПС,
        # оплата услуг, эквайринг.
        elif raw["operationType"] == "17":
            if "снятие наличных" in purpose or "атм" in purpose:
                category = OperationCategory.CASH_WITHDRAWAL
            elif "перевод средств по реквизитам карты" in purpose or "мпс" in purpose:
                category = OperationCategory.CARD_TRANSFER
            elif "оплаты по карте" in purpose or "оплата по карте" in purpose:
                category = OperationCategory.CARD_PAYMENT
                merchant = self._extract_merchant(purpose_raw)
            elif "оплата услуг" in purpose or "мобильной связи" in purpose:
                category = OperationCategory.EXPENSE
            elif direction == "IN":
                category = OperationCategory.INCOME
            else:
                category = OperationCategory.EXPENSE

        # 1. Налоговые платежи (ЕНП и прочие налоги через ФНС)
        elif direction == "OUT" and (is_tax_authority or kbk.startswith("182")):
            category = OperationCategory.TAX_PAYMENT

        # 2. Страховые и пенсионные взносы
        elif direction == "OUT" and (
                is_social_fund
                or kbk.startswith((KBK_PENSION_PREFIX, KBK_SOCIAL_PREFIX, KBK_ACCIDENT_PREFIX))
                or "страховые взносы" in purpose
                or "пенсионн" in purpose
        ):
            category = OperationCategory.INSURANCE_CONTRIBUTION

        # 3. Комиссии за выплату ЗП (ВК)
        elif is_bank_recipient and any(kw in purpose for kw in ["функций агента вк", "вфавк"]):
            category = OperationCategory.SALARY_COMMISSION

        # 4. Прочие комиссии и платы банка
        elif is_bank_recipient and any(kw in purpose for kw in ["плата за", "комиссия"]):
            category = OperationCategory.COMMISSION

        # 5. Оплата по карте
        elif "оплаты по карте" in purpose:
            category = OperationCategory.CARD_PAYMENT
            merchant = self._extract_merchant(purpose_raw)

        # 6. Выплата ЗП физлицам
        elif is_salary:
            category = OperationCategory.SALARY

        # 7. Поступления от контрагентов
        elif direction == "IN" and raw["operationType"] == "01":
            category = OperationCategory.INCOME

        # 8. Расходы — внешние переводы третьим лицам
        elif direction == "OUT" and raw["operationType"] == "01":
            category = OperationCategory.EXPENSE

        # 9. Прочие внутренние переводы
        elif direction == "INTERNAL":
            category = OperationCategory.INTERNAL_TRANSFER

        # 10. Взыскания ФССП
        elif raw["operationType"] == "06" and "обращ. взыск" in purpose:
            category = OperationCategory.COURT_BAILIFF

        else:
            category = OperationCategory.UNKNOWN

        counterparty = self.build_counterparty(raw, direction)

        return NormalizedOperation(
            operation_id=raw["operationId"],
            date=datetime.fromisoformat(raw["date"]),
            amount=raw["amount"],
            category=category,
            direction=direction,
            counterparty=counterparty,
            description=purpose_raw,
            merchant=merchant,
        )


class TBankAPI:
    """Итоговый класс получения из API и классификации """

    def __init__(self) -> None:
        self._client = TBankClient()
        self._classifier = OperationClassifier(my_inn=MY_INN, bank_inn=BANK_INN)

    def get_operations(self) -> Iterator[NormalizedOperation]:
        raw_ops = self._client.fetch_operations()
        for raw in raw_ops:
            try:
                yield self._classifier.classify(raw)
            except (KeyError, ValueError) as e:
                logger.warning("Пропущена операция %s: %s", raw.get('operationId'), e)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TBankAPI":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _connect(self) -> list[dict]:
        """ Для проверок операций """
        return self._client.fetch_operations()

    def classify_operation(self, raw: dict) -> NormalizedOperation:
        """ Для проверок классификаций """
        return self._classifier.classify(raw)

#----------------------------------------------------------------------------------------------------------
#                                             ИНВЕСТИЦИИИ
#----------------------------------------------------------------------------------------------------------

class TInvestClient:
    """ Только HTTP: сессия, ретраи, пагинация"""

    def __init__(self):
        self._header = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {INVEST_TOKEN}'
        }
        self._url = INVEST_URL
        self._session = requests.Session()
        self._session.headers.update(self._header)
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

    def fetch_operations(self) -> list[dict]:
        """ Забирает операции """
        payload = build_invest_payload()

        try:
            response = self._session.post(
                self._url,
                json=payload,
                timeout=self._timeout,
                verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Ошибка сети при запросе операций: %s", e)
            return []

        # Логируем статус
        if response.status_code == 401:
            logger.error("401 Unauthorized — проверь INVEST_TOKEN")
            return []
        if response.status_code != 200:
            logger.warning(
                "API вернул %s: %s", response.status_code, response.text[:300]
            )
            return []

        # Защита от пустого/не-JSON тела
        if not response.text.strip():
            logger.warning("Пустой ответ от API")
            return []

        try:
            data = response.json().get('operations')
        except requests.exceptions.JSONDecodeError as e:
            logger.error("Не удалось распарсить JSON: %s\nОтвет: %s", e, response.text[:500])
            return []

        return data

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "TInvestClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class TInvestPortfolio:
    """ Получение информации о портфеле """

    def __init__(self):
        self._header = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {INVEST_TOKEN}'
        }
        self._url = URL_PORTFOLIO
        self._session = requests.Session()
        self._session.headers.update(self._header)
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

    def fetch_portfolio(self) -> list[dict]:
        payload = build_invest_payload('portfolio')

        try:
            response = self._session.post(
                self._url,
                json=payload,
                timeout=self._timeout,
                verify=CA_BUNDLE,
            )
        except requests.RequestException as e:
            logger.error("Ошибка сети при запросе операций: %s", e)
            return []

        # Логируем статус
        if response.status_code == 401:
            logger.error("401 Unauthorized — проверь INVEST_TOKEN")
            return []
        if response.status_code != 200:
            logger.warning(
                "API вернул %s: %s", response.status_code, response.text[:300]
            )
            return []

        # Защита от пустого/не-JSON тела
        if not response.text.strip():
            logger.warning("Пустой ответ от API")
            return []

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as e:
            logger.error("Не удалось распарсить JSON: %s\nОтвет: %s", e, response.text[:500])
            return []

        return data

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "TInvestPortfolio":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class InvestOperationsClassifier:
    pass


class TInvestAPI:
    pass

