from datetime import datetime
from typing import List, Dict

import requests
import re

from clients.normalized import Counterparty, NormalizedOperation, OperationCategory
from config.settings import BUSINESS_TOKEN, BUSINESS_URL, PAYLOAD, MY_INN, BANK_INN, KBK_PENSION_PREFIX, \
    KBK_SOCIAL_PREFIX, KBK_ACCIDENT_PREFIX, TAX_AUTHORITY_INN, SOCIAL_FUND_INN
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TBankAPI:

    def __init__(self):
        self.__token = BUSINESS_TOKEN
        self._headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.__token}'
        }
        self.url = BUSINESS_URL
        self._payload = PAYLOAD
        self._my_inn = MY_INN
        self._bank_inn = BANK_INN

    def _connect(self) -> List[Dict]:
        """ Подключение к API, получение первоначальных данных """
        response = requests.get(self.url, headers=self._headers, params=self._payload, verify=False)

        if response.status_code != 200:
            return []

        return response.json()['operation']

    def _extract_merchant(self, purpose: str) -> str | None:
        m = re.search(r"\d{4}\.\.\.\d{4}\s+(.+?)\.\s*Договор", purpose)

        if m:
            return m.group(1).strip()

        return None

    def build_counterparty(self, raw: dict, direction: str) -> Counterparty:
        """
        Сбор реквизитов контрагента.
        Для поступлений (IN) — данные плательщика.
        Для расходов (OUT) — данные получателя.
        Для внутренних — данные второй стороны.
        """

        if direction == 'IN':
            prefix = 'payer'

        else:
            prefix = 'recipient'

        return Counterparty(
            name=raw.get(f'{prefix}Name', ''),
            inn=raw.get(f'{prefix}Inn', ''),
            kpp=raw.get(f'{prefix}Kpp', ''),
            account=raw.get(f'{prefix}Account', ''),
            corr_account=raw.get(f'{prefix}CorrAccount', ''),
            bic=raw.get(f'{prefix}Bic', ''),
            bank=raw.get(f'{prefix}Bank', '')
        )

    def classify_operation(self, raw: dict) -> NormalizedOperation:
        """ Нормализация операций для дальнейшего использования"""

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

        # 1. Налоговые платежи (ЕНП и прочие налоги через ФНС)
        if direction == "OUT" and (is_tax_authority or kbk.startswith("182")):
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

        # 6. Операции с депозитом "Овернайт"
        elif "овернайт" in purpose:
            if "возврат процентов" in purpose:
                category = OperationCategory.OVERNIGHT_INCOME
            elif "возврат" in purpose:
                category = OperationCategory.OVERNIGHT_RETURN
            elif "перевод на депозит" in purpose:
                category = OperationCategory.OVERNIGHT_DEPOSIT
            else:
                category = OperationCategory.INTERNAL_TRANSFER

        # 7. Выплата ЗП физлицам
        elif is_salary:
            category = OperationCategory.SALARY

        # 8. Поступления от контрагентов
        elif direction == "IN" and raw["operationType"] == "01":
            category = OperationCategory.INCOME

        # 9. Расходы — внешние переводы третьим лицам
        elif direction == "OUT" and raw["operationType"] == "01":
            category = OperationCategory.EXPENSE

        # 10. Прочие внутренние переводы
        elif direction == "INTERNAL":
            category = OperationCategory.INTERNAL_TRANSFER

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
            raw=raw,
        )

    def get_operations(self):
        data = self._connect()

        operations = [self.classify_operation(op) for op in data]

        return operations
