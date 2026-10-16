"""Симуляция: что будет с портфелем при разных сценариях."""
from datetime import date, timedelta

from database.db import Session
from database.snapshot_crud import SnapshotCrud
from config.settings import ACCOUNTS_ID
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio


def build_simulation(account_id: str | None = None) -> dict:
    """
    Сценарии на год вперёд:
      - без реинвестирования
      - с реинвестированием купонов
      - при падении рынка на 10%
      - при росте рынка на 10%
    """
    # 1. Текущая стоимость
    accounts = [account_id] if account_id else ACCOUNTS_ID
    total = 0.0
    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)
            total += p['total_amount_portfolio']

    if total == 0:
        return {'error': 'Портфель пуст'}

    # 2. Годовая доходность (из снапшотов)
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots(account_id or 'all')

    # Фильтруем битые snapshots
    valid = [
        s for s in snapshots
        if float(s.index_value) > 0 and float(s.total_value) > 0
    ]

    if len(valid) < 2:
        annual_return = 0.10
    else:
        days = (valid[-1].date - valid[0].date).days or 1
        total_ret = float(valid[-1].index_value) / float(valid[0].index_value) - 1
        annual_return = (1 + total_ret) ** (365 / days) - 1

    # 3. Купоны и дивиденды за период → годовые
    from sqlalchemy import func
    from database.db import InvestOperationDB

    with Session() as s:
        q = s.query(
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0)
        ).filter(
            InvestOperationDB.kind.in_(['coupon', 'dividend'])
        )
        if account_id:
            q = q.filter(InvestOperationDB.account_id == account_id)
        income_total = float(q.scalar() or 0)

        # За какой период?
        if len(snapshots) >= 2:
            days = max(1, (snapshots[-1].date - snapshots[0].date).days)
            income_annual = income_total * 365 / days
        else:
            income_annual = 0

    # 4. Сценарии
    # A. Без реинвестирования
    end_no_reinvest = total * (1 + annual_return)

    # B. С реинвестированием купонов
    end_reinvest = total * (1 + annual_return) + income_annual * (1 + annual_return / 2)

    # C. Падение рынка на 10%
    # Предполагаем: 30% портфеля в акциях → упадут на 10%
    share_of_equity = 0.30
    drop_pct = 0.10 * share_of_equity  # = 3%
    end_drop = total * (1 - drop_pct)

    # D. Рост рынка на 10%
    end_growth = total * (1 + 0.10 * share_of_equity)

    return {
        'current_value': round(total, 2),
        'annual_return_pct': round(annual_return * 100, 2),
        'annual_income_rub': round(income_annual, 2),
        'scenarios': {
            'no_reinvest': {
                'label': 'Без реинвестирования',
                'value': round(end_no_reinvest, 2),
                'diff_pct': round((end_no_reinvest / total - 1) * 100, 2),
            },
            'reinvest': {
                'label': 'С реинвестированием купонов',
                'value': round(end_reinvest, 2),
                'diff_pct': round((end_reinvest / total - 1) * 100, 2),
            },
            'market_drop': {
                'label': 'Падение рынка на 10%',
                'value': round(end_drop, 2),
                'diff_pct': round((end_drop / total - 1) * 100, 2),
            },
            'market_growth': {
                'label': 'Рост рынка на 10%',
                'value': round(end_growth, 2),
                'diff_pct': round((end_growth / total - 1) * 100, 2),
            },
        },
    }