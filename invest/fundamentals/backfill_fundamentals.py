"""Backfill фундаментала по всем тикерам из портфеля.

Логика:
1. Собрать FIGI из InvestOperationDB (только buy/sell).
2. Через InstrumentCrud получить тикеры.
3. Отфильтровать уникальные тикеры.
4. Прогнать парсер Smart-Lab.
5. Сохранить в StockFundamentalsDB.
"""
import logging
import time
from datetime import datetime

from sqlalchemy import func

from database.db import Session, InvestOperationDB, Base, engine
from database.fundamentals_crud import StockFundamentalsCrud
from database.instrument_crud import InstrumentCrud
from invest.fundamentals.smartlab_parser import (
    fetch_stock_fundamentals,
    _normalize_ticker,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 1. Сбор тикеров из портфеля
# ------------------------------------------------------------

def collect_portfolio_tickers() -> list[str]:
    """
    Возвращает уникальные тикеры из InvestOperationDB.

    Логика:
    - берём FIGI из сделок buy/sell,
    - смотрим в InstrumentInfoDB, чтобы получить тикер,
    - нормализуем (SNGSP → SNGS, YNDX → YDEX и т.д.),
    - возвращаем уникальный отсортированный список.
    """
    with Session() as s:
        # FIGI из сделок
        rows = (
            s.query(InvestOperationDB.figi)
            .filter(
                InvestOperationDB.kind.in_(['buy', 'sell']),
                InvestOperationDB.figi.isnot(None),
            )
            .distinct()
            .all()
        )
        figis = [r[0] for r in rows if r[0]]

        if not figis:
            logger.warning("В InvestOperationDB нет сделок buy/sell")
            return []

        # Получаем тикеры из кэша InstrumentInfoDB
        instr_crud = InstrumentCrud(s)
        tickers: set[str] = set()

        for figi in figis:
            info = instr_crud.get(figi)
            if info and info.ticker:
                tickers.add(_normalize_ticker(info.ticker))

        # Если для части FIGI нет тикера — подтягиваем через API
        missing_figis = [
            f for f in figis
            if not instr_crud.get(f) or not instr_crud.get(f).ticker
        ]

    if missing_figis:
        logger.info("Подтягиваем %d тикеров через API...", len(missing_figis))
        try:
            from invest.sync import _fetch_tickers
            fetched = _fetch_tickers(missing_figis)
            for t in fetched.values():
                if t:
                    tickers.add(_normalize_ticker(t))
        except Exception as e:
            logger.error("Не удалось подтянуть тикеры: %s", e)

    result = sorted(tickers)
    logger.info("Собрано %d уникальных тикеров", len(result))
    return result


# ------------------------------------------------------------
# 2. Backfill
# ------------------------------------------------------------

def backfill_portfolio_fundamentals(
    force: bool = False,
    delay: float = 1.0,
    only_tickers: list[str] | None = None,
    create_tables: bool = True,
) -> dict:
    if create_tables:
        Base.metadata.create_all(engine)
        logger.info("Таблицы проверены/созданы")

    if only_tickers is not None:
        tickers = [_normalize_ticker(t) for t in only_tickers]
    else:
        # НОВОЕ: если БД пуста — collect_portfolio_tickers упадёт,
        # ловим и возвращаем пустой результат
        try:
            tickers = collect_portfolio_tickers()
        except Exception as e:
            logger.error("Не удалось собрать тикеры из портфеля: %s", e)
            return {
                'tickers': 0, 'rows': 0, 'errors': 0, 'skipped': 0,
                'error': str(e),
            }

    if not tickers:
        return {'tickers': 0, 'rows': 0, 'errors': 0, 'skipped': 0}

    stats = {
        'tickers': 0,
        'rows': 0,
        'errors': 0,
        'skipped': 0,
        'started_at': datetime.utcnow().isoformat(),
    }

    with Session() as s:
        crud = StockFundamentalsCrud(s)

        for i, ticker in enumerate(tickers, 1):
            if not force and not crud.is_stale(ticker):
                logger.info("[%d/%d] %s: свежие данные, пропуск",
                            i, len(tickers), ticker)
                stats['skipped'] += 1
                continue

            logger.info("[%d/%d] %s: парсим...", i, len(tickers), ticker)
            data = fetch_stock_fundamentals(ticker)

            if not data:
                logger.warning("[%d/%d] %s: НЕ НАЙДЕНО",
                               i, len(tickers), ticker)
                stats['errors'] += 1
                continue

            years_saved = 0
            for year, metrics in data.items():
                crud.upsert(ticker, year, **metrics)
                years_saved += 1

            logger.info("[%d/%d] %s: сохранено %d лет",
                        i, len(tickers), ticker, years_saved)
            stats['tickers'] += 1
            stats['rows'] += years_saved

            time.sleep(delay)

    stats['finished_at'] = datetime.utcnow().isoformat()
    logger.info("Backfill завершён: %s", stats)
    return stats


# ------------------------------------------------------------
# 3. Диагностика
# ------------------------------------------------------------

def print_fundamentals_summary() -> None:
    """Печатает сводку по тому, что уже лежит в БД."""
    with Session() as s:
        crud = StockFundamentalsCrud(s)
        tickers = crud.get_all_tickers()

        print(f"\n=== Фундаментал в БД ===")
        print(f"Тикеров: {len(tickers)}")
        print(f"Записей: {crud.count()}\n")

        for ticker in sorted(tickers):
            history = crud.get_history(ticker, years=10)
            if not history:
                continue

            latest = history[0]
            years = sorted([h.year for h in history])

            flags = []
            if latest.anomaly_flags:
                flags = list(latest.anomaly_flags.keys())

            flag_str = f"  ⚠️ {', '.join(flags)}" if flags else ""
            print(f"  {ticker}: {len(history)} лет {years}, "
                  f"latest={latest.year}, "
                  f"rev={latest.revenue}, "
                  f"ebitda={latest.ebitda}, "
                  f"NP={latest.net_profit}{flag_str}")


# ------------------------------------------------------------
# 4. Точка входа для ручного запуска
# ------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    parser = argparse.ArgumentParser(description="Backfill фундаментала Smart-Lab")
    parser.add_argument('--force', action='store_true',
                        help='Игнорировать кэш, обновлять всегда')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Пауза между запросами (сек)')
    parser.add_argument('--tickers', nargs='*', default=None,
                        help='Только эти тикеры (если не задано — все из портфеля)')
    parser.add_argument('--summary', action='store_true',
                        help='Только показать сводку из БД')
    args = parser.parse_args()

    if args.summary:
        print_fundamentals_summary()
    else:
        result = backfill_portfolio_fundamentals(
            force=args.force,
            delay=args.delay,
            only_tickers=args.tickers,
        )
        print("\n=== Результат ===")
        for k, v in result.items():
            print(f"  {k}: {v}")