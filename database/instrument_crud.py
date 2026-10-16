"""CRUD для кэша информации об инструментах."""
from datetime import datetime, timedelta

from database.db import InstrumentInfoDB


class InstrumentCrud:
    def __init__(self, session):
        self.__session = session

    def upsert(
            self,
            figi: str,
            ticker: str = None,
            name: str = None,
            instrument_type: str = None,
            sector: str = None,
            instrument_uid: str = None,
            isin: str = None,
            credit_rating: str = None,
            net_debt_ebitda: float = None,
            interest_coverage: float = None,
            ocf_positive: bool = None,
    ) -> None:
        """
        Вставляет или обновляет запись об инструменте.

        Обновляет только те поля, которые переданы (не None).

        :param figi: FIGI инструмента (первичный ключ)
        :param ticker: торговый код (может совпадать с ISIN для облигаций)
        :param name: название инструмента
        :param instrument_type: 'share' | 'bond' | 'etf'
        :param sector: сектор
        :param instrument_uid: UID в T-Invest API
        :param isin: ISIN облигации (например, RU000A10EJR5)
        :param credit_rating: кредитный рейтинг (AAA, AA+, ..., BB+)
        :param net_debt_ebitda: Чистый долг / EBITDA
        :param interest_coverage: EBITDA / Проценты
        :param ocf_positive: OCF > 0 (True/False)
        """
        from datetime import datetime

        existing = (
            self.__session.query(InstrumentInfoDB)
            .filter_by(figi=figi)
            .first()
        )

        if existing:
            # Обновляем только переданные значения
            if ticker is not None:
                existing.ticker = ticker
            if name is not None:
                existing.name = name
            if instrument_type is not None:
                existing.instrument_type = instrument_type
            if sector is not None:
                existing.sector = sector
            if instrument_uid is not None:
                existing.instrument_uid = instrument_uid
            if isin is not None:
                existing.isin = isin
            if credit_rating is not None:
                existing.credit_rating = credit_rating
            if net_debt_ebitda is not None:
                existing.net_debt_ebitda = net_debt_ebitda
            if interest_coverage is not None:
                existing.interest_coverage = interest_coverage
            if ocf_positive is not None:
                existing.ocf_positive = ocf_positive

            existing.updated_at = datetime.utcnow()
        else:
            # Создаём новую запись
            self.__session.add(InstrumentInfoDB(
                figi=figi,
                ticker=ticker,
                name=name,
                instrument_type=instrument_type,
                sector=sector,
                instrument_uid=instrument_uid,
                isin=isin,
                credit_rating=credit_rating,
                net_debt_ebitda=net_debt_ebitda,
                interest_coverage=interest_coverage,
                ocf_positive=ocf_positive,
            ))

        self.__session.commit()

    def get(self, figi: str) -> InstrumentInfoDB | None:
        return (
            self.__session.query(InstrumentInfoDB)
            .filter_by(figi=figi)
            .first()
        )

    def get_all(self) -> dict:
        """{figi: InstrumentInfoDB}."""
        rows = self.__session.query(InstrumentInfoDB).all()
        return {r.figi: r for r in rows}

    def is_stale(self, figi: str, ttl_hours: int = 24) -> bool:
        """Проверяет, нужно ли обновить информацию."""
        info = self.get(figi)
        if not info:
            return True
        age = datetime.utcnow() - info.updated_at
        return age > timedelta(hours=ttl_hours)

    def get_by_ticker(self, ticker: str) -> InstrumentInfoDB | None:
        """Ищет инструмент по ticker (ISIN)."""
        return (
            self.__session.query(InstrumentInfoDB)
            .filter(InstrumentInfoDB.ticker == ticker.strip().upper())
            .first()
        )