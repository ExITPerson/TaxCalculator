"""Рекомендации по ребалансировке портфеля."""
import logging
from pathlib import Path

from config.settings import ACCOUNTS_ID
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio

logger = logging.getLogger(__name__)


# Целевые доли (можно вынести в .env или config)
TARGET_ALLOCATION = {
    'Акции': 0.30,
    'Облигации': 0.60,
    'ETF': 0.10,
}

# Порог отклонения, после которого рекомендуем ребалансировку (%)
REBALANCE_THRESHOLD = 5.0


def build_rebalance_recommendations(account_id: str | None = None) -> dict:
    """
    Считает отклонения от целевых долей и даёт рекомендации.
    """
    accounts = [account_id] if account_id else ACCOUNTS_ID

    totals = {'Акции': 0.0, 'Облигации': 0.0, 'ETF': 0.0}

    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)
            totals['Акции'] += p.get('total_amount_shares', 0.0)
            totals['Облигации'] += p.get('total_amount_bonds', 0.0)
            totals['ETF'] += p.get('total_amount_etf', 0.0)

    total = sum(totals.values())
    if total == 0:
        return {'error': 'Портфель пуст'}

    current = {k: v / total for k, v in totals.items()}

    recommendations = []
    for asset, target_pct in TARGET_ALLOCATION.items():
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