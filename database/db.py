from datetime import datetime
from enum import Enum
from pathlib import Path
import os

from dotenv import load_dotenv

from sqlalchemy import (
    create_engine, String, Column, Integer, DateTime, Numeric,
    ForeignKey, Index, Boolean, JSON, Date, func, URL
)
from sqlalchemy.orm import sessionmaker, DeclarativeBaseNoMeta, relationship


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class Role(str, Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


ROLE_LEVEL = {
    Role.USER: 0,
    Role.MODERATOR: 10,
    Role.ADMIN: 100,
}


# === БД ===
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    f'sqlite:///{BASE_DIR / "data" / "operations.db"}',
)
IS_POSTGRES = DATABASE_URL.startswith('postgresql')
#
# if IS_POSTGRES:
#     engine = create_engine(
#         DATABASE_URL,
#         echo=False,
#         pool_size=10,
#         max_overflow=20,
#         pool_pre_ping=True,
#         connect_args={"connect_timeout": 10},
#     )
# else:
#     DB_DIR = BASE_DIR / "data"
#     DB_DIR.mkdir(exist_ok=True)
#     engine = create_engine(
#         DATABASE_URL,
#         echo=False,
#         connect_args={"check_same_thread": False, "timeout": 10},
#     )

url = URL.create(
    drivername="postgresql+psycopg",  # Обратите внимание на регистр, не должно быть пробелов
    username="baranovs11",
    password="mongol222",  # Если в пароле есть специальные символы, URL.create автоматически закодирует их
    host="amvera-baranovs11-cnpg-taxcalculator-rw",  # Используйте полное доменное имя, подтверждённое ранее
    port=5432,
    database="taxcal"
)

engine = create_engine(url)

Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBaseNoMeta):
    pass


class CounterpartyDB(Base):
    __tablename__ = 'counterparty'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    inn = Column(String, index=True)
    kpp = Column(String)
    account = Column(String)
    corr_account = Column(String)
    bic = Column(String)
    bank = Column(String)

    operations = relationship("OperationsDB", back_populates="counterparty")


class OperationsDB(Base):
    __tablename__ = 'operations'

    operation_id = Column(String, primary_key=True)
    date = Column(DateTime, index=True)
    amount = Column(Numeric(precision=13, scale=2))
    category = Column(String, index=True)
    direction = Column(String)
    description = Column(String)
    merchant = Column(String, nullable=True)

    counterparty_id = Column(Integer, ForeignKey('counterparty.id'), nullable=True, index=True)
    counterparty = relationship("CounterpartyDB", back_populates="operations")


Index('ix_operations_category_direction', OperationsDB.category, OperationsDB.direction)


class UserDB(Base):
    __tablename__ = 'users'

    user_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    role = Column(String, default=Role.USER.value, index=True)
    is_banned = Column(Boolean, default=False, index=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)


