"""Разложение P&L по компонентам + сводка по тикерам + НКД.

Считает:
- Купоны, дивиденды (реальный доход)
- Реализованный P&L от продаж (FIFO)
- Нереализованный P&L по текущим позициям (с учётом амортизации)
- Комиссии, налоги
- Итого P&L по каждому тикеру
- Количество бумаг в портфеле на текущий момент
- НКД по каждой позиции и общий

Важно:
- Погашение облигаций и амортизация НЕ считаются доходом —
  это возврат вложенного капитала.
- Но при расчёте нереализованного P&L амортизация учитывается,
  чтобы компенсировать падение цены облигации после частичного
  погашения номинала.
- Комиссии и налоги учитываются со знаком минус.
"""
import logging
import sys
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func

from database.db import Session, InvestOperationDB, AccruedInterestCacheDB
from database.instrument_crud import InstrumentCrud


# Дата старта (с 05.08 по ТЗ)
DATE_FROM = datetime(2026, 8, 5)


def _to_float(v) -> float:
    if v is None:
        return 0.0
    return float(v)


def _fmt_qty(q: float) -> str:
    """Форматирует количество: целое — без дробной части, иначе 2 знака."""
    if q == int(q):
        return str(int(q))
    return f"{q:.2f}"


# ------------------------------------------------------------
# 1. Купоны, дивиденды (общая сумма)
# ------------------------------------------------------------

def get_income(session) -> dict:
    """
    Только купоны и дивиденды — это реальный доход.

    Погашение облигаций и амортизация — возврат вложенного капитала,
    а не доход.
    """
    rows = (
        session.query(
            InvestOperationDB.kind,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['coupon', 'dividend']),
            InvestOperationDB.date >= DATE_FROM,
        )
        .group_by(InvestOperationDB.kind)
        .all()
    )
    return {kind: _to_float(total) for kind, total in rows}


# ------------------------------------------------------------
# 1b. Купоны, дивиденды по FIGI
# ------------------------------------------------------------

def get_income_by_figi(session) -> dict[str, dict]:
    """{figi: {'coupon': X, 'dividend': Y}} — только купоны и дивиденды."""
    rows = (
        session.query(
            InvestOperationDB.figi,
            InvestOperationDB.kind,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['coupon', 'dividend']),
            InvestOperationDB.date >= DATE_FROM,
            InvestOperationDB.figi.isnot(None),
        )
        .group_by(InvestOperationDB.figi, InvestOperationDB.kind)
        .all()
    )

    result: dict[str, dict] = {}
    for figi, kind, total in rows:
        result.setdefault(figi, {})[kind] = _to_float(total)
    return result


# ------------------------------------------------------------
# 2. Комиссии и налоги (общая сумма)
# ------------------------------------------------------------

def get_fees(session) -> dict:
    """Комиссии, маржинальные комиссии, налоги (со знаком минус)."""
    rows = (
        session.query(
            InvestOperationDB.kind,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['fee', 'margin_fee', 'tax']),
            InvestOperationDB.date >= DATE_FROM,
        )
        .group_by(InvestOperationDB.kind)
        .all()
    )
    return {kind: _to_float(total) for kind, total in rows}


# ------------------------------------------------------------
# 2b. Комиссии и налоги по FIGI
# ------------------------------------------------------------

def get_fees_by_figi(session) -> dict[str, float]:
    """{figi: сумма комиссий и налогов (со знаком минус)}."""
    rows = (
        session.query(
            InvestOperationDB.figi,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['fee', 'margin_fee', 'tax']),
            InvestOperationDB.date >= DATE_FROM,
            InvestOperationDB.figi.isnot(None),
        )
        .group_by(InvestOperationDB.figi)
        .all()
    )
    return {figi: _to_float(total) for figi, total in rows}


# ------------------------------------------------------------
# 2c. НКД по FIGI (последнее значение из кэша)
# ------------------------------------------------------------

