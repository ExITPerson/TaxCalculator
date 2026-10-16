"""Визуализации по портфелю: структура и доходы."""
import logging
from collections import defaultdict
from pathlib import Path

import matplotlib
from sqlalchemy import func

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from config.settings import ACCOUNTS_ID
from database.db import Session, InvestOperationDB
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
DATA_DIR.mkdir(exist_ok=True)


ASSET_COLORS = {
    'Акции': '#2E86AB',
    'Облигации': '#A23B72',
    'ETF': '#F18F01',
    'Валюты': '#06A77D',
    'Плечо': '#C73E1D',
    'Прочее': '#6A4C93',
}

INCOME_LABELS = {
    'coupon': 'Купоны',
    'dividend': 'Дивиденды',
    'bond_repayment': 'Погашение облигаций',
    'amortization': 'Амортизация',
}

INCOME_COLORS = {
    'Купоны': '#2E86AB',
    'Дивиденды': '#F18F01',
    'Погашение облигаций': '#06A77D',
    'Амортизация': '#6A4C93',
}


# ============================================================
# 1. Структура портфеля (pie)
# ============================================================

def build_portfolio_pie_chart(output_path: str | None = None,
                              account_id: str | None = None) -> str:
    """
    Круговая диаграмма структуры портфеля.

    Категории:
      - Акции
      - Облигации
      - ETF
      - Валюты (если положительный остаток)
    """
    if output_path is None:
        output_path = str(DATA_DIR / 'portfolio_pie.png')

    totals = {
        'Акции': 0.0,
        'Облигации': 0.0,
        'ETF': 0.0,
        'Валюты': 0.0,
    }
    accounts = [account_id] if account_id else ACCOUNTS_ID

    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)

            totals['Акции'] += p.get('total_amount_shares', 0.0)
            totals['Облигации'] += p.get('total_amount_bonds', 0.0)
            totals['ETF'] += p.get('total_amount_etf', 0.0)
            totals['Валюты'] += max(0.0, p.get('total_amount_currencies', 0.0))

    # Оставляем только ненулевые категории
    data = {k: v for k, v in totals.items() if v > 0}

    if not data:
        raise ValueError("Портфель пуст")

    labels = list(data.keys())
    values = list(data.values())
    colors = [ASSET_COLORS.get(lbl, '#999') for lbl in labels]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(10, 8))

    wedges, _, _ = ax.pie(
        values, labels=None,
        autopct=lambda pct: f'{pct:.1f}%',
        startangle=90, colors=colors, pctdistance=0.75,
        wedgeprops={'edgecolor': 'white', 'linewidth': 2},
    )

    legend_labels = [
        f'{lbl}: {val:,.0f} ₽ ({val / total * 100:.1f}%)'
        for lbl, val in zip(labels, values)
    ]
    ax.legend(wedges, legend_labels, loc='center left',
              bbox_to_anchor=(1.0, 0.5), fontsize=10)

    ax.set_title(f'Структура портфеля\nВсего: {total:,.2f} ₽',
                 fontsize=14, pad=20)

    centre_circle = plt.Circle((0, 0), 0.5, fc='white')
    fig.gca().add_artist(centre_circle)
    ax.text(0, 0, f'{total:,.0f}\n₽', ha='center', va='center',
            fontsize=14, fontweight='bold')

    ax.axis('equal')
    plt.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)

    return output_path


# ============================================================
# 2. Динамика купонов и дивидендов (bar)
# ============================================================

def _get_monthly_income(session, account_id: str | None = None) -> dict:
    from database.db import month_expr

    month = month_expr(InvestOperationDB.date)

    q = (
        session.query(
            month.label('month'),
            InvestOperationDB.kind,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(InvestOperationDB.kind.in_(
            ['coupon', 'dividend', 'bond_repayment', 'amortization']
        ))
    )
    if account_id:
        q = q.filter(InvestOperationDB.account_id == account_id)

    rows = (
        q.group_by(month, InvestOperationDB.kind)
        .order_by(month)
        .all()
    )

    result: dict = defaultdict(lambda: defaultdict(float))
    for month_val, kind, total in rows:
        if not month_val:
            continue
        result[month_val][kind] = float(total or 0)
    return result


def build_income_chart(output_path: str | None = None,
                       account_id: str | None = None) -> str:
    if output_path is None:
        output_path = str(DATA_DIR / 'income_chart.png')

    with Session() as session:
        monthly = _get_monthly_income(session, account_id)

    if not monthly:
        raise ValueError("Нет данных о купонах/дивидендах")

    months = sorted(monthly.keys())
    kinds = ['coupon', 'dividend', 'bond_repayment', 'amortization']

    series = {kind: [] for kind in kinds}
    for month in months:
        for kind in kinds:
            series[kind].append(monthly[month].get(kind, 0.0))

    totals = [sum(series[kind][i] for kind in kinds) for i in range(len(months))]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(months))
    width = 0.6
    bottom = [0.0] * len(months)

    for kind in kinds:
        values = series[kind]
        if not any(values):
            continue
        label = INCOME_LABELS[kind]
        ax.bar(x, values, width, bottom=bottom,
               label=label, color=INCOME_COLORS[label])
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.plot(x, totals, marker='o', color='#222', linewidth=1.5,
            label='Итого', zorder=5)

    for i, total in enumerate(totals):
        if total > 0:
            ax.text(i, total * 1.02, f'{total:,.0f}',
                    ha='center', fontsize=9, fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(months, rotation=45, ha='right')
    ax.set_ylabel('Сумма, ₽')
    ax.set_title('Динамика купонов, дивидендов и погашений по месяцам')
    ax.grid(True, alpha=0.3, axis='y')
    ax.legend(loc='upper left')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v:,.0f}'))

    plt.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)

    return output_path

