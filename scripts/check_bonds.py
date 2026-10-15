"""Оценка облигаций.

Режимы:
    python scripts/check_bonds.py --db                    # все из БД
    python scripts/check_bonds.py --portfolio             # только из портфеля
    python scripts/check_bonds.py -t RU000A109E71         # конкретные тикеры
    python scripts/check_bonds.py -t RU000A109E71 RU000A10FWA1

Сортировка: BUY → HOLD → AVOID, внутри — по убыванию YTM.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import Session, InstrumentInfoDB
from database.instrument_crud import InstrumentCrud
from invest.bond_score import evaluate_bond
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
from config.settings import ACCOUNTS_ID


logging.basicConfig(level=logging.WARNING)


# ------------------------------------------------------------
# 1. Оценка одной облигации по тикеру (с добавлением в БД)
# ------------------------------------------------------------

def evaluate_bond_by_ticker(ticker: str, save: bool = True) -> dict | None:
    """Оценивает облигацию по тикеру (ISIN). Если нет в БД — добавляет."""
    from invest.bond_resolver import ensure_bond_in_db

    ticker = ticker.strip().upper()
    figi = ensure_bond_in_db(ticker, save=save)
    if not figi:
        print(f"[!] Не удалось найти облигацию {ticker} в БД или API")
        return None

    return evaluate_bond(figi)


# ------------------------------------------------------------
# 2. Все облигации из БД
# ------------------------------------------------------------

def evaluate_bonds_from_db() -> list[dict]:
    """Оценивает все облигации из instrument_info."""
    with Session() as s:
        rows = (
            s.query(InstrumentInfoDB.figi)
            .filter(InstrumentInfoDB.instrument_type == 'bond')
            .all()
        )
        figis = [r[0] for r in rows if r[0]]

    results = []
    for figi in figis:
        try:
            data = evaluate_bond(figi)
            if 'error' not in data:
                results.append(data)
        except Exception as e:
            print(f"Ошибка {figi}: {e}")

    return _sort_results(results)


# ------------------------------------------------------------
# 3. Только облигации из портфеля
# ------------------------------------------------------------

def evaluate_bonds_from_portfolio() -> list[dict]:
    """Оценивает только облигации из текущего портфеля."""
    with Session() as s:
        crud = InstrumentCrud(s)
        figis = []

        with TInvestPortfolioClient() as client:
            for acc in ACCOUNTS_ID:
                raw = client.fetch_portfolio(acc)
                if not raw:
                    continue
                p = parse_portfolio(raw)
                for pos in p['positions']:
                    info = crud.get(pos['figi'])
                    if info and info.instrument_type == 'bond':
                        value = pos['quantity'] * pos['current_price']
                        if value > 0:
                            figis.append(pos['figi'])

    results = []
    for figi in set(figis):
        try:
            data = evaluate_bond(figi)
            if 'error' not in data:
                results.append(data)
        except Exception as e:
            print(f"Ошибка {figi}: {e}")

    return _sort_results(results)


# ------------------------------------------------------------
# 4. Сортировка
# ------------------------------------------------------------

def _sort_results(results: list[dict]) -> list[dict]:
    """BUY → HOLD → AVOID, внутри — по убыванию YTM."""
    order = {"BUY": 0, "HOLD": 1, "AVOID": 2}
    results.sort(key=lambda x: (
        order.get(x['verdict'], 3),
        -(x.get('ytm') or 0),
    ))
    return results


# ------------------------------------------------------------
# 5. Печать
# ------------------------------------------------------------

def print_bond(r: dict):
    emoji = {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}.get(r['verdict'], "❓")

    print(f"{emoji} {r['ticker']:<15} "
          f"YTM={r['ytm'] or 0:>6.2f}%  "
          f"купон={r['coupon'] or 0:>5.1f}%  "
          f"дюрация={r['duration_human']:<10} "
          f"рейтинг={r['rating'] or '—':<6} "
          f"→ {r['verdict']}")

    for reason in r['reasons'][:3]:
        print(f"     ✅ {reason}")
    for warn in r['warnings'][:3]:
        print(f"     ⚠️  {warn}")
    print()


def print_summary(results: list[dict]):
    buy = [r for r in results if r['verdict'] == 'BUY']
    hold = [r for r in results if r['verdict'] == 'HOLD']
    avoid = [r for r in results if r['verdict'] == 'AVOID']

    print()
    print("=" * 100)
    print("  ИТОГ")
    print("=" * 100)
    print(f"  🟢 BUY:   {len(buy)}")
    print(f"  🟡 HOLD:  {len(hold)}")
    print(f"  🔴 AVOID: {len(avoid)}")
    print(f"  Всего:    {len(results)}")
    print()


# ------------------------------------------------------------
# 6. CLI
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Оценка облигаций")
    parser.add_argument(
        "-t", "--ticker", nargs="+", default=None,
        help="ISIN облигаций (можно несколько)",
    )
    parser.add_argument(
        "--db", action="store_true",
        help="Все облигации из БД",
    )
    parser.add_argument(
        "--portfolio", "-p", action="store_true",
        help="Только облигации из текущего портфеля",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Не сохранять новые облигации в БД",
    )
    args = parser.parse_args()

    # --- Режим 1: конкретные тикеры ---
    if args.ticker:
        print()
        print("=" * 100)
        print(f"  ОЦЕНКА ОБЛИГАЦИЙ: {', '.join(args.ticker)}")
        print("=" * 100)
        print()

        results = []
        for ticker in args.ticker:
            result = evaluate_bond_by_ticker(
                ticker,
                save=not args.no_save,
            )
            if result:
                print_bond(result)
                results.append(result)

        if results:
            print_summary(results)
        return

    # --- Режим 2: только портфель ---
    if args.portfolio:
        print()
        print("=" * 100)
        print("  ОЦЕНКА ОБЛИГАЦИЙ ПОРТФЕЛЯ")
        print("=" * 100)
        print()

        results = evaluate_bonds_from_portfolio()
        for r in results:
            print_bond(r)
        if results:
            print_summary(results)
        return

    # --- Режим 3 (по умолчанию): все из БД ---
    print()
    print("=" * 100)
    print("  ОЦЕНКА ВСЕХ ОБЛИГАЦИЙ ИЗ БД")
    print("=" * 100)
    print()

    results = evaluate_bonds_from_db()
    for r in results:
        print_bond(r)
    if results:
        print_summary(results)


if __name__ == "__main__":
    main()