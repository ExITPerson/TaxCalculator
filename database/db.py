from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, String, Column, Integer, DATETIME, Numeric, ForeignKey
from sqlalchemy.orm import sessionmaker, DeclarativeBaseNoMeta, relationship

DB_DIR = Path('data')
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / 'operations.db'

engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Session = sessionmaker(bind=engine)

class Base(DeclarativeBaseNoMeta):
    pass

class CounterpartyDB(Base):
    """ Структура таблицы контрагентов """
    __tablename__ = 'counterparty'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String)
    inn: str = Column(String)
    kpp: str = Column(String)
    account: str = Column(String)
    corr_account: str = Column(String)
    bic: str = Column(String)
    bank: str = Column(String)

    operations = relationship("OperationsDB", back_populates="counterparty")

class OperationsDB(Base):
    """ Структура таблицы операций """
    __tablename__ = 'operations'

    operation_id: str = Column(String, primary_key=True)
    date: datetime = Column(DATETIME)
    amount: float = Column(Numeric(precision=13, scale=2))
    category: str = Column(String)
    direction: str = Column(String)  # "IN" / "OUT" / "INTERNAL"
    description: str = Column(String)
    merchant: str | None =  Column(String, nullable=True)

    counterparty_id = Column(Integer, ForeignKey('counterparty.id'), nullable=True)
    counterparty = relationship("CounterpartyDB", back_populates="operations")
