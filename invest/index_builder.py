"""Построение snapshots: TWR-индекс + P&L.

Логика:
- paper_value = Σ qty × (price + НКД)
- total_value = paper_value + cash_value
- TWR-индекс = дневные доходности (с защитой от малого капитала)
- P&L = total_value − net_invested
  где net_invested = накопленные внешние потоки (deposit − withdraw)
  (внутренние переводы исключаются)
"""
import logging
from datetime import date, datetime, timedelta

from database.db import InvestOperationDB
from database.snapshot_crud import SnapshotCrud
from database.accrued_interest_crud import AccruedInterestCrud
from invest.candles_client import TInvestCandlesClient
from invest.accrued_interest_client import TInvestAccruedInterestClient

logger = logging.getLogger(__name__)


# ============================================================
# 1. Позиции по дням
# ============================================================

def build_positions_timeline(session, date_from: date, date_to: date,
                             start_positions: dict | None = None) -> dict:
    """{figi: {date: quantity}}, начиная с start_positions."""
    start_positions = start_positions or {}

    trades = (
        session.query(InvestOperationDB)
        .filter(
            InvestOperationDB.kind.in_(['buy', 'sell']),
            InvestOperationDB.figi.isnot(None),
            InvestOperationDB.date >= datetime.combine(date_from, datetime.min.time()),
            InvestOperationDB.date <= datetime.combine(date_to, datetime.max.time()),
        )
        .order_by(InvestOperationDB.date)
        .all()
    )

    deltas: dict[str, dict[date, float]] = {}
    for t in trades:
        day = t.date.date()
        qty = float(t.quantity or 0)
        delta = qty if t.kind == 'buy' else -qty
        deltas.setdefault(t.figi, {})
        deltas[t.figi][day] = deltas[t.figi].get(day, 0) + delta

    all_figis = set(deltas.keys()) | set(start_positions.keys())

    timeline: dict[str, dict[date, float]] = {}
    for figi in all_figis:
        pos = float(start_positions.get(figi, 0.0))
        day_deltas = deltas.get(figi, {})

        result = {}
        current = date_from
        while current <= date_to:
            pos += day_deltas.get(current, 0)
            result[current] = pos
            current += timedelta(days=1)
        timeline[figi] = result

    return timeline


# ============================================================
# 2. Внешние потоки (deposit/withdraw без внутренних переводов)
# ============================================================

def build_daily_flows(session, date_from: date, date_to: date) -> dict:
    from sqlalchemy import func, or_
    from database.db import day_expr

    day = day_expr(InvestOperationDB.date)

    rows = (
        session.query(
            day.label('day'),
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['deposit', 'withdraw']),
            InvestOperationDB.date >= datetime.combine(date_from, datetime.min.time()),
            InvestOperationDB.date <= datetime.combine(date_to, datetime.max.time()),
            or_(
                InvestOperationDB.parent_id.is_(None),
                InvestOperationDB.parent_id == '',
            ),
        )
        .group_by(day)
        .all()
    )

    flows: dict[date, float] = {}
    for day_val, total in rows:
        if not day_val:
            continue
        # day_val может быть date (SQLite) или datetime (PG)
        d = day_val.date() if hasattr(day_val, 'date') else day_val
        if not isinstance(d, date):
            d = datetime.fromisoformat(str(day_val)).date()
        flows[d] = float(total or 0)

    return flows


# ============================================================
# 3. Кэш по дням
# ============================================================

def build_daily_cash(session, date_from: date, date_to: date,
                     start_cash: float = 0.0) -> dict:
    from sqlalchemy import func
    from database.db import day_expr

    day = day_expr(InvestOperationDB.date)

    rows = (
        session.query(
            day.label('day'),
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.date >= datetime.combine(date_from, datetime.min.time()),
            InvestOperationDB.date <= datetime.combine(date_to, datetime.max.time()),
        )
        .group_by(day)
        .all()
    )

    daily_delta: dict[date, float] = {}
    for day_val, total in rows:
        if not day_val:
            continue
        d = day_val.date() if hasattr(day_val, 'date') else day_val
        if not isinstance(d, date):
            d = datetime.fromisoformat(str(day_val)).date()
        daily_delta[d] = float(total or 0)

    cash: dict[date, float] = {}
    current_cash = start_cash
    current = date_from
    while current <= date_to:
        current_cash += daily_delta.get(current, 0.0)
        cash[current] = round(current_cash, 2)
        current += timedelta(days=1)

    return cash


