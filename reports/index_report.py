"""Построение графика: TWR + стоимость портфеля + P&L."""
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from database.db import Session
from database.snapshot_crud import SnapshotCrud
from invest.candles_client import TInvestCandlesClient


IMOEX_FIGI = 'BBG00KDWPPW2'
RTSI_FIGI = 'BBG000NJ9048'
RGBI_FIGI = 'BBG000V0SJ39'
MCFTR_FIGI = 'BBG00G6B6TB1'


MARKET_INDICES = [
    {'figi': IMOEX_FIGI, 'name': 'IMOEX',  'color': '#F18F01', 'enabled': True},
    {'figi': RTSI_FIGI,  'name': 'RTSI',   'color': '#C73E1D', 'enabled': True},
    {'figi': RGBI_FIGI,  'name': 'RGBI',   'color': '#06A77D', 'enabled': True},
    {'figi': MCFTR_FIGI, 'name': 'MCFTR',  'color': '#6A4C93', 'enabled': True},
]


def _load_index_history(figi: str, date_from: date, date_to: date,
                        crud: SnapshotCrud) -> dict:
    cached = crud.get_cached_candles(figi, date_from, date_to)

    all_days = set()
    current = date_from
    while current <= date_to:
        all_days.add(current)
        current += timedelta(days=1)

    missing = all_days - set(cached.keys())
    if not missing:
        return cached

    fetch_from = min(missing)
    fetch_to = max(missing)

    with TInvestCandlesClient() as client:
        fetched = client.fetch_candles(
            figi,
            datetime.combine(fetch_from, datetime.min.time()),
            datetime.combine(fetch_to, datetime.min.time()),
        )

    if fetched:
        crud.save_candles(figi, fetched)

    result = dict(cached)
    result.update(fetched)
    return result


def _normalize_index(raw: dict, start_date: date) -> dict:
    if not raw:
        return {}

    base = None
    for d in sorted(raw.keys()):
        if d >= start_date:
            base = raw[d]
            break

    if base is None or base == 0:
        return {}

    return {d: (v / base) * 100 for d, v in raw.items() if d >= start_date}


