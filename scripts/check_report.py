"""Быстрая проверка отчёта на PostgreSQL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import Session, IS_POSTGRES
from database.crud import CrudDB
from database.crud import CashWithdrawalCrud, BalanceAdjustmentCrud
from reports.report import build_detailed_report


def main():
    print(f"БД: {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
    print()

    with Session() as s:
        cash_total = CashWithdrawalCrud(s).total()
        adj_total = BalanceAdjustmentCrud(s).total()
        report = build_detailed_report(
            CrudDB(s),
            cash_withdrawn=cash_total,
            balance_adjustment=adj_total,
        )

    print("=" * 60)
    print("  ФИНАНСОВЫЙ ОТЧЁТ")
    print("=" * 60)
    print(f"  {'Реальный остаток:':<30} {report['Реальный остаток на счету']:>15,.2f} ₽")
    print(f"  {'Свободный остаток:':<30} {report['Свободный остаток (после налогов и взносов)']:>15,.2f} ₽")
    print(f"  {'Поступления:':<30} {report['Поступления (выручка)']:>15,.2f} ₽")
    print(f"  {'Расходы:':<30} {report['Расходы']:>15,.2f} ₽")
    print(f"  {'Корректировка:':<30} {report.get('Корректировка остатка', 0):>15,.2f} ₽")
    print("=" * 60)


if __name__ == '__main__':
    main()