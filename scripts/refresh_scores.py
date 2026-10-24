# scripts/refresh_scores.py
import sys
import time
import logging
from pathlib import Path

# Чтобы скрипт видел корень проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import Session
from invest.bond_resolver import ensure_bond_in_db
from database.crud import CachedScoreCrud
from database.instrument_crud import InstrumentCrud
from invest.scoring.final_verdict import final_verdict
from invest.bond_score import evaluate_bond

logger = logging.getLogger('refresh_scores')


def refresh_all():
    logger.info("=== Запуск обновления кэша оценок ===")

    with Session() as s:
        instr_crud = InstrumentCrud(s)
        all_instruments = instr_crud.get_all()

        # Берем уникальные тикеры акций
        stocks = list({info.ticker for info in all_instruments.values()
                       if info.instrument_type == 'share' and info.ticker})

        # Берем FIGI облигаций
        bonds = list({info.figi for info in all_instruments.values()
                      if info.instrument_type == 'bond' and info.ticker})

    logger.info(f"Найдено акций: {len(stocks)}, облигаций: {len(bonds)}")

    with Session() as s:
        cache_crud = CachedScoreCrud(s)

        # 1. Оцениваем акции
        for i, ticker in enumerate(stocks, 1):
            try:
                logger.info(f"[{i}/{len(stocks)}] Оценка акции {ticker}...")
                res = final_verdict(ticker, auto_backfill=False)
                if 'error' not in res and 'score' in res:
                    cache_crud.save(ticker, 'stock', res['score'], res['action'], str(res))
                else:
                    logger.warning(f"Не удалось оценить {ticker}: {res.get('error')}")
            except Exception as e:
                logger.error(f"Ошибка оценки акции {ticker}: {e}")
            time.sleep(1)  # Пауза, чтобы не перегружать API/парсер

        # 2. Оцениваем облигации
        for i, figi in enumerate(bonds, 1):
            try:
                logger.info(f"[{i}/{len(bonds)}] Оценка облигации {figi}...")
                res = evaluate_bond(figi)
                if 'error' not in res:
                    # Для облигаций score не считается, сохраняем вердикт
                    cache_crud.save(res['ticker'], 'bond', 0, res['verdict'], str(res))
            except Exception as e:
                logger.error(f"Ошибка оценки облигации {figi}: {e}")
            time.sleep(1)

    logger.info("=== Обновление кэша оценок завершено ===")

    logger.info("Обновление данных об облигациях (TTL 24ч)...")
    with Session() as s:
        instr_crud = InstrumentCrud(s)
        stale_bonds = instr_crud.get_stale_bonds(ttl_hours=24)

        for i, figi in enumerate(stale_bonds, 1):
            logger.info(f"[{i}/{len(stale_bonds)}] Обновление облигации {figi}...")
            try:
                # force_update=True заставит скрипт сходить в API
                ensure_bond_in_db(figi, save=True, force_update=True)
                time.sleep(1)  # Пауза, чтобы не превысить лимиты API
            except Exception as e:
                logger.error(f"Ошибка обновления облигации {figi}: {e}")