# ============================================================
# 4. Свечи с кэшем
# ============================================================

def load_candles_for_figis(snapshot_crud, figis, date_from: date, date_to: date) -> dict:
    result = {}

    with TInvestCandlesClient() as client:
        for figi in figis:
            cached = snapshot_crud.get_cached_candles(figi, date_from, date_to)

            all_days = set()
            current = date_from
            while current <= date_to:
                all_days.add(current)
                current += timedelta(days=1)

            missing = all_days - set(cached.keys())

            if missing:
                fetched = client.fetch_candles(
                    figi,
                    datetime.combine(min(missing), datetime.min.time()),
                    datetime.combine(max(missing), datetime.min.time()),
                )
                if fetched:
                    snapshot_crud.save_candles(figi, fetched)
                    cached.update(fetched)

            result[figi] = cached

    return result


# ============================================================
# 5. Коэффициенты коррекции цен
# ============================================================

def compute_price_factors(session, timeline, candles):
    """
    factor = price_per_unit из первой сделки / цена первой свечи.
    Фиксирует factor на исторических данных.
    """
    factors = {}
    for figi in timeline:
        figi_candles = candles.get(figi, {})
        if not figi_candles:
            factors[figi] = 1.0
            continue

        first_trade = (
            session.query(InvestOperationDB)
            .filter(
                InvestOperationDB.figi == figi,
                InvestOperationDB.kind.in_(['buy', 'sell']),
                InvestOperationDB.price_per_unit.isnot(None),
                InvestOperationDB.price_per_unit > 0,
            )
            .order_by(InvestOperationDB.date)
            .first()
        )

        if not first_trade:
            factors[figi] = 1.0
            continue

        first_date = min(figi_candles.keys())
        first_candle_price = figi_candles[first_date]

        if first_candle_price > 0:
            factors[figi] = float(first_trade.price_per_unit) / first_candle_price
        else:
            factors[figi] = 1.0

    return factors


# ============================================================
# 6. Последняя цена
# ============================================================

def _last_known_price(prices: dict, target: date) -> float | None:
    for d in sorted(prices.keys(), reverse=True):
        if d <= target:
            return prices[d]
    return None


# ============================================================
# 7. НКД: загрузка + получение по дате
# ============================================================

def load_accrued_interests(
    session,
    figis: list[str],
    date_from: date,
    date_to: date,
    delay: float = 0.1,
) -> dict[str, dict[date, float]]:
    """Загружает НКД по FIGI с кэшированием. Возвращает {figi: {date: nkd}}."""
    from database.instrument_crud import InstrumentCrud

    crud = AccruedInterestCrud(session)
    instr_crud = InstrumentCrud(session)
    result: dict[str, dict[date, float]] = {}

    with TInvestAccruedInterestClient() as client:
        for figi in figis:
            info = instr_crud.get(figi)
            if not info or not info.instrument_uid:
                result[figi] = {}
                continue

            uid = info.instrument_uid
            cached = crud.get_range(figi, date_from, date_to)
            missing = crud.missing_dates(figi, date_from, date_to)

            if missing:
                logger.info("НКД %s (UID=%s): загружаем %d дней...",
                            figi, uid[:20], len(missing))
                fetched = client.fetch_accrued_interests(
                    uid, min(missing), max(missing),
                )
                if fetched:
                    crud.save_batch(figi, fetched)
                    cached.update(fetched)
                import time
                time.sleep(delay)

            result[figi] = cached

    return result


