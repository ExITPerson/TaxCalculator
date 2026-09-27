from clients.hookup import TBankAPI
from database.crud import CrudDB
from database.db import engine, Base, Session


def sync_operations() -> dict:
    """
    Получает операции из API Т-Банка, классифицирует и сохраняет в БД.
    Сессия закрывается автоматически через контекстный менеджер.
    """

    Base.metadata.create_all(engine)

    api = TBankAPI()
    operations = api.get_operations()

    if not operations:
        return {"added_ops": 0, "skipped_ops": 0, "added_cp": 0, "updated_cp": 0, "error": "Нет данных от API"}

    with Session() as session:
        crud = CrudDB(session)
        stats = crud.save_operations(operations)

    return stats
