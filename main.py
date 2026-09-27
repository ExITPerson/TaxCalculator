from clients.hookup import TBankAPI
from database.crud import CrudDB
from database.db import Session
from sync.operations import sync_operations
from taxes.calculator import Taxes

if __name__ == '__main__':
    result = sync_operations()
    # print(result)
    with Session() as session:
        summ_category = CrudDB(session).get_sums_by_category()
        print(summ_category)

        for op in summ_category:
            if op['category'] == 'Поступление':
                revenue = op['total']

            elif op['category'] == 'Выплата ЗП':
                salary = op['total']

            elif op['category'] == 'Доход от депозита':
                revenue_overnight = op['total']

        print(Taxes().get_full_report(revenue, salary, revenue_overnight))

    # print(TBankAPI()._connect())