def get_nkd_on_date(nkd_map: dict[date, float], target: date) -> float | None:
    """НКД на дату (или ближайшую предшествующую)."""
    if target in nkd_map:
        return nkd_map[target]
    for d in sorted(nkd_map.keys(), reverse=True):
        if d <= target:
            return nkd_map[d]
    return None


# ============================================================
# 8. Значения по дням
# ============================================================

def build_daily_values(timeline, candles, daily_cash, price_factors,
                       date_from: date, date_to: date,
                       nkd_data: dict | None = None):
    paper_values: dict[date, float] = {}
    total_values: dict[date, float] = {}
    positions_count: dict[date, int] = {}

    last_valid_paper = 0.0

    current = date_from
    while current <= date_to:
        paper = 0.0
        count = 0

        for figi, positions_by_day in timeline.items():
            qty = positions_by_day.get(current, 0)
            if qty == 0:
                continue

            price = candles.get(figi, {}).get(current)
            if price is None:
                price = _last_known_price(candles.get(figi, {}), current)
            if price is None:
                continue

            factor = price_factors.get(figi, 1.0)
            adjusted_price = price * factor

            nkd_per_unit = 0.0
            if nkd_data and figi in nkd_data:
                nkd_per_unit = get_nkd_on_date(nkd_data[figi], current) or 0.0

            paper += qty * (adjusted_price + nkd_per_unit)
            count += 1

        cash = daily_cash.get(current, 0.0)

        # FIX: если в текущий день нет ни одной цены (count=0), но позиции есть,
        # берём предыдущее значение paper.
        if count == 0 and current != date_from:
            paper = last_valid_paper
            count = positions_count.get(
                max([d for d in positions_count if d < current], default=current),
                0,
            )

        if count > 0:
            last_valid_paper = paper

        paper_values[current] = round(paper, 2)
        total_values[current] = round(paper + cash, 2)
        positions_count[current] = count

        current += timedelta(days=1)

    return paper_values, total_values, positions_count


# ============================================================
# 9. TWR-индекс
# ============================================================

def calculate_twr_index(total_values: dict, flows: dict, start_date: date,
                        start_index: float = 100.0,
                        min_capital: float = 5000.0,
                        max_daily_return: float = 0.20) -> dict:
    """TWR-индекс с защитой от шума на малом капитале."""
    if not total_values:
        return {}

    dates = sorted(total_values.keys())
    index: dict = {}
    index[dates[0]] = start_index

    for i in range(1, len(dates)):
        prev = dates[i - 1]
        curr = dates[i]

        v_prev = total_values[prev]
        v_curr = total_values[curr]
        flow = flows.get(curr, 0.0)

        # Защита 1: капитал слишком мал
        if v_prev < min_capital and v_curr < min_capital:
            index[curr] = index[prev]
            continue

        # Защита 2: пополнение при малом капитале
        if v_prev < min_capital and flow > 0:
            index[curr] = index[prev]
            continue

        denom = v_prev + flow
        if denom <= 0:
            index[curr] = index[prev]
            continue

        daily_return = v_curr / denom - 1

        # Защита 3: аномальный скачок
        if abs(daily_return) > max_daily_return:
            logger.warning(
                "TWR: аномальный скачок %s → %s: %.2f%% — обнуляем",
                prev, curr, daily_return * 100,
            )
            index[curr] = index[prev]
            continue

        index[curr] = index[prev] * (1 + daily_return)

    return index


# ============================================================
# 10. Net invested (накопленный)
# ============================================================

