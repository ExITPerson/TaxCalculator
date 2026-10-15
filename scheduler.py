"""Главный модуль: бот, scheduler, проверка скоринга.

Запуск:
    python main.py                        — обычный запуск (бот / scheduler)
    python main.py check                  — все акции из БД
    python main.py check --portfolio      — только акции из портфеля
    python main.py check -t SBER GAZP     — конкретные тикеры
"""
import argparse
import logging
import sys

from database.db import Session, engine, Base
import database.db  # noqa: F401
from database.fundamentals_crud import StockFundamentalsCrud
from database.instrument_crud import InstrumentCrud
from invest.fundamentals.smartlab_parser import (
    fetch_stock_fundamentals,
    _normalize_ticker,
)
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
from invest.scoring.final_verdict import final_verdict
from config.settings import ACCOUNTS_ID


logger = logging.getLogger(__name__)


# ============================================================
# Список тикеров (по умолчанию)
# ============================================================

CHECK_TICKERS = [
    "GAZP", 'LKOH', 'SBER', 'ROSM', 'OZON', 'T', 'SMLT', 'VTBR', 'NVTK', 'YDEX', 'PLZL',
    'GMKN', 'TATN', 'MAGN', 'MTSS', 'X5', 'CHMF', 'VKCO', 'SNGS', 'MGNT', 'RUAL', 'ALRS',
    'SIBN', 'NLMK', 'SVCB', 'PHOR', 'SPBE', 'AFLT', 'HEAD', 'AFKS', 'MOEX', 'POSI', 'TRNF',
    'MTLR', 'DOMRF', 'BSPB', 'RAGR', 'IRAO', 'SGZH', 'SELG', 'FLOT', 'RNFT', 'RTKM', 'UPRO',
    'CBOM', 'FEES', 'VSEH', 'UGLD', 'EUTR', 'ASTR', 'FESH', 'ENPG', 'LENT', 'SFIN', 'HYDR',
    'WUSH', 'CNRU', 'UNAC', 'MDMG', 'MSNG', 'PRMD', 'NMTP', 'BELU', 'OZPH', 'MRKC', 'IRKT',
    'RENI', 'AQUA', 'GLRX', 'TRMK', 'RASP', 'FIXR', 'PIKK', 'IVAT', 'UWGN', 'MVID', 'SOFL',
    'ROLO', 'LSRG', 'BTBR', 'BAZA', 'DATA', 'TGKA', 'MBNK', 'BANE', 'GCHE', 'KMAZ', 'DIAS',
    'SVAV', 'ZAYM', 'ETLN', 'GEMC', 'DVEC', 'NKHP', 'DELI', 'AKRN', 'HNFG', 'ELFV', 'RBCM',
    'MGKL', 'LEAS', 'PMSB', 'ABIO', 'LIFE', 'ELMT', 'GTRK', 'KROT', 'KAZT', 'NSVZ', 'KLSB',
    'KRKN', 'KZOS', 'OKEY', 'TTLK', 'ABRD', 'CHMK', 'INCB', 'GECO', 'YAKG', 'BLNG',
    'RKKE', 'MSTT', 'CARM', 'CNTL', 'PRFN', 'VEON-RX', 'LNZL',
]


# ============================================================
# 1. Загрузка фундаментала
# ============================================================

def _ensure_fundamentals(tickers: list[str], delay: float = 0.5) -> None:
    """Загружает фундаментал для тикеров, которых нет в БД."""
    import time

    with Session() as s:
        crud = StockFundamentalsCrud(s)

        for i, ticker in enumerate(tickers, 1):
            if crud.get_latest(ticker):
                continue

            print(f"[{i}/{len(tickers)}] {ticker}: парсим...", end=" ")

            try:
                data = fetch_stock_fundamentals(ticker)
            except Exception as e:
                print(f"ОШИБКА: {e}")
                continue

            if not data:
                print("НЕ НАЙДЕНО")
                continue

            for year, metrics in data.items():
                crud.upsert(ticker, year, **metrics)

            print(f"OK ({len(data)} лет)")
            time.sleep(delay)


# ============================================================
# 2. Оценка одной акции
# ============================================================

