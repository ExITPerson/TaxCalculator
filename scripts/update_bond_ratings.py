"""Ручной ввод рейтингов и метрик эмитента для облигаций без рейтинга.

Работает по ВСЕЙ БД (instrument_info), а не только по текущему портфелю.
Показывает только те, у которых credit_rating ещё не заполнен.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import Session, InstrumentInfoDB


logging.basicConfig(level=logging.WARNING)


def _input_float(prompt: str) -> float | None:
    val = input(prompt).strip().replace(",", ".")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        print("   Не число, пропускаем")
        return None


def main():
    with Session() as s:
        # Все облигации из БД без рейтинга
        bonds = (
            s.query(InstrumentInfoDB)
            .filter(InstrumentInfoDB.instrument_type == 'bond')
            .filter(
                (InstrumentInfoDB.credit_rating.is_(None))
                | (InstrumentInfoDB.credit_rating == '')
            )
            .all()
        )

        total_bonds = (
            s.query(InstrumentInfoDB)
            .filter(InstrumentInfoDB.instrument_type == 'bond')
            .count()
        )

        print(f"Всего облигаций в БД: {total_bonds}")
        print(f"Без рейтинга:         {len(bonds)}")
        print()

        if not bonds:
            print("Все рейтинги заполнены!")
            return

        print("Вводим рейтинг и метрики.")
        print("Формат: AAA, AA+, AA, AA-, A+, A, A-, BBB+, BBB, ...")
        print("Метрики: число (2.5) или Enter — пропустить.")
        print("OCF: y/n или Enter — пропустить.")
        print("Пустой рейтинг — пропустить облигацию.")
        print()

        for i, info in enumerate(bonds, 1):
            ticker = info.ticker or info.figi[:15]
            name = info.name or '—'

            print(f"[{i}/{len(bonds)}] {ticker} — {name}")

            rating = input("   Рейтинг: ").strip().upper()
            if not rating:
                print()
                continue

            info.credit_rating = rating

            d2e = _input_float("   Долг/EBITDA: ")
            if d2e is not None:
                info.net_debt_ebitda = d2e

            ic = _input_float("   Покрытие процентов: ")
            if ic is not None:
                info.interest_coverage = ic

            ocf = input("   OCF > 0? (y/n): ").strip().lower()
            if ocf in ('y', 'n'):
                info.ocf_positive = (ocf == 'y')

            s.commit()
            print()

        print("Готово!")


if __name__ == "__main__":
    main()