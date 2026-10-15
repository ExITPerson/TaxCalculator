import sys

from database.crud import CrudDB
from database.db import Session
from reports.interface import print_detailed_report, print_category_turnover, \
    print_counterparty_turnover
from reports.report import build_detailed_report, counterparty_detailed_report
from sync.operations import sync_operations


# def main():
#     sync_operations()
#     with Session() as session:
#         crud = CrudDB(session)
#         report = build_detailed_report(crud)
#         report_counterparty = counterparty_detailed_report(crud)
#         categories = crud.get_sums_by_category()
#
#         if report.get('Налог за поступления', 0) == 0:
#             print("\n[!] Налог = 0. Проверь период выписки и категорию 'Поступление'.\n",
#                   file=sys.stderr)
#
#     print_detailed_report(report)
#     print_counterparty_turnover(report_counterparty)
#     print_category_turnover(categories)

def main():
    with Session() as session:
        crud = CrudDB(session)
        report = build_detailed_report(crud)

        return report

# def main():
#     from invest.date_windows import split_period
#
#     windows = split_period('2026-01-01', '2026-03-15')
#     for f, t in windows:
#         print(f, '->', t)
if __name__ == '__main__':
    main()