def evaluate_stock(ticker: str) -> dict | None:
    """Оценивает акцию по тикеру (с автозагрузкой фундаментала)."""
    ticker = _normalize_ticker(ticker)
    _ensure_fundamentals([ticker])

    try:
        return final_verdict(ticker, auto_backfill=False)
    except Exception as e:
        print(f"❌ {ticker}: {e}")
        return None


# ============================================================
# 3. Все акции из БД
# ============================================================

def evaluate_stocks_from_db() -> list[dict]:
    """Оценивает все акции, для которых есть фундаментал в БД."""
    with Session() as s:
        rows = (
            s.query(StockFundamentalsCrud.__module__ and None)  # placeholder
        )
        # Получаем уникальные тикеры из stock_fundamentals
        from database.db import StockFundamentalsDB
        tickers = [
            r[0] for r in s.query(StockFundamentalsDB.ticker).distinct().all()
        ]

    results = []
    for ticker in tickers:
        try:
            v = final_verdict(ticker, auto_backfill=False)
            results.append(v)
        except Exception as e:
            print(f"❌ {ticker}: {e}")

    return _sort_results(results)


# ============================================================
# 4. Только акции из портфеля
# ============================================================

def evaluate_stocks_from_portfolio() -> list[dict]:
    """Оценивает только акции из текущего портфеля."""
    with Session() as s:
        crud = InstrumentCrud(s)
        tickers = set()

        with TInvestPortfolioClient() as client:
            for acc in ACCOUNTS_ID:
                raw = client.fetch_portfolio(acc)
                if not raw:
                    continue
                p = parse_portfolio(raw)
                for pos in p['positions']:
                    info = crud.get(pos['figi'])
                    if not info:
                        continue
                    if info.instrument_type == 'share' and info.ticker:
                        tickers.add(_normalize_ticker(info.ticker))

    tickers = sorted(tickers)
    print(f"Акций в портфеле: {len(tickers)}")

    _ensure_fundamentals(tickers)

    results = []
    for ticker in tickers:
        try:
            v = final_verdict(ticker, auto_backfill=False)
            results.append(v)
        except Exception as e:
            print(f"❌ {ticker}: {e}")

    return _sort_results(results)


# ============================================================
# 5. Сортировка и печать
# ============================================================

def _sort_results(results: list[dict]) -> list[dict]:
    order = {"BUY": 0, "HOLD": 1, "AVOID": 2, "STRONG_AVOID": 3}
    results.sort(key=lambda x: (
        order.get(x["action"], 4),
        -x["score"],
    ))
    return results


def print_verdict(v: dict) -> None:
    emoji = {"BUY": "🟢", "HOLD": "🟡",
             "AVOID": "🔴", "STRONG_AVOID": "⛔"}.get(v["action"], "❓")

    print(f"{emoji} {v['ticker']:<8} [{v['kind']:<6}] "
          f"score={v['score']:5.1f}  {v['action']}")

    for c in v["critical"]:
        print(f"    ⛔ {c}")
    for r in v["info"][:5]:
        print(f"    ✅ {r}")
    for w in v["warnings"][:3]:
        print(f"    ⚠️  {w}")
    for n in v["notes"]:
        print(f"    ℹ️  {n}")

    if v.get("pe_data"):
        pe = v["pe_data"]
        print(f"    📊 P/E {pe['current_pe']} "
              f"({int(pe['percentile'] * 100)}-й перцентиль, "
              f"{pe['verdict']})")

    if v.get("dcf_data"):
        d = v["dcf_data"]
        print(f"    💰 DCF: fair {d['fair_price']:.0f} ₽ "
              f"vs current {d['current_price']:.0f} ₽ "
              f"({d['upside_pct']:+.1f}%)")

    print()


def print_summary(results: list[dict]) -> None:
    groups = {"BUY": 0, "HOLD": 0, "AVOID": 0, "STRONG_AVOID": 0}
    for v in results:
        groups[v["action"]] = groups.get(v["action"], 0) + 1

    emoji = {"BUY": "🟢", "HOLD": "🟡",
             "AVOID": "🔴", "STRONG_AVOID": "⛔"}

    print()
    print("=" * 60)
    print("  ИТОГ")
    print("=" * 60)
    for action in ["BUY", "HOLD", "AVOID", "STRONG_AVOID"]:
        print(f"  {emoji[action]} {action:<14} {groups.get(action, 0)}")
    print(f"  Всего: {len(results)}")
    print()


