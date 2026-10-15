"""
Пересборка БД из API Т-Банка + проверка отчёта.

Запуск:  python rebuild_and_check.py
"""

from database.db import Session, engine, Base
from database.crud import CrudDB
from clients.hookup import TBankAPI
from reports.report import build_detailed_report


# === Ожидаемый факт (сумма остатков из приложения Т-Банка) ===
# 40802810800001207791 : 31 567.04
# 40802810300002476212 :  5 558.00
# 42109810500000018733 : 2 665 000.00
FACT_BALANCE = 31_567.04 + 5_558.00 + 2_665_000.00


def rebuild_database() -> None:
    """Удаляет и пересоздаёт таблицы, загружает операции из API."""
    print("=" * 70)
    print("  ПЕРЕСБОРКА БД")
    print("=" * 70)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    print("  Схема пересоздана")

    with Session() as s:
        with TBankAPI() as api:
            ops = list(api.get_operations())
        print(f"  Получено из API: {len(ops)} операций")

        crud = CrudDB(s)
        stats = crud.save_operations(ops)
        print(f"  Сохранено:       {stats}")
    print()


def print_category_sums() -> None:
    """Печатает суммы по категориям."""
    print("=" * 70)
    print("  СУММЫ ПО КАТЕГОРИЯМ")
    print("=" * 70)
    print(f"  {'Категория':<28} {'IN':>16} {'OUT':>16} {'INT':>16}")
    print("  " + "-" * 66)

    with Session() as s:
        crud = CrudDB(s)
        for c in crud.get_sums_by_category():
            print(f"  {c['category']:<28} "
                  f"{c['income']:>16,.2f} "
                  f"{c['expense']:>16,.2f} "
                  f"{c['internal']:>16,.2f}")
    print()


def print_report() -> None:
    """Печатает итоговый отчёт и сверяет с фактом."""
    print("=" * 70)
    print("  ФИНАНСОВЫЙ ОТЧЁТ")
    print("=" * 70)

    with Session() as s:
        crud = CrudDB(s)
        report = build_detailed_report(crud)

    real = report['Реальный остаток на счету']
    free = report['Свободный остаток (после налогов и взносов)']
    income = report['Поступления (выручка)']
    expenses = report['Расходы']

    print(f"  {'Реальный остаток:':<28} {real:>18,.2f}")
    print(f"  {'Свободный остаток:':<28} {free:>18,.2f}")
    print(f"  {'Поступления:':<28} {income:>18,.2f}")
    print(f"  {'Расходы:':<28} {expenses:>18,.2f}")
    print()

    # === Сверка ===
    print("=" * 70)
    print("  СВЕРКА С БАНКОМ")
    print("=" * 70)

    diff = real - FACT_BALANCE
    pct = (diff / FACT_BALANCE * 100) if FACT_BALANCE else 0.0

    print(f"  {'Остаток по отчёту:':<28} {real:>18,.2f}")
    print(f"  {'Остаток по приложению:':<28} {FACT_BALANCE:>18,.2f}")
    print(f"  {'Расхождение:':<28} {diff:>18,.2f}  ({pct:+.2f}%)")
    print()

    if abs(diff) < 50_000:
        print("  ✅ Расхождение в пределах допустимого (комиссии, округления).")
    else:
        print("  ⚠️  Расхождение больше 50 000 ₽ — проверь категории и API-период.")
    print()


if __name__ == '__main__':
    rebuild_database()
    print_category_sums()
    print_report()