from datetime import datetime
from decimal import Decimal

from invest.models import (
    Money, OperationKind, AssetType,
    Trade, Income, Fee, CashFlow, BaseOperation,
)


KIND_MAP = {
    "OPERATION_TYPE_BUY":              OperationKind.BUY,
    "OPERATION_TYPE_SELL":             OperationKind.SELL,
    "OPERATION_TYPE_COUPON":           OperationKind.COUPON,
    "OPERATION_TYPE_DIVIDEND":         OperationKind.DIVIDEND,
    "OPERATION_TYPE_BOND_REPAYMENT":   OperationKind.BOND_REPAYMENT,
    "OPERATION_TYPE_AMORTIZATION":     OperationKind.AMORTIZATION,
    "OPERATION_TYPE_BROKER_FEE":       OperationKind.FEE,
    "OPERATION_TYPE_MARGIN_FEE":       OperationKind.MARGIN_FEE,
    "OPERATION_TYPE_TAX":              OperationKind.TAX,
    "OPERATION_TYPE_DIVIDEND_TAX":     OperationKind.TAX,
    "OPERATION_TYPE_INPUT":            OperationKind.DEPOSIT,
    "OPERATION_TYPE_INP_MULTI":        OperationKind.DEPOSIT,
    "OPERATION_TYPE_OUTPUT":           OperationKind.WITHDRAW,
    "OPERATION_TYPE_OUT_MULTI":        OperationKind.WITHDRAW,
}

TRADE_KINDS = {OperationKind.BUY, OperationKind.SELL}
INCOME_KINDS = {
    OperationKind.COUPON, OperationKind.DIVIDEND,
    OperationKind.BOND_REPAYMENT, OperationKind.AMORTIZATION,
}
FEE_KINDS = {OperationKind.FEE, OperationKind.MARGIN_FEE, OperationKind.TAX}
CASHFLOW_KINDS = {OperationKind.DEPOSIT, OperationKind.WITHDRAW}


def _parse_date(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return datetime(1970, 1, 1)


def _parse_asset_type(s: str | None) -> AssetType:
    if not s:
        return AssetType.UNKNOWN
    try:
        return AssetType(s)
    except ValueError:
        return AssetType.UNKNOWN


def parse_operation(raw: dict, account_id: str | None = None) -> BaseOperation:
    """Превращает один raw-объект API в нормализованный."""
    op_type = raw.get("operationType", "")
    kind = KIND_MAP.get(op_type, OperationKind.UNKNOWN)

    # account_id: сначала из raw (если проставлен клиентом), потом аргумент
    acc_id = raw.get("_account_id") or account_id

    common = dict(
        id=raw.get("id", ""),
        date=_parse_date(raw.get("date", "1970-01-01T00:00:00Z")),
        kind=kind,
        raw_type=raw.get("type", ""),
        operation_type=op_type,
        state=raw.get("state", ""),
        payment=Money.from_api(raw.get("payment")),
        parent_id=raw.get("parentOperationId") or None,
        account_id=acc_id,
    )

    if kind in TRADE_KINDS:
        qty = Decimal(str(raw.get("quantity", 0) or 0))
        price = Money.from_api(raw.get("price"))
        return Trade(
            **common,
            figi=raw.get("figi", ""),
            instrument_uid=raw.get("instrumentUid", ""),
            instrument_type=_parse_asset_type(raw.get("instrumentType")),
            quantity=qty,
            price_per_unit=price,
            total=Money(price.amount * qty, price.currency),
        )

    if kind in INCOME_KINDS:
        return Income(
            **common,
            figi=raw.get("figi", ""),
            instrument_uid=raw.get("instrumentUid", ""),
            instrument_type=_parse_asset_type(raw.get("instrumentType")),
        )

    if kind in FEE_KINDS:
        return Fee(
            **common,
            figi=raw.get("figi", ""),
            instrument_uid=raw.get("instrumentUid", ""),
        )

    if kind in CASHFLOW_KINDS:
        return CashFlow(**common)

    return BaseOperation(**common)


def parse_operations(raw_list: list[dict], account_id: str | None = None) -> list[BaseOperation]:
    """Парсит список операций.

    ВАЖНО: childOperations НЕ раскрываем — они уже приходят отдельными
    операциями с parentOperationId (проверено: 194/194 BROKER_FEE имеют parent).
    """
    result: list[BaseOperation] = []

    for raw in raw_list:
        if raw.get("state") == "OPERATION_STATE_CANCELED":
            continue
        result.append(parse_operation(raw, account_id=account_id))

    return result