def build_net_invested(session, date_from: date, date_to: date) -> dict:
    from sqlalchemy import func, or_
    from database.db import day_expr

    day = day_expr(InvestOperationDB.date)

    # Сумма всех deposit/withdraw ДО date_from
    start_value = (
        session.query(
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0)
        )
        .filter(
            InvestOperationDB.kind.in_(['deposit', 'withdraw']),
            InvestOperationDB.date < datetime.combine(date_from, datetime.min.time()),
            or_(
                InvestOperationDB.operation_type.is_(None),
                InvestOperationDB.operation_type.notin_([
                    'OPERATION_TYPE_INP_MULTI',
                    'OPERATION_TYPE_OUT_MULTI',
                ]),
            ),
        )
        .scalar()
    ) or 0.0

    # Дневные потоки за период
    rows = (
        session.query(
            day.label('day'),
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['deposit', 'withdraw']),
            InvestOperationDB.date >= datetime.combine(date_from, datetime.min.time()),
            InvestOperationDB.date <= datetime.combine(date_to, datetime.max.time()),
            or_(
                InvestOperationDB.operation_type.is_(None),
                InvestOperationDB.operation_type.notin_([
                    'OPERATION_TYPE_INP_MULTI',
                    'OPERATION_TYPE_OUT_MULTI',
                ]),
            ),
        )
        .group_by(day)
        .all()
    )

    daily_flows: dict[date, float] = {}
    for day_val, total in rows:
        if not day_val:
            continue
        d = day_val.date() if hasattr(day_val, 'date') else day_val
        if not isinstance(d, date):
            d = datetime.fromisoformat(str(day_val)).date()
        daily_flows[d] = float(total or 0)

    # Накапливаем
    result: dict[date, float] = {}
    current = date_from
    accumulated = float(start_value)

    while current <= date_to:
        accumulated += daily_flows.get(current, 0.0)
        result[current] = round(accumulated, 2)
        current += timedelta(days=1)

    return result


# ============================================================
# 11. P&L = total_value − net_invested
# ============================================================

def calculate_daily_pnl(
    session,
    total_values: dict,
    date_from: date,
    date_to: date,
) -> dict:
    """
    P&L(T) = total_value(T) − net_invested(T).

    НКД и амортизация УЖЕ в total_value.
    """
    if not total_values:
        return {}

    net_invested = build_net_invested(session, date_from, date_to)

    pnl: dict = {}
    for d in sorted(total_values.keys()):
        pnl[d] = round(total_values[d] - net_invested.get(d, 0.0), 2)

    return pnl


# ============================================================
# 12. Оркестратор
# ============================================================

def build_snapshots_for_period(session, date_from: date, date_to: date,
                               account_id: str = 'all',
                               start_cash: float = 0.0,
                               start_positions: dict | None = None,
                               start_index: float = 100.0) -> dict:
    crud = SnapshotCrud(session)

    timeline = build_positions_timeline(
        session, date_from, date_to, start_positions=start_positions,
    )
    if not timeline:
        return {'added': 0, 'updated': 0, 'skipped': 0}

    flows = build_daily_flows(session, date_from, date_to)
    daily_cash = build_daily_cash(session, date_from, date_to, start_cash=start_cash)

    figis = list(timeline.keys())
    candles = load_candles_for_figis(crud, figis, date_from, date_to)
    price_factors = compute_price_factors(session, timeline, candles)

    # --- НКД для облигаций ---
    nkd_data = load_accrued_interests(session, figis, date_from, date_to)

    paper_values, total_values, positions_count = build_daily_values(
        timeline, candles, daily_cash, price_factors,
        date_from, date_to,
        nkd_data=nkd_data,
    )

    # TWR
    index = calculate_twr_index(total_values, flows, date_from, start_index)

    # P&L = total_value − net_invested
    pnl = calculate_daily_pnl(session, total_values, date_from, date_to)

    stats = {'added': 0, 'updated': 0, 'skipped': 0}

    for d in sorted(total_values.keys()):
        result = crud.upsert_snapshot(d, account_id, {
            'total_value': total_values[d],
            'paper_value': paper_values[d],
            'cash_value': daily_cash.get(d, 0.0),
            'external_flow': flows.get(d, 0.0),
            'index_value': index.get(d, start_index),
            'pnl_value': pnl.get(d, 0.0),
            'positions_count': positions_count.get(d, 0),
        })
        stats[result] += 1

    return stats