def get_nkd_by_figi(session) -> dict[str, float]:
    """
    {figi: НКД на 1 бумагу (последнее значение из кэша)}.

    Берём максимальную дату в accrued_interest_cache для каждого FIGI.
    """
    # Подзапрос: максимальная дата для каждого FIGI
    subq = (
        session.query(
            AccruedInterestCacheDB.figi,
            func.max(AccruedInterestCacheDB.date).label('max_date'),
        )
        .group_by(AccruedInterestCacheDB.figi)
        .subquery()
    )

    rows = (
        session.query(
            AccruedInterestCacheDB.figi,
            AccruedInterestCacheDB.value,
        )
        .join(
            subq,
            (AccruedInterestCacheDB.figi == subq.c.figi)
            & (AccruedInterestCacheDB.date == subq.c.max_date),
        )
        .all()
    )

    return {figi: _to_float(value) for figi, value in rows}


# ------------------------------------------------------------
# 3. Реализованный P&L (FIFO)
# ------------------------------------------------------------

def get_realized_pnl(session) -> dict:
    trades = (
        session.query(InvestOperationDB)
        .filter(
            InvestOperationDB.kind.in_(['buy', 'sell']),
            InvestOperationDB.date >= DATE_FROM,
            InvestOperationDB.figi.isnot(None),
        )
        .order_by(InvestOperationDB.date)
        .all()
    )

    lots: dict[str, list[list[Decimal]]] = {}
    by_figi: dict[str, dict] = {}

    for t in trades:
        figi = t.figi
        qty = Decimal(str(t.quantity or 0))
        price = Decimal(str(t.price_per_unit or 0))
        kind = t.kind

        lots.setdefault(figi, [])
        by_figi.setdefault(figi, {
            'ticker': t.ticker,
            'buy_qty': Decimal(0),
            'sell_qty': Decimal(0),
            'buy_cost': Decimal(0),
            'sell_income': Decimal(0),
            'pnl': Decimal(0),
        })

        if kind == 'buy':
            lots[figi].append([qty, price])
            by_figi[figi]['buy_qty'] += qty
            by_figi[figi]['buy_cost'] += qty * price
        elif kind == 'sell':
            by_figi[figi]['sell_qty'] += qty
            by_figi[figi]['sell_income'] += qty * price

            remaining = qty
            realized = Decimal(0)
            while remaining > 0 and lots[figi]:
                lot_qty, lot_price = lots[figi][0]
                take = min(lot_qty, remaining)
                realized += (price - lot_price) * take
                lot_qty -= take
                remaining -= take
                if lot_qty == 0:
                    lots[figi].pop(0)
                else:
                    lots[figi][0][0] = lot_qty

            by_figi[figi]['pnl'] += realized

    total = sum(v['pnl'] for v in by_figi.values())

    return {
        'total': float(total),
        'by_figi': {
            figi: {
                'ticker': v['ticker'],
                'buy_qty': float(v['buy_qty']),
                'sell_qty': float(v['sell_qty']),
                'buy_cost': float(v['buy_cost']),
                'sell_income': float(v['sell_income']),
                'pnl': float(v['pnl']),
            }
            for figi, v in by_figi.items()
            if v['sell_qty'] > 0
        },
    }


# ------------------------------------------------------------
# 4. Нереализованный P&L + текущие позиции (с учётом амортизации)
# ------------------------------------------------------------

