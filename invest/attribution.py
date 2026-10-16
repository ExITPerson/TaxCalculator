"""Атрибуция доходности: разложение на цены, купоны, комиссии.

ВАЖНО:
- Купоны и дивиденды — это ДОХОД.
- Погашения и амортизация — это ВОЗВРАТ ВЛОЖЕННОГО КАПИТАЛА, а не доход.
- Комиссии и налоги — это РАСХОДЫ.
"""
from datetime import date, datetime

from sqlalchemy import func

from database.db import Session, InvestOperationDB


def build_attribution(account_id: str | None = None,
                      date_from: date | None = None,
                      date_to: date | None = None) -> dict:
    """
    Разложение доходности портфеля на составляющие.

    ВАЖНО: использует TWR-индекс, а не total_value, потому что
    total_value включает пополнения/выводы, которые не являются доходностью.

    Погашения и амортизация НЕ включаются в доходность —
    это возврат вложенного капитала.
    """
    with Session() as s:
        from database.snapshot_crud import SnapshotCrud
        snapshots = SnapshotCrud(s).get_snapshots(account_id or 'all')

        if not snapshots:
            return {'error': 'Нет snapshots'}

        # Фильтруем по периоду
        if date_from:
            snapshots = [x for x in snapshots if x.date.date() >= date_from]
        if date_to:
            snapshots = [x for x in snapshots if x.date.date() <= date_to]

        if not snapshots:
            return {'error': 'Нет данных в периоде'}

        # Фильтруем битые snapshots (index = 0)
        valid = [
            x for x in snapshots
            if float(x.index_value) > 0 and float(x.total_value) > 0
        ]

        if len(valid) < 2:
            return {'error': 'Мало валидных snapshots'}

        # Стоимость на старте и конце
        start_value = float(valid[0].total_value)
        end_value = float(valid[-1].total_value)

        # TWR-индекс
        start_index = float(valid[0].index_value)
        end_index = float(valid[-1].index_value)
        total_return_pct = end_index - start_index

        # Общая доходность в рублях от начального капитала
        total_return_rub = start_value * (total_return_pct / 100)

        # Собираем компоненты из операций
        q = s.query(
            InvestOperationDB.kind,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        ).filter(
            InvestOperationDB.kind.in_([
                'coupon', 'dividend',
                'bond_repayment', 'amortization',
                'fee', 'margin_fee', 'tax',
            ]),
        )
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        if date_from:
            q = q.filter(
                InvestOperationDB.date >= datetime.combine(date_from, datetime.min.time())
            )
        if date_to:
            q = q.filter(
                InvestOperationDB.date <= datetime.combine(date_to, datetime.max.time())
            )

        rows = q.group_by(InvestOperationDB.kind).all()
        by_kind = {kind: float(total or 0) for kind, total in rows}

        # --- ДОХОД ---
        # Только купоны и дивиденды. Погашения/амортизация — НЕ доход.
        coupons = by_kind.get('coupon', 0)
        dividends = by_kind.get('dividend', 0)

        # --- ВОЗВРАТ КАПИТАЛА (не доход) ---
        repayment = by_kind.get('bond_repayment', 0)
        amortization = by_kind.get('amortization', 0)
        capital_return = repayment + amortization

        # --- РАСХОДЫ ---
        commissions = abs(by_kind.get('fee', 0) + by_kind.get('margin_fee', 0))
        taxes = abs(by_kind.get('tax', 0))

        income_total = coupons + dividends
        expenses_total = commissions + taxes

        # Изменение цен = общая доходность − купоны − дивиденды + комиссии + налоги
        price_change_rub = total_return_rub - income_total + expenses_total

        # Проценты от начального капитала
        if start_value > 0:
            price_change_pct = price_change_rub / start_value * 100
            coupons_pct = coupons / start_value * 100
            dividends_pct = dividends / start_value * 100
            capital_return_pct = capital_return / start_value * 100
            commissions_pct = -commissions / start_value * 100
            taxes_pct = -taxes / start_value * 100
        else:
            price_change_pct = coupons_pct = dividends_pct = 0.0
            capital_return_pct = commissions_pct = taxes_pct = 0.0

        return {
            'total_return_pct': round(total_return_pct, 2),
            'total_return_rub': round(total_return_rub, 2),
            'start_value': start_value,
            'end_value': end_value,
            'components': {
                'price_change': {
                    'pct': round(price_change_pct, 2),
                    'rub': round(price_change_rub, 2),
                    'label': 'Изменение цен',
                },
                'coupons': {
                    'pct': round(coupons_pct, 2),
                    'rub': round(coupons, 2),
                    'label': 'Купоны',
                },
                'dividends': {
                    'pct': round(dividends_pct, 2),
                    'rub': round(dividends, 2),
                    'label': 'Дивиденды',
                },
                'commissions': {
                    'pct': round(commissions_pct, 2),
                    'rub': round(-commissions, 2),
                    'label': 'Комиссии',
                },
                'taxes': {
                    'pct': round(taxes_pct, 2),
                    'rub': round(-taxes, 2),
                    'label': 'Налоги',
                },
            },
            # Возврат капитала — отдельно, НЕ в компонентах доходности
            'capital_return': {
                'pct': round(capital_return_pct, 2),
                'rub': round(capital_return, 2),
                'label': 'Возврат капитала (не доход)',
            },
        }