import logging

from database.db import engine, Base, Session
import database.db  # noqa: F401
from database.crud import InvestCrud
from database.instrument_crud import InstrumentCrud
from invest.client import TInvestClient
from invest.instrument_client import TInvestInstrumentClient
from invest.parser import parse_operations

logger = logging.getLogger(__name__)


def _fetch_tickers(figis: list[str]) -> dict:
    """Запрашивает тикеры через GetInstrumentBy для всех FIGI."""
    tickers = {}

    if not figis:
        return tickers

    with Session() as session:
        instr_crud = InstrumentCrud(session)

        with TInvestInstrumentClient() as client:
            for figi in figis:
                # Кэш
                if not instr_crud.is_stale(figi):
                    info = instr_crud.get(figi)
                    if info and info.ticker:
                        tickers[figi] = info.ticker
                        continue

                # Запрос
                data = client.fetch_instrument(figi)
                if data:
                    instr_crud.upsert(
                        figi,
                        ticker=data.get('ticker'),
                        name=data.get('name'),
                        instrument_type=data.get('instrument_type'),
                        sector=data.get('sector'),
                        instrument_uid=data.get('instrument_uid'),  # ← НОВОЕ
                    )
                    if data.get('ticker'):
                        tickers[figi] = data['ticker']

    return tickers


def sync_invest_operations() -> dict:
    """Синхронизирует операции + подтягивает тикеры."""
    Base.metadata.create_all(engine)

    with TInvestClient() as client:
        raw_ops = client.fetch_operations()

    if not raw_ops:
        logger.warning("T-Invest: 0 операций")
        return {'added': 0, 'skipped': 0, 'duplicates': 0, 'error': 'Нет данных'}

    operations = parse_operations(raw_ops)
    logger.info("Распарсено операций: %d", len(operations))

    # Собираем уникальные FIGI
    figis = sorted({op.figi for op in operations if hasattr(op, 'figi') and op.figi})
    logger.info("Уникальных FIGI: %d", len(figis))

    # Подтягиваем тикеры
    tickers = _fetch_tickers(figis)
    logger.info("Получено тикеров: %d", len(tickers))

    with Session() as session:
        stats = InvestCrud(session).save_operations(operations, tickers=tickers)

    # Snapshots
    try:
        from invest.backfill import backfill_incremental
        stats['snapshots'] = backfill_incremental()
    except Exception as e:
        logger.error("Ошибка backfill snapshots: %s", e)
        stats['snapshots'] = {'error': str(e)}

    logger.info("Синк завершён: %s", stats)
    return stats