def get_unrealized_pnl(session) -> dict:
    """
    Возвращает:
    {
      'total': float,
      'by_figi': {figi: {ticker, qty, avg_price, current_price,
                          amort_per_unit, pnl}},
      'positions_count': int,
      'positions_total_qty': float,
    }

    ВАЖНО: учитывает амортизацию облигаций.
    Амортизация — это возврат капитала, а не убыток.
    Она компенсирует падение цены облигации после частичного
    погашения номинала.
    """
    from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
    from config.settings import ACCOUNTS_ID

    trades = (
        session.query(InvestOperationDB)
        .filter(
            InvestOperationDB.kind.in_(['buy', 'sell']),
            InvestOperationDB.date >= DATE_FROM,
            InvestOperationDB.figi.isnot(None),
        )
        .order_by(InvestOperationDB.date)
        .all()
    )

    lots: dict[str, list[list[Decimal]]] = {}
    for t in trades:
        figi = t.figi
        qty = Decimal(str(t.quantity or 0))
        price = Decimal(str(t.price_per_unit or 0))

        lots.setdefault(figi, [])

        if t.kind == 'buy':
            lots[figi].append([qty, price])
        elif t.kind == 'sell':
            remaining = qty
            while remaining > 0 and lots[figi]:
                lot_qty, lot_price = lots[figi][0]
                take = min(lot_qty, remaining)
                lot_qty -= take
                remaining -= take
                if lot_qty == 0:
                    lots[figi].pop(0)
                else:
                    lots[figi][0][0] = lot_qty

    # --- Амортизация по FIGI (возврат капитала) ---
    amort_rows = (
        session.query(
            InvestOperationDB.figi,
            func.coalesce(func.sum(InvestOperationDB.payment_amount), 0),
        )
        .filter(
            InvestOperationDB.kind.in_(['amortization', 'bond_repayment']),
            InvestOperationDB.date >= DATE_FROM,
            InvestOperationDB.figi.isnot(None),
        )
        .group_by(InvestOperationDB.figi)
        .all()
    )
    amort_by_figi = {figi: _to_float(total) for figi, total in amort_rows}

    current_positions = {}
    with TInvestPortfolioClient() as client:
        for acc in ACCOUNTS_ID:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)
            for pos in p['positions']:
                if pos['quantity'] > 0:
                    current_positions[pos['figi']] = {
                        'qty': pos['quantity'],
                        'current_price': pos['current_price'],
                        'ticker': pos.get('ticker'),
                    }

    by_figi = {}
    total = 0.0
    for figi, pos in current_positions.items():
        figi_lots = lots.get(figi, [])
        if not figi_lots:
            continue

        total_qty = sum(float(l[0]) for l in figi_lots)
        if total_qty == 0:
            continue

        avg_price = sum(float(l[0]) * float(l[1]) for l in figi_lots) / total_qty
        current_price = pos['current_price']

        # Амортизация на 1 бумагу
        amort_total = amort_by_figi.get(figi, 0.0)
        amort_per_unit = amort_total / total_qty if total_qty > 0 else 0.0

        # Реальный P&L = (текущая цена + амортизация − цена покупки) × кол-во
        pnl = (current_price + amort_per_unit - avg_price) * total_qty

        by_figi[figi] = {
            'ticker': pos['ticker'],
            'qty': total_qty,
            'avg_price': avg_price,
            'current_price': current_price,
            'amort_per_unit': amort_per_unit,
            'pnl': pnl,
        }
        total += pnl

    return {
        'total': total,
        'by_figi': by_figi,
        'positions_count': len(by_figi),
        'positions_total_qty': sum(v['qty'] for v in by_figi.values()),
    }


# ------------------------------------------------------------
# 5. Сводка по тикерам (+ НКД)
# ------------------------------------------------------------

def build_ticker_summary(
    session,
    income_by_figi: dict,
    fees_by_figi: dict,
    realized: dict,
    unrealized: dict,
    nkd_by_figi: dict,
) -> list[dict]:
    """Собирает всё в одну таблицу по тикерам + НКД."""
    crud = InstrumentCrud(session)

    all_figis = set()
    all_figis.update(income_by_figi.keys())
    all_figis.update(fees_by_figi.keys())
    all_figis.update(realized['by_figi'].keys())
    all_figis.update(unrealized['by_figi'].keys())
    all_figis.update(nkd_by_figi.keys())

    rows = []
    for figi in all_figis:
        info = crud.get(figi)
        ticker = info.ticker if info and info.ticker else figi[:15]

        # Купоны/дивиденды (без амортизации и погашения!)
        income = income_by_figi.get(figi, {})
        coupons = income.get('coupon', 0.0)
        dividends = income.get('dividend', 0.0)
        income_total = coupons + dividends

        # Комиссии (уже со знаком минус)
        fees = fees_by_figi.get(figi, 0.0)

        # Реализованный P&L
        r = realized['by_figi'].get(figi, {})
        realized_pnl = r.get('pnl', 0.0)
        buy_qty = r.get('buy_qty', 0.0)
        sell_qty = r.get('sell_qty', 0.0)

        # Нереализованный P&L + текущее количество
        u = unrealized['by_figi'].get(figi, {})
        unrealized_pnl = u.get('pnl', 0.0)
        cur_qty = u.get('qty', 0.0)

        # НКД на 1 бумагу и общий НКД
        nkd_per_unit = nkd_by_figi.get(figi, 0.0)
        nkd_total = nkd_per_unit * cur_qty

        total = income_total + realized_pnl + unrealized_pnl + fees

        rows.append({
            'figi': figi,
            'ticker': ticker,
            'coupons': coupons,
            'dividends': dividends,
            'income_total': income_total,
            'fees': fees,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'nkd_per_unit': nkd_per_unit,
            'nkd_total': nkd_total,
            'total': total,
            'buy_qty': buy_qty,
            'sell_qty': sell_qty,
            'cur_qty': cur_qty,
        })

    rows.sort(key=lambda x: -x['total'])
    return rows


