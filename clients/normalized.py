from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OperationCategory(str, Enum):
    """ Классификация операций """
    INCOME = "Поступление"
    EXPENSE = "Расход"
    TAX_PAYMENT = "Налоговые платежи"
    INSURANCE_CONTRIBUTION = "Страховые взносы"
    COMMISSION = "Комиссия банка"
    SALARY_COMMISSION = "Комиссия за выплату ЗП"
    CARD_PAYMENT = "Оплата по карте"
    CARD_TRANSFER = "Перевод с карты"
    CASH_WITHDRAWAL = "Снятие наличных"
    SALARY = "Выплата ЗП"
    OVERNIGHT_DEPOSIT = "Перевод на депозит"
    OVERNIGHT_RETURN = "Возврат с депозита"
    OVERNIGHT_INCOME = "Доход от депозита"
    INTERNAL_TRANSFER = "Внутренний перевод"          # на второй расчётный / овернайт (игнор)
    OWN_FUNDS_TRANSFER = "Перевод собственных средств" # на личную карту / сторонний счёт (расход)
    CARD_DEPOSIT = "Пополнение с карты"
    COURT_BAILIFF = "Взыскание ФССП"
    UNKNOWN = "Не классифицировано"


@dataclass
class Counterparty:
    """Реквизиты контрагента по операции """
    name: str = ""
    inn: str = ""
    kpp: str = ""
    account: str = ""
    corr_account: str = ""
    bic: str = ""
    bank: str = ""


@dataclass
class NormalizedOperation:
    """ Нормализация классификации операций """
    operation_id: str
    date: datetime
    amount: float
    category: OperationCategory
    direction: str          # "IN" / "OUT" / "INTERNAL"
    counterparty: Counterparty
    description: str
    merchant: str | None = None