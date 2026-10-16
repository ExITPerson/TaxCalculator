from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OperationKind(str, Enum):
    """Внутренняя классификация операции."""
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    BUY = "buy"
    SELL = "sell"
    COUPON = "coupon"
    DIVIDEND = "dividend"
    BOND_REPAYMENT = "bond_repayment"
    AMORTIZATION = "amortization"
    FEE = "fee"
    MARGIN_FEE = "margin_fee"
    TAX = "tax"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class AssetType(str, Enum):
    SHARE = "share"
    BOND = "bond"
    ETF = "etf"
    CURRENCY = "currency"
    FUTURES = "futures"
    OPTION = "option"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Money:
    """Денежная сумма. Decimal — чтобы не терять копейки."""
    amount: Decimal
    currency: str = "rub"

    @classmethod
    def from_api(cls, obj: dict | None, default_currency: str = "rub") -> "Money":
        if not obj:
            return cls(Decimal("0"), default_currency)
        units = Decimal(str(obj.get("units", 0)))
        nano = Decimal(str(obj.get("nano", 0)))
        amount = units + nano / Decimal("1000000000")
        return cls(amount, obj.get("currency", default_currency))

    def __float__(self) -> float:
        return float(self.amount)


@dataclass
class BaseOperation:
    """Общие поля для всех операций."""
    id: str
    date: datetime
    kind: OperationKind
    raw_type: str
    operation_type: str
    state: str
    payment: Money
    parent_id: str | None = None
    account_id: str | None = None


@dataclass
class Trade(BaseOperation):
    """Сделка покупки/продажи."""
    figi: str = ""
    instrument_uid: str = ""
    instrument_type: AssetType = AssetType.UNKNOWN
    quantity: Decimal = Decimal("0")
    price_per_unit: Money = field(default_factory=lambda: Money(Decimal("0")))
    total: Money = field(default_factory=lambda: Money(Decimal("0")))

    @property
    def direction(self) -> str:
        return "buy" if self.kind == OperationKind.BUY else "sell"

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.kind == OperationKind.BUY else -self.quantity


@dataclass
class Income(BaseOperation):
    """Доход по активу."""
    figi: str = ""
    instrument_uid: str = ""
    instrument_type: AssetType = AssetType.UNKNOWN


@dataclass
class Fee(BaseOperation):
    """Комиссия или налог."""
    figi: str = ""
    instrument_uid: str = ""


@dataclass
class CashFlow(BaseOperation):
    """Пополнение или вывод."""
    pass