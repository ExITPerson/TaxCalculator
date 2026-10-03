import sys

from database.crud import CrudDB
from database.db import Session
from reports.interface import print_detailed_report
from reports.report import build_detailed_report
from sync.operations import sync_operations


def main():
    sync_operations()
    with Session() as session:
        crud = CrudDB(session)
        report = build_detailed_report(crud)

        if report.get('Налог за поступления', 0) == 0:
            print("\n[!] Налог = 0. Проверь период выписки и категорию 'Поступление'.\n",
                  file=sys.stderr)

    print_detailed_report(report)
    print(crud.get_sums_by_category())

if __name__ == '__main__':
    main()