"""График rolling Sharpe и волатильности портфеля."""
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from database.db import Session
from database.snapshot_crud import SnapshotCrud
from invest.candles_client import TInvestCandlesClient
from invest.rolling_metrics import (
    build_rolling_sharpe_report, rolling_sharpe,
)


DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
DATA_DIR.mkdir(exist_ok=True)


# FIGI индексов для сравнения
IMOEX_FIGI = 'BBG00KDWPPW2'
RTSI_FIGI = 'BBG000NJ9048'
RGBI_FIGI = 'BBG000V0SJ39'
MCFTR_FIGI = 'BBG00G6B6TB1'


# ============================================================
# Загрузка и нормализация индексов
# ============================================================

def _load_index_prices(figi: str, date_from: date, date_to: date,
                        crud: SnapshotCrud) -> list[tuple]:
    """Загружает цены индекса и возвращает [(date, close), ...]."""
    cached = crud.get_cached_candles(figi, date_from, date_to)

    all_days = set()
    current = date_from
    while current <= date_to:
        all_days.add(current)
        current += timedelta(days=1)

    missing = all_days - set(cached.keys())
    if missing:
        with TInvestCandlesClient() as client:
            fetched = client.fetch_candles(
                figi,
                datetime.combine(min(missing), datetime.min.time()),
                datetime.combine(max(missing), datetime.min.time()),
            )
        if fetched:
            crud.save_candles(figi, fetched)
            cached.update(fetched)

    return sorted(cached.items())


def _normalize_prices(prices: list[tuple], start_date: date) -> list[float]:
    """Нормализует цены к базе 100 на start_date."""
    base = None
    for d, p in prices:
        if d >= start_date:
            base = p
            break

    if base is None or base == 0:
        return []

    return [(p / base) * 100 for d, p in prices if d >= start_date]


# ============================================================
# Основная функция
# ============================================================

def build_rolling_sharpe_chart(output_path: str | None = None,
                                account_id: str = 'all',
                                compare_with_imoex: bool = True) -> str:
    """
    Двухпанельный график:
      - верх: rolling Sharpe портфеля (+ IMOEX, если включено)
      - низ: rolling волатильность портфеля
    """
    if output_path is None:
        output_path = str(DATA_DIR / 'rolling_sharpe.png')

    report = build_rolling_sharpe_report(account_id, windows=(30, 90))
    if 'error' in report:
        raise ValueError(report['error'])

    dates = report['dates']
    current = report['current']

    # Загружаем IMOEX для сравнения
    imoex_sharpe = None
    imoex_dates = None

    if compare_with_imoex:
        with Session() as session:
            crud = SnapshotCrud(session)
            start_date = dates[0]
            end_date = dates[-1]

            prices = _load_index_prices(IMOEX_FIGI, start_date, end_date, crud)
            if prices:
                norm_prices = _normalize_prices(prices, start_date)
                norm_dates = [d for d, p in prices if d >= start_date]

                if len(norm_prices) >= 31:
                    imoex_sharpe = rolling_sharpe(norm_prices, window=30)
                    imoex_dates = norm_dates

    # ---------- Фигура ----------
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 8),
        gridspec_kw={'height_ratios': [2, 1]},
    )

    # ============ Верхний график: rolling Sharpe ============

    # Sharpe портфеля 30 дней
    sharpe_30 = report['windows'][30]['sharpe']
    mask_30 = [v is not None for v in sharpe_30]
    if any(mask_30):
        d30 = [d for d, m in zip(dates, mask_30) if m]
        v30 = [v for v, m in zip(sharpe_30, mask_30) if m]
        ax1.plot(d30, v30, linewidth=2.0, color='#2E86AB',
                 label='Портфель (30 дней)', zorder=3)

    # Sharpe портфеля 90 дней
    sharpe_90 = report['windows'][90]['sharpe']
    mask_90 = [v is not None for v in sharpe_90]
    if any(mask_90):
        d90 = [d for d, m in zip(dates, mask_90) if m]
        v90 = [v for v, m in zip(sharpe_90, mask_90) if m]
        ax1.plot(d90, v90, linewidth=2.0, color='#A23B72',
                 label='Портфель (90 дней)', zorder=3)

    # IMOEX для сравнения
    if imoex_sharpe and imoex_dates:
        mask_i = [v is not None for v in imoex_sharpe]
        if any(mask_i):
            di = [d for d, m in zip(imoex_dates, mask_i) if m]
            vi = [v for v, m in zip(imoex_sharpe, mask_i) if m]
            ax1.plot(di, vi, linewidth=1.5, color='#F18F01',
                     label='IMOEX (30 дней)', alpha=0.8, linestyle='--')

    # Опорные линии
    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.7)
    ax1.axhline(y=0.5, color='green', linestyle=':', linewidth=1, alpha=0.5,
                label='Sharpe = 0.5')
    ax1.axhline(y=-0.5, color='red', linestyle=':', linewidth=1, alpha=0.5)

    # Заголовок
    rfr_pct = report['risk_free_rate'] * 100
    title_lines = [
        'Скользящий Sharpe ratio портфеля',
        f'(безрисковая ставка: {rfr_pct:.1f}%)',
    ]
    for w in (30, 90):
        c = current[w]
        if c['has_enough_data']:
            emoji = '🟢' if c['sharpe'] > 0.5 else ('🟡' if c['sharpe'] > 0 else '🔴')
            title_lines.append(f"{w} дней: {c['sharpe']:+.2f} {emoji}")
        else:
            title_lines.append(f"{w} дней: мало данных")

    ax1.set_title('\n'.join(title_lines), fontsize=11)
    ax1.set_ylabel('Sharpe ratio')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='lower right', fontsize=8)

    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')

    # ============ Нижний график: волатильность ============

    vol_30 = report['windows'][30]['volatility']
    mask_v = [v is not None for v in vol_30]
    if any(mask_v):
        dv = [d for d, m in zip(dates, mask_v) if m]
        vv = [v for v, m in zip(vol_30, mask_v) if m]
        ax2.plot(dv, vv, linewidth=1.8, color='#A23B72',
                 label='Волатильность (30 дней)')
        ax2.fill_between(dv, 0, vv, alpha=0.15, color='#A23B72')

    ax2.set_ylabel('Волатильность, % годовых')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v:.1f}%'))

    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')

    plt.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)

    return output_path