def build_index_chart(output_path: str | None = None,
                      account_id: str = 'all',
                      title: str = 'Индекс полной доходности портфеля (TWR)',
                      include_market_indices: bool = True) -> str:
    """Строит график: TWR + стоимость + P&L."""
    if output_path is None:
        output_path = str(
            Path(__file__).resolve().parent.parent / 'data' / 'index_chart.png'
        )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Session() as session:
        crud = SnapshotCrud(session)
        snapshots = crud.get_snapshots(account_id)

        if not snapshots:
            raise ValueError("Нет snapshots. Сначала запусти backfill.")

        raw_dates = [s.date for s in snapshots]
        raw_index = [float(s.index_value) for s in snapshots]
        raw_total = [float(s.total_value) for s in snapshots]
        raw_pnl = [float(s.pnl_value or 0) for s in snapshots]

        # --- УМНЫЙ ФИЛЬТР ---
        # Если P&L упал более чем на 20 000 руб (или стоимость упала в 10 раз),
        # значит в этот день API не отдал цены, и снапшот битый.
        valid = []
        for d, iv, tv, pv in zip(raw_dates, raw_index, raw_total, raw_pnl):
            # Пропускаем дни с нулевым капиталом
            if iv <= 0 or tv <= 5000:
                continue

            # Пропускаем дни, где P&L рухнул в глубокий минус (явный сбой цен)
            if pv < -20000:
                print(f"[!] Пропущен битый снапшот {d}: P&L={pv}, total={tv}")
                continue

            valid.append((d, iv, tv, pv))

        if not valid:
            raise ValueError("Нет валидных snapshots (все отфильтрованы как битые)")

        # if not valid:
        #     raise ValueError("Нет валидных snapshots (все с капиталом < 5000)")

        if len(valid) < len(raw_dates):
            skipped = len(raw_dates) - len(valid)
            print(f"[!] Пропущено {skipped} snapshots с малым капиталом")

        dates = [x[0] for x in valid]
        index_values = [x[1] for x in valid]
        total_values = [x[2] for x in valid]
        pnl_values = [x[3] for x in valid]

        # Загружаем индексы
        normalized_indices: list[dict] = []
        if include_market_indices:
            start_date = dates[0].date()
            end_date = dates[-1].date()

            for idx in MARKET_INDICES:
                if not idx['enabled']:
                    continue

                raw = _load_index_history(idx['figi'], start_date, end_date, crud)
                norm = _normalize_index(raw, start_date)

                if norm:
                    normalized_indices.append({
                        'name': idx['name'],
                        'color': idx['color'],
                        'data': norm,
                    })

    # ---------- Фигура ----------
    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(14, 12),
        gridspec_kw={'height_ratios': [2, 1, 1]},
    )

    # ============ Верхний: TWR ============
    ax1.plot(dates, index_values, linewidth=2.4, color='#2E86AB',
             label='Портфель (TWR)', zorder=5)
    ax1.fill_between(dates, 100, index_values, alpha=0.10, color='#2E86AB')

    for idx in normalized_indices:
        data = idx['data']
        ax1.plot(list(data.keys()), list(data.values()),
                 linewidth=1.4, color=idx['color'],
                 label=idx['name'], alpha=0.85, zorder=3)

    ax1.axhline(y=100, color='gray', linestyle='--', linewidth=1, alpha=0.7)

    min_idx = index_values.index(min(index_values))
    max_idx = index_values.index(max(index_values))

    ax1.scatter([dates[min_idx]], [index_values[min_idx]],
                color='red', zorder=6, s=40)
    ax1.annotate(f'{index_values[min_idx]:.2f}',
                 (dates[min_idx], index_values[min_idx]),
                 textcoords="offset points", xytext=(0, -15),
                 ha='center', fontsize=9, color='red')

    ax1.scatter([dates[max_idx]], [index_values[max_idx]],
                color='green', zorder=6, s=40)
    ax1.annotate(f'{index_values[max_idx]:.2f}',
                 (dates[max_idx], index_values[max_idx]),
                 textcoords="offset points", xytext=(0, 8),
                 ha='center', fontsize=9, color='green')

    total_return = index_values[-1] - 100
    title_lines = [title, f'Портфель: {total_return:+.2f}%']

    for idx in normalized_indices:
        values = list(idx['data'].values())
        if not values:
            continue
        idx_return = values[-1] - 100
        title_lines.append(f"{idx['name']}: {idx_return:+.2f}%")

    ax1.set_title('\n'.join(title_lines), fontsize=12)
    ax1.set_ylabel('Индекс (старт = 100)')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left', fontsize=9, ncol=2)

    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')

    # ============ Средний: стоимость ============
    ax2.plot(dates, total_values, linewidth=1.5, color='#A23B72',
             label='Стоимость портфеля')
    ax2.fill_between(dates, 0, total_values, alpha=0.1, color='#A23B72')
    ax2.set_ylabel('Стоимость, ₽')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')

    # ============ Нижний: P&L ============
    if pnl_values:
        ax3.plot(dates, pnl_values, linewidth=1.5, color='#2A9D8F',
                 label='P&L (руб)')

        # Заливка: зелёная выше 0, красная ниже
        ax3.fill_between(dates, 0, pnl_values,
                         where=[v >= 0 for v in pnl_values],
                         alpha=0.20, color='#2A9D8F', interpolate=True)
        ax3.fill_between(dates, 0, pnl_values,
                         where=[v < 0 for v in pnl_values],
                         alpha=0.20, color='#C73E1D', interpolate=True)

        ax3.axhline(y=0, color='gray', linestyle='--',
                    linewidth=1, alpha=0.7)

        current_pnl = pnl_values[-1]
        color = '#2A9D8F' if current_pnl >= 0 else '#C73E1D'
        ax3.scatter([dates[-1]], [current_pnl], color=color, zorder=6, s=40)
        ax3.annotate(
            f'{current_pnl:+,.0f} ₽',
            (dates[-1], current_pnl),
            textcoords="offset points", xytext=(0, 10),
            ha='center', fontsize=10, color=color,
            fontweight='bold',
        )

        ax3.set_ylabel('P&L, ₽')
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc='upper left', fontsize=9)
        ax3.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f'{x:+,.0f}')
        )
        ax3.xaxis.set_major_locator(
            mdates.WeekdayLocator(byweekday=mdates.MO)
        )
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
        plt.setp(ax3.get_xticklabels(), rotation=45, ha='right')

    plt.tight_layout()
    plt.savefig(str(out_path), dpi=120, bbox_inches='tight')
    plt.close(fig)

    return str(out_path)