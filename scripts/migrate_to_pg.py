"""
Переносит данные из SQLite (data/operations.db) в PostgreSQL.
Запускать ОДИН РАЗ при переезде.
"""
import logging
import sys
from pathlib import Path

# Дать доступ к корню проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
)
logger = logging.getLogger('migrate')


BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_PATH = BASE_DIR / 'data' / 'operations.db'

# URL PostgreSQL — из .env или хардкод
import os
from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')
PG_URL = os.getenv('DATABASE_URL')

if not PG_URL or not PG_URL.startswith('postgresql'):
    logger.error("DATABASE_URL не указывает на PostgreSQL: %s", PG_URL)
    sys.exit(1)


SQLITE_URL = f'sqlite:///{SQLITE_PATH}'

# Таблицы в порядке зависимостей
TABLES = [
    'counterparty',
    'operations',
    'users',
    'cash_withdrawals',
    'balance_adjustments',
    'invest_operations',
    'portfolio_snapshots',
    'candle_cache',
    'stock_fundamentals',
    'bond_fundamentals',
    'fund_fundamentals',
    'price_factors',
    'accrued_interest_cache',
    'instrument_info',
]


# Поля, которые в SQLite хранятся как INTEGER (0/1),
# а в PostgreSQL должны быть BOOLEAN
BOOLEAN_FIELDS = {
    'users': ['is_banned'],
    'stock_fundamentals': ['has_anomaly'],
    'bond_fundamentals': ['has_covenants', 'has_offer', 'has_guarantor'],
    'instrument_info': ['ocf_positive'],
}

# Поля-даты: SQLite хранит как строку — надо распарсить в datetime
DATETIME_FIELDS = {
    'operations': ['date'],
    'users': ['added_at', 'last_seen'],
    'cash_withdrawals': ['created_at'],
    'balance_adjustments': ['created_at'],
    'invest_operations': ['date'],
    'portfolio_snapshots': ['date', 'calculated_at'],
    'candle_cache': ['date'],
    'stock_fundamentals': ['updated_at'],
    'bond_fundamentals': ['updated_at'],
    'fund_fundamentals': ['updated_at'],
    'price_factors': ['calculated_at'],
    'accrued_interest_cache': ['date', 'updated_at'],
    'instrument_info': ['updated_at'],
}

# Поля JSON: SQLite хранит как строку — надо распарсить
JSON_FIELDS = {
    'stock_fundamentals': ['extra_metrics', 'anomaly_flags'],
}


def main():
    logger.info("SQLite: %s", SQLITE_URL)
    logger.info("PostgreSQL: %s", PG_URL.split('@')[-1])

    sqlite_engine = create_engine(SQLITE_URL)
    pg_engine = create_engine(PG_URL)

    SqlSession = sessionmaker(bind=sqlite_engine)
    PgSession = sessionmaker(bind=pg_engine)

    from database.db import Base
    Base.metadata.create_all(pg_engine)
    logger.info("Схема в PostgreSQL создана")

    import json
    from datetime import datetime

    with SqlSession() as src, PgSession() as dst:
        for table in TABLES:
            try:
                cols_info = src.execute(
                    text(f"PRAGMA table_info({table})")
                ).fetchall()
                if not cols_info:
                    logger.warning("Таблица %s не найдена в SQLite", table)
                    continue

                col_names = [c[1] for c in cols_info]

                rows = src.execute(text(f"SELECT * FROM {table}")).fetchall()
                if not rows:
                    logger.info("%s: пустая", table)
                    continue

                placeholders = ', '.join([f':{c}' for c in col_names])
                cols_sql = ', '.join(col_names)
                insert_sql = text(
                    f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
                    f"ON CONFLICT DO NOTHING"
                )

                inserted = 0
                skipped = 0

                for row in rows:
                    data = dict(zip(col_names, row))

                    # --- boolean: 0/1 → False/True ---
                    for bf in BOOLEAN_FIELDS.get(table, []):
                        if bf in data and data[bf] is not None:
                            data[bf] = bool(data[bf])

                    # --- datetime: строка → datetime ---
                    for df in DATETIME_FIELDS.get(table, []):
                        if df in data and isinstance(data[df], str):
                            try:
                                data[df] = datetime.fromisoformat(data[df])
                            except (ValueError, TypeError):
                                data[df] = None

                    # --- JSON: строка → dict ---
                    for jf in JSON_FIELDS.get(table, []):
                        if jf in data and isinstance(data[jf], str):
                            try:
                                data[jf] = json.loads(data[jf])
                            except (ValueError, TypeError):
                                data[jf] = None

                    try:
                        dst.execute(insert_sql, data)
                        inserted += 1
                    except Exception as e:
                        logger.warning(
                            "Ошибка в %s: %s (данные: %s)",
                            table, e, str(data)[:200],
                        )
                        dst.rollback()
                        skipped += 1

                dst.commit()
                logger.info("%s: перенесено %d/%d (ошибок: %d)",
                            table, inserted, len(rows), skipped)

            except Exception as e:
                logger.error("Ошибка при переносе %s: %s", table, e)
                dst.rollback()

    logger.info("Готово!")


if __name__ == '__main__':
    main()