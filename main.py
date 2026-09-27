from clients.hookup import TBankAPI
from database.crud import CrudDB
from database.db import Session
from sync.operations import sync_operations

if __name__ == '__main__':
    result = sync_operations()
    # print(result)
    with Session() as session:
        summ_category = CrudDB(session).get_sums_by_category()
        print(summ_category)

    # print(TBankAPI()._connect())