# ============================================================
# 3. Атрибуция доходности (pie)
# ============================================================

def build_attribution_pie_chart(output_path: str | None = None,
                                account_id: str | None = None) -> str:
    """
    Круговая диаграмма атрибуции доходности:
    из чего сложилась итоговая доходность.
    """
    from invest.attribution import build_attribution

    if output_path is None:
        output_path = str(DATA_DIR / 'attribution_pie.png')

    data = build_attribution(account_id=account_id)
    if 'error' in data:
        raise ValueError(data['error'])

    components = data['components']

    # Только ненулевые компоненты
    labels = []
    values = []
    colors = []

    color_map = {
        'price_change': '#2E86AB',
        'coupons': '#06A77D',
        'dividends': '#F18F01',
        'bond_repayment': '#A23B72',
        'commissions': '#C73E1D',
        'taxes': '#6A4C93',
    }

    label_map = {
        'price_change': 'Изменение цен',
        'coupons': 'Купоны',
        'dividends': 'Дивиденды',
        'bond_repayment': 'Погашения',
        'commissions': 'Комиссии',
        'taxes': 'Налоги',
    }

    for key in ['price_change', 'coupons', 'dividends',
                'bond_repayment', 'commissions', 'taxes']:
        pct = components[key]['pct']
        if abs(pct) < 0.01:
            continue
        labels.append(label_map[key])
        values.append(abs(pct))
        colors.append(color_map[key])

    if not labels:
        raise ValueError("Все компоненты нулевые")

    fig, ax = plt.subplots(figsize=(10, 8))

    wedges, _, autotexts = ax.pie(
        values, labels=None,
        autopct=lambda pct: f'{pct:.1f}%',
        startangle=90, colors=colors, pctdistance=0.75,
        wedgeprops={'edgecolor': 'white', 'linewidth': 2},
    )

    # Подписи с рублями
    legend_labels = [
        f'{label_map[key]}: {components[key]["rub"]:+,.0f} ₽ '
        f'({components[key]["pct"]:+.2f}%)'
        for key in ['price_change', 'coupons', 'dividends',
                    'bond_repayment', 'commissions', 'taxes']
        if abs(components[key]['pct']) >= 0.01
    ]

    ax.legend(wedges, legend_labels, loc='center left',
              bbox_to_anchor=(1.0, 0.5), fontsize=10)

    total_return = data['total_return_pct']
    ax.set_title(
        f'Атрибуция доходности портфеля\n'
        f'Итоговая доходность: {total_return:+.2f}%',
        fontsize=13, pad=20,
    )

    # Круг в центре
    centre_circle = plt.Circle((0, 0), 0.5, fc='white')
    fig.gca().add_artist(centre_circle)
    ax.text(0, 0, f'{total_return:+.2f}%',
            ha='center', va='center',
            fontsize=16, fontweight='bold')

    ax.axis('equal')
    plt.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)

    return output_path


# ============================================================
# 4. Распределение по секторам (pie)
# ============================================================

def build_sectors_pie_chart(output_path: str | None = None,
                            account_id: str | None = None) -> str:
    """
    Круговая диаграмма распределения портфеля по секторам.
    """
    from invest.sectors import build_sectors_distribution

    if output_path is None:
        output_path = str(DATA_DIR / 'sectors_pie.png')

    data = build_sectors_distribution(account_id=account_id)
    if 'error' in data:
        raise ValueError(data['error'])

    sectors = data['sectors']
    if not sectors:
        raise ValueError("Нет данных по секторам")

    labels = list(sectors.keys())
    values = [s['value'] for s in sectors.values()]
    total = data['total']

    # Цвета по секторам
    color_map = {
        'Финансы': '#2E86AB',
        'Энергетика': '#F18F01',
        'IT': '#06A77D',
        'Потребительские товары': '#A23B72',
        'Сырьё': '#6A4C93',
        'Промышленность': '#C73E1D',
        'Телеком': '#4CAF50',
        'Здравоохранение': '#FF6B6B',
        'Недвижимость': '#9C27B0',
        'Коммунальные': '#607D8B',
        'Прочее': '#999999',
    }

    colors = [color_map.get(lbl, '#999999') for lbl in labels]

    fig, ax = plt.subplots(figsize=(12, 8))

    wedges, _, autotexts = ax.pie(
        values, labels=None,
        autopct=lambda pct: f'{pct:.1f}%' if pct > 3 else '',
        startangle=90, colors=colors, pctdistance=0.75,
        wedgeprops={'edgecolor': 'white', 'linewidth': 2},
    )

    legend_labels = [
        f'{lbl}: {val:,.0f} ₽ ({val / total * 100:.1f}%) — {sectors[lbl]["count"]} шт'
        for lbl, val in zip(labels, values)
    ]

    ax.legend(wedges, legend_labels, loc='center left',
              bbox_to_anchor=(1.0, 0.5), fontsize=10)

    ax.set_title(
        f'Распределение портфеля по секторам\nВсего: {total:,.2f} ₽',
        fontsize=14, pad=20,
    )

    centre_circle = plt.Circle((0, 0), 0.5, fc='white')
    fig.gca().add_artist(centre_circle)
    ax.text(0, 0, f'{len(labels)}\nсекторов',
            ha='center', va='center',
            fontsize=14, fontweight='bold')

    ax.axis('equal')
    plt.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)

    return output_path