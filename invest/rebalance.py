# invest/rebalance.py
import logging
from config.settings import ACCOUNTS_ID
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
from database.db import Session
from database.crud import BotSettingsCrud
from database.instrument_crud import InstrumentCrud

logger = logging.getLogger(__name__)

REBALANCE_THRESHOLD = 5.0


def build_rebalance_recommendations(account_id: str | None = None) -> dict:
    """
    Считает отклонения от целевых долей и даёт рекомендации.
    Учитывает Акции, Облигации и Фонды (ETF).
    """
    accounts = [account_id] if account_id else ACCOUNTS_ID

    # Читаем цели из БД
    with Session() as s:
        target_allocation = BotSettingsCrud(s).get_target_allocation()
        # Достаем кэш инструментов, чтобы понять, что такое ETF/Фонд
        instr_crud = InstrumentCrud(s)
        all_instr = instr_crud.get_all()

    totals = {'Акции': 0.0, 'Облигации': 0.0, 'Фонды': 0.0}

    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)

            # Суммируем по типам из API (общая стоимость)
            totals['Акции'] += p.get('total_amount_shares', 0.0)
            totals['Облигации'] += p.get('total_amount_bonds', 0.0)
            totals['Фонды'] += p.get('total_amount_etf', 0.0)

            # Если API не разделяет ETF, пробуем найти их через позиции
            for pos in p['positions']:
                figi = pos['figi']
                val = pos['quantity'] * pos['current_price']
                if val <= 0:
                    continue
                # Смотрим в БД, что это за инструмент
                info = all_instr.get(figi)
                if info and info.instrument_type == 'etf':
                    # Если API уже посчитал это в total_amount_etf,
                    # то мы можем задвоить. Но для надежности лучше
                    # использовать логику API.
                    pass

    total = sum(totals.values())
    if total == 0:
        return {'error': 'Портфель пуст'}

    current = {k: v / total for k, v in totals.items()}

    recommendations = []
    for asset, target_pct in target_allocation.items():
        current_pct = current.get(asset, 0.0)
        deviation = (current_pct - target_pct) * 100

        target_value = total * target_pct
        current_value = totals.get(asset, 0.0)
        diff = target_value - current_value  # >0 — купить, <0 — продать

        recommendations.append({
            'asset': asset,
            'current_pct': round(current_pct * 100, 2),
            'target_pct': round(target_pct * 100, 2),
            'deviation_pct': round(deviation, 2),
            'current_value': round(current_value, 2),
            'target_value': round(target_value, 2),
            'diff_rub': round(diff, 2),
            'action': 'купить' if diff > 0 else 'продать' if diff < 0 else '—',
            'needs_rebalance': abs(deviation) >= REBALANCE_THRESHOLD,
        })

    return {
        'total': round(total, 2),
        'recommendations': recommendations,
        'needs_rebalance': any(r['needs_rebalance'] for r in recommendations),
    }