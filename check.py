# debug_28.py
from datetime import date, timedelta
from database.db import Session, InvestOperationDB
from database.snapshot_crud import SnapshotCrud
from invest.index_builder import (
    build_positions_timeline, build_daily_flows, build_daily_cash,
    load_candles_for_figis, compute_price_factors, build_daily_values,
    load_accrued_interests
)
from invest.start_state import compute_start_state
from config.settings import ACCOUNTS_ID

target = date(2026, 10, 28)
prev = target - timedelta(days=1)

# 1. Смотрим start_state на 27.10
start_positions, start_cash = compute_start_state(prev, ACCOUNTS_ID)
print(f"Start state на {prev}:")
print(f"  Позиций: {len(start_positions)}")
print(f"  Кэш: {start_cash:,.2f}")

# 2. Строим timeline, flows, cash
with Session() as s:
    crud = SnapshotCrud(s)
    timeline = build_positions_timeline(s, target, target, start_positions=start_positions)
    flows = build_daily_flows(s, target, target)
    daily_cash = build_daily_cash(s, target, target, start_cash=start_cash)

    print(f"\nFlows за {target}: {flows}")
    print(f"Daily cash: {daily_cash}")

    # 3. Загружаем свечи
    figis = list(timeline.keys())
    candles = load_candles_for_figis(crud, figis, target, target)

    # 4. Смотрим, есть ли свечи за 28.10
    missing_candles = [f for f in figis if target not in candles.get(f, {})]
    print(f"\nБумаг без свечи за {target}: {len(missing_candles)}")

    # 5. Считаем paper_values
    price_factors = compute_price_factors(s, timeline, candles)
    nkd_data = load_accrued_interests(s, figis, target, target)
    paper_values, total_values, positions_count = build_daily_values(
        timeline, candles, daily_cash, price_factors, target, target, nkd_data=nkd_data
    )

    print(f"\nPaper values: {paper_values}")
    print(f"Total values: {total_values}")
    print(f"Positions count: {positions_count}")