class CashWithdrawalDB(Base):
    __tablename__ = 'cash_withdrawals'

    id = Column(Integer, primary_key=True, autoincrement=True)
    amount = Column(Numeric(precision=13, scale=2), nullable=False)
    comment = Column(String, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class BalanceAdjustmentDB(Base):
    __tablename__ = 'balance_adjustments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    amount = Column(Numeric(15, 2), nullable=False)
    comment = Column(String, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class InvestOperationDB(Base):
    __tablename__ = 'invest_operations'

    id = Column(String, primary_key=True)
    account_id = Column(String, primary_key=True)
    parent_id = Column(String, nullable=True)
    date = Column(DateTime, index=True)
    kind = Column(String, index=True)
    raw_type = Column(String)
    operation_type = Column(String)
    state = Column(String)
    payment_amount = Column(Numeric(15, 2))
    payment_currency = Column(String, default='rub')
    figi = Column(String, nullable=True, index=True)
    ticker = Column(String, nullable=True, index=True)
    instrument_uid = Column(String, nullable=True)
    instrument_type = Column(String, nullable=True)
    quantity = Column(Numeric(15, 6), nullable=True)
    price_per_unit = Column(Numeric(15, 6), nullable=True)


Index('ix_invest_ops_account_date', InvestOperationDB.account_id, InvestOperationDB.date)
Index('ix_invest_ops_figi_kind', InvestOperationDB.figi, InvestOperationDB.kind)


class PortfolioSnapshotDB(Base):
    __tablename__ = 'portfolio_snapshots'

    date = Column(DateTime, primary_key=True)
    account_id = Column(String, primary_key=True, default='all')
    total_value = Column(Numeric(18, 2), default=0)
    paper_value = Column(Numeric(18, 2), default=0)
    cash_value = Column(Numeric(18, 2), default=0)
    external_flow = Column(Numeric(18, 2), default=0)
    index_value = Column(Numeric(18, 6), default=100)
    pnl_value = Column(Numeric(18, 2), default=0)
    positions_count = Column(Integer, default=0)
    calculated_at = Column(DateTime, default=datetime.utcnow)


Index('ix_snapshots_date', PortfolioSnapshotDB.date)


class CandleCacheDB(Base):
    __tablename__ = 'candle_cache'

    figi = Column(String, primary_key=True)
    date = Column(DateTime, primary_key=True)
    close_price = Column(Numeric(15, 6), nullable=False)


class StockFundamentalsDB(Base):
    __tablename__ = 'stock_fundamentals'

    ticker = Column(String, primary_key=True)
    year = Column(Integer, primary_key=True)

    revenue = Column(Numeric(18, 2), nullable=True)
    ebitda = Column(Numeric(18, 2), nullable=True)
    net_profit = Column(Numeric(18, 2), nullable=True)
    fcf = Column(Numeric(18, 2), nullable=True)

    roe = Column(Numeric(10, 4), nullable=True)
    roa = Column(Numeric(10, 4), nullable=True)
    roic = Column(Numeric(10, 4), nullable=True)

    debt_to_ebitda = Column(Numeric(10, 4), nullable=True)
    payout_ratio = Column(Numeric(10, 4), nullable=True)

    net_operating_income = Column(Numeric(18, 2), nullable=True)
    net_interest_income = Column(Numeric(18, 2), nullable=True)
    net_fee_income = Column(Numeric(18, 2), nullable=True)

    extra_metrics = Column(JSON, nullable=True)

    has_anomaly = Column(Boolean, default=False, index=True)
    anomaly_flags = Column(JSON, nullable=True)

    source = Column(String, default='smartlab')
    updated_at = Column(DateTime, default=datetime.utcnow)


Index('ix_stock_fundamentals_ticker_year',
      StockFundamentalsDB.ticker, StockFundamentalsDB.year)


class BondFundamentalsDB(Base):
    __tablename__ = 'bond_fundamentals'

    isin = Column(String, primary_key=True)
    figi = Column(String, index=True)
    rating = Column(String, nullable=True)
    rating_agency = Column(String, nullable=True)
    debt_ebitda = Column(Numeric(10, 4), nullable=True)
    interest_coverage = Column(Numeric(10, 4), nullable=True)
    duration = Column(Numeric(10, 4), nullable=True)
    ytm = Column(Numeric(10, 4), nullable=True)
    ytm_to_offer = Column(Numeric(10, 4), nullable=True)
    spread_to_ofz_bp = Column(Numeric(10, 2), nullable=True)
    has_covenants = Column(Boolean, default=False)
    has_offer = Column(Boolean, default=False)
    has_guarantor = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class FundFundamentalsDB(Base):
    __tablename__ = 'fund_fundamentals'

    figi = Column(String, primary_key=True)
    ticker = Column(String, index=True)
    ter = Column(Numeric(10, 4), nullable=True)
    tracking_error = Column(Numeric(10, 4), nullable=True)
    tracking_difference = Column(Numeric(10, 4), nullable=True)
    avg_daily_volume = Column(Numeric(18, 2), nullable=True)
    bid_ask_spread = Column(Numeric(10, 4), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class PriceFactorDB(Base):
    __tablename__ = 'price_factors'
    figi = Column(String, primary_key=True)
    factor = Column(Numeric(18, 6))
    calculated_at = Column(DateTime, default=datetime.utcnow)


class AccruedInterestCacheDB(Base):
    __tablename__ = 'accrued_interest_cache'

    figi = Column(String, primary_key=True)
    date = Column(DateTime, primary_key=True)
    value = Column(Numeric(18, 6), nullable=False)
    nominal = Column(Numeric(18, 2), nullable=True)
    value_percent = Column(Numeric(10, 4), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class InstrumentInfoDB(Base):
    __tablename__ = 'instrument_info'

    figi = Column(String, primary_key=True)
    instrument_uid = Column(String, nullable=True, index=True)
    ticker = Column(String, nullable=True)
    isin = Column(String, nullable=True, index=True)
    name = Column(String, nullable=True)
    instrument_type = Column(String, nullable=True)
    sector = Column(String, nullable=True)

    credit_rating = Column(String, nullable=True)
    net_debt_ebitda = Column(Numeric(10, 2), nullable=True)
    interest_coverage = Column(Numeric(10, 2), nullable=True)
    ocf_positive = Column(Boolean, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# Универсальные SQL-функции для дат (SQLite + PostgreSQL)
# ============================================================

def month_expr(col):
    """Год-месяц в формате 'YYYY-MM'."""
    if IS_POSTGRES:
        return func.to_char(col, 'YYYY-MM')
    return func.strftime('%Y-%m', col)


def day_expr(col):
    """День без времени (Date)."""
    if IS_POSTGRES:
        return func.date_trunc('day', col).cast(Date)
    return func.date(col)