# ------------------------------------------------------------
# 6. Main
# ------------------------------------------------------------

def main():
    logging.basicConfig(level=logging.WARNING)

    with Session() as s:
        income = get_income(s)
        coupons = income.get('coupon', 0)
        dividends = income.get('dividend', 0)

        fees = get_fees(s)
        fee_total = fees.get('fee', 0) + fees.get('margin_fee', 0)
        tax_total = fees.get('tax', 0)

        realized = get_realized_pnl(s)
        unrealized = get_unrealized_pnl(s)

        income_by_figi = get_income_by_figi(s)
        fees_by_figi = get_fees_by_figi(s)
        nkd_by_figi = get_nkd_by_figi(s)

        ticker_rows = build_ticker_summary(
            s, income_by_figi, fees_by_figi, realized, unrealized,
            nkd_by_figi,
        )

    # ============================================================
    # Общая сводка
    # ============================================================

    print()
    print("=" * 80)
    print("  РАЗЛОЖЕНИЕ P&L ЗА ПЕРИОД")
    print(f"  с {DATE_FROM.date()} по сегодня")
    print("=" * 80)
    print()

    print("📥 ДОХОДЫ:")
    print(f"  Купоны:                {coupons:>12,.2f} ₽")
    print(f"  Дивиденды:             {dividends:>12,.2f} ₽")
    print(f"  ─────────────────────────────────────")
    print(f"  Итого доходов:         {coupons + dividends:>12,.2f} ₽")
    print()

    print("📤 РАСХОДЫ:")
    print(f"  Комиссии:              {fee_total:>12,.2f} ₽")
    print(f"  Налоги:                {tax_total:>12,.2f} ₽")
    print(f"  ─────────────────────────────────────")
    print(f"  Итого расходов:        {fee_total + tax_total:>12,.2f} ₽")
    print()

    print("📊 РЕАЛИЗОВАННЫЙ P&L (FIFO, по проданным бумагам):")
    print(f"  Итого:                 {realized['total']:>12,.2f} ₽")
    print()

    print("📈 НЕРЕАЛИЗОВАННЫЙ P&L (движение текущих бумаг, с учётом амортизации):")
    print(f"  Итого:                 {unrealized['total']:>12,.2f} ₽")
    print()

    # ============================================================
    # Общий НКД
    # ============================================================

    total_nkd = sum(r['nkd_total'] for r in ticker_rows)
    total_nkd_per_unit_only = sum(
        r['nkd_per_unit'] for r in ticker_rows if r['cur_qty'] > 0
    )

    print("=" * 80)
    print("  НКД (накопленный купонный доход)")
    print("=" * 80)
    print()
    print(f"  Общий НКД по портфелю: {total_nkd:>15,.2f} ₽")
    print()

    # ============================================================
    # Сводка по портфелю
    # ============================================================

    print("=" * 80)
    print("  ТЕКУЩИЙ ПОРТФЕЛЬ")
    print("=" * 80)
    print()
    print(f"  Уникальных бумаг:       {unrealized['positions_count']:>12}")
    print(f"  Всего единиц (сумма):   {unrealized['positions_total_qty']:>12,.2f}")
    print()

    # ============================================================
    # Сводка по тикерам
    # ============================================================

    print("=" * 80)
    print("  СВОДКА ПО ТИКЕРАМ")
    print("=" * 80)
    print()

    header = (
        f"{'Тикер':<10} "
        f"{'Кол-во':>10} "
        f"{'Купоны':>10} "
        f"{'Дивы':>8} "
        f"{'Комис':>9} "
        f"{'Реал.PnL':>11} "
        f"{'Нереал.PnL':>12} "
        f"{'НКД/шт':>10} "
        f"{'НКД всего':>12} "
        f"{'ИТОГО':>12}"
    )
    print(header)
    print("-" * 120)

    for r in ticker_rows:
        if (abs(r['total']) < 0.01
                and abs(r['realized_pnl']) < 0.01
                and abs(r['unrealized_pnl']) < 0.01
                and abs(r['income_total']) < 0.01
                and abs(r['fees']) < 0.01
                and r['cur_qty'] == 0
                and abs(r['nkd_total']) < 0.01):
            continue

        qty_str = _fmt_qty(r['cur_qty'])

        print(
            f"{r['ticker']:<10} "
            f"{qty_str:>10} "
            f"{r['coupons']:>10,.2f} "
            f"{r['dividends']:>8,.2f} "
            f"{r['fees']:>9,.2f} "
            f"{r['realized_pnl']:>+11,.2f} "
            f"{r['unrealized_pnl']:>+12,.2f} "
            f"{r['nkd_per_unit']:>10,.2f} "
            f"{r['nkd_total']:>12,.2f} "
            f"{r['total']:>+12,.2f}"
        )

    print("-" * 120)

    sum_coupons = sum(r['coupons'] for r in ticker_rows)
    sum_divs = sum(r['dividends'] for r in ticker_rows)
    sum_fees = sum(r['fees'] for r in ticker_rows)
    sum_realized = sum(r['realized_pnl'] for r in ticker_rows)
    sum_unrealized = sum(r['unrealized_pnl'] for r in ticker_rows)
    sum_nkd_total = sum(r['nkd_total'] for r in ticker_rows)
    sum_total = sum(r['total'] for r in ticker_rows)

    print(
        f"{'ИТОГО':<10} "
        f"{_fmt_qty(unrealized['positions_total_qty']):>10} "
        f"{sum_coupons:>10,.2f} "
        f"{sum_divs:>8,.2f} "
        f"{sum_fees:>9,.2f} "
        f"{sum_realized:>+11,.2f} "
        f"{sum_unrealized:>+12,.2f} "
        f"{'':>10} "
        f"{sum_nkd_total:>12,.2f} "
        f"{sum_total:>+12,.2f}"
    )
    print()

    # ============================================================
    # Топ позиций по НКД
    # ============================================================

    print("=" * 80)
    print("  ТОП-10 ПО НКД")
    print("=" * 80)
    print()

    top_by_nkd = sorted(
        [r for r in ticker_rows if r['nkd_total'] > 0],
        key=lambda x: -x['nkd_total'],
    )[:10]

    for r in top_by_nkd:
        print(
            f"  {r['ticker']:<15} "
            f"{_fmt_qty(r['cur_qty']):>10} шт × "
            f"{r['nkd_per_unit']:>8,.2f} ₽ = "
            f"{r['nkd_total']:>12,.2f} ₽"
        )

    print()

    # ============================================================
    # Топ позиций по количеству
    # ============================================================

    print("=" * 80)
    print("  ТОП-10 ПО КОЛИЧЕСТВУ БУМАГ")
    print("=" * 80)
    print()

    top_by_qty = sorted(
        [r for r in ticker_rows if r['cur_qty'] > 0],
        key=lambda x: -x['cur_qty'],
    )[:10]

    for r in top_by_qty:
        print(f"  {r['ticker']:<15} {_fmt_qty(r['cur_qty']):>15} шт")

    print()

    # ============================================================
    # Итог
    # ============================================================

    total_income = coupons + dividends
    total_expenses = fee_total + tax_total
    total_pnl = (
        total_income
        + total_expenses        # total_expenses уже отрицательный
        + realized['total']
        + unrealized['total']
    )

    print("=" * 80)
    print("  ИТОГО P&L:")
    print("=" * 80)
    print(f"  Доходы:                {total_income:>+12,.2f} ₽")
    print(f"  Расходы:               {total_expenses:>+12,.2f} ₽")
    print(f"  Реализованный P&L:     {realized['total']:>+12,.2f} ₽")
    print(f"  Нереализованный P&L:   {unrealized['total']:>+12,.2f} ₽")
    print(f"  ─────────────────────────────────────")
    print(f"  ИТОГО P&L:             {total_pnl:>+12,.2f} ₽")
    print()
    print(f"  Справочно (не в P&L):")
    print(f"    НКД (не реализован): {total_nkd:>+12,.2f} ₽")
    print()


if __name__ == "__main__":
    main()