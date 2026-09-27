from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class OperationCategory(str, Enum):
    """ Классификация операций """
    INCOME = "Поступление"
    EXPENSE = "Расход"
    COMMISSION = "Комиссия банка"
    CARD_PAYMENT = "Оплата по карте"
    OVERNIGHT_DEPOSIT = "Перевод на депозит"
    OVERNIGHT_RETURN = "Возврат с депозита"
    OVERNIGHT_INCOME = "Доход от депозита"
    INTERNAL_TRANSFER = "Внутренний перевод"
    UNKNOWN = "Не классифицировано"

@dataclass
class Counterparty:
    """Реквизиты контрагента по операции."""
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
    raw: dict = field(default_factory=dict, repr=False)

