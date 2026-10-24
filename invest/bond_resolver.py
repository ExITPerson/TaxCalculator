"""Первичная проверка облигации в БД.

Если облигации нет — тянет данные из T-Invest API и создаёт запись.
"""
import logging

from database.db import Session
from database.instrument_crud import InstrumentCrud
from invest.instrument_client import TInvestInstrumentClient
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
from config.settings import ACCOUNTS_ID


logger = logging.getLogger(__name__)


def ensure_bond_in_db(ticker: str, save: bool = True, force_update: bool = False) -> str | None:
    """
    Убеждается, что облигация есть в БД.
    Если force_update=True или данные устарели — обновляет их из API.
    """
    ticker = ticker.strip().upper()

    # --- 1. Ищем в БД по ticker ---
    with Session() as s:
        crud = InstrumentCrud(s)
        info = crud.get_by_ticker(ticker)

        if info and info.figi:
            # Если данные не устарели — возвращаем сразу
            if not force_update and not crud.is_stale(info.figi, ttl_hours=24):
                logger.debug("Найдено в БД (свежее): %s → %s", ticker, info.figi)
                return info.figi
            else:
                logger.info("Данные %s устарели. Обновляем...", ticker)
                figi = info.figi

    # --- 2. Если обновляем или ищем в портфеле ---
    if not figi:
        figi = _find_figi_in_portfolio(ticker)

    if figi:
        if save:
            data = _fetch_from_tinvest(ticker)
            if data:
                _save_bond(
                    figi=figi,
                    ticker=data.get('ticker') or ticker,
                    name=data.get('name'),
                    instrument_type=data.get('instrument_type'),
                    sector=data.get('sector'),
                    instrument_uid=data.get('instrument_uid'),
                )
        return figi

    # --- 3. Запрашиваем у T-Invest API по ISIN ---
    data = _fetch_from_tinvest(ticker)
    if not data:
        logger.warning("Не удалось найти облигацию %s нигде", ticker)
        return None

    figi = data.get('figi') or ticker
    if save:
        _save_bond(
            figi=figi,
            ticker=data.get('ticker') or ticker,
            name=data.get('name'),
            instrument_type=data.get('instrument_type'),
            sector=data.get('sector'),
            instrument_uid=data.get('instrument_uid'),
        )
    return figi


def _find_figi_in_portfolio(ticker: str) -> str | None:
    """Ищет FIGI в текущем портфеле по тикеру."""
    try:
        with TInvestPortfolioClient() as client:
            for acc in ACCOUNTS_ID:
                raw = client.fetch_portfolio(acc)
                if not raw:
                    continue
                p = parse_portfolio(raw)
                for pos in p['positions']:
                    if (pos.get('ticker') or '').upper() == ticker:
                        return pos['figi']
    except Exception as e:
        logger.warning("Ошибка поиска в портфеле: %s", e)
    return None


def _fetch_from_tinvest(isin: str) -> dict | None:
    """Запрашивает облигацию у T-Invest API по ISIN."""
    try:
        with TInvestInstrumentClient() as client:
            data = client.fetch_bond_by_isin(isin)
            if data:
                return data
    except Exception as e:
        logger.warning("Ошибка T-Invest API для %s: %s", isin, e)
    return None


def _save_bond(figi: str, ticker: str, name: str = None,
               instrument_type: str = None, sector: str = None,
               instrument_uid: str = None, isin: str = None) -> None:
    with Session() as s:
        crud = InstrumentCrud(s)
        info = crud.get(figi)
        crud.upsert(
            figi=figi,
            ticker=ticker,
            name=name,
            instrument_type=instrument_type or 'bond',
            sector=sector,
            instrument_uid=instrument_uid,
        )
        # Дополнительно — isin (если добавили поле)
        if isin:
            info = crud.get(figi)
            if info:
                info.isin = isin
                s.commit()