def print_grouped(results: list[dict], max_per_group: int = 10) -> None:
    """Печать с группировкой: BUY — все, остальные — топ-N."""
    groups = {"BUY": [], "HOLD": [], "AVOID": [], "STRONG_AVOID": []}
    for v in results:
        groups[v["action"]].append(v)

    emoji = {"BUY": "🟢", "HOLD": "🟡",
             "AVOID": "🔴", "STRONG_AVOID": "⛔"}

    for action in ["BUY", "HOLD", "AVOID", "STRONG_AVOID"]:
        items = groups[action]
        if not items:
            continue

        items_sorted = sorted(items, key=lambda x: -x["score"])

        if action == "BUY":
            shown = items_sorted
            hidden = 0
        else:
            shown = items_sorted[:max_per_group]
            hidden = max(0, len(items_sorted) - max_per_group)

        print()
        print("=" * 60)
        if hidden:
            print(f"{emoji[action]} {action} "
                  f"({len(items)}, показаны топ-{max_per_group})")
        else:
            print(f"{emoji[action]} {action} ({len(items)})")
        print("=" * 60)
        print()

        for v in shown:
            print_verdict(v)

        if hidden:
            print(f"    … ещё {hidden} тикеров\n")


# ============================================================
# 6. CLI
# ============================================================

def check_verdicts(
    tickers: list[str] | None = None,
    from_db: bool = False,
    from_portfolio: bool = False,
    grouped: bool = True,
) -> None:
    Base.metadata.create_all(engine)

    # --- Конкретные тикеры ---
    if tickers:
        tickers = [_normalize_ticker(t) for t in tickers]
        tickers = sorted(set(tickers))

        print()
        print("=" * 60)
        print(f"  ОЦЕНКА АКЦИЙ: {', '.join(tickers)}")
        print("=" * 60)
        print()

        _ensure_fundamentals(tickers)

        results = []
        for t in tickers:
            try:
                v = final_verdict(t, auto_backfill=False)
                results.append(v)
            except Exception as e:
                print(f"❌ {t}: {e}")

        results = _sort_results(results)
        for v in results:
            print_verdict(v)
        print_summary(results)
        return

    # --- Только портфель ---
    if from_portfolio:
        print()
        print("=" * 60)
        print("  ОЦЕНКА АКЦИЙ ПОРТФЕЛЯ")
        print("=" * 60)
        print()

        results = evaluate_stocks_from_portfolio()
        if grouped:
            print_grouped(results)
        else:
            for v in results:
                print_verdict(v)
        print_summary(results)
        return

    # --- Все из БД (по умолчанию) ---
    print()
    print("=" * 60)
    print("  ОЦЕНКА ВСЕХ АКЦИЙ ИЗ БД")
    print("=" * 60)
    print()

    results = evaluate_stocks_from_db()
    if grouped:
        print_grouped(results)
    else:
        for v in results:
            print_verdict(v)
    print_summary(results)


# ============================================================
# Точка входа
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Оценка акций")
    parser.add_argument("command", nargs="?", default=None,
                        help="'check' для оценки акций")
    parser.add_argument("-t", "--ticker", nargs="+", default=None,
                        help="Тикеры (можно несколько)")
    parser.add_argument("--db", action="store_true",
                        help="Все акции из БД")
    parser.add_argument("--portfolio", "-p", action="store_true",
                        help="Только акции из портфеля")
    parser.add_argument("--no-group", action="store_true",
                        help="Не группировать, показывать всё подряд")

    args = parser.parse_args()

    if args.command == "check" or args.ticker or args.portfolio or args.db:
        check_verdicts(
            tickers=args.ticker,
            from_db=args.db or not (args.portfolio or args.ticker),
            from_portfolio=args.portfolio,
            grouped=not args.no_group,
        )
    else:
        from scheduler import main as scheduler_main
        scheduler_main()