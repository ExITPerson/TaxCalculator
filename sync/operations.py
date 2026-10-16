import logging

from clients.hookup import TBankAPI
from database.crud import CrudDB
from database.db import engine, Base, Session

logger = logging.getLogger(__name__)


def sync_operations() -> dict:
    """
    Получает операции из API Т-Банка, классифицирует и сохраняет в БД.
    """
    Base.metadata.create_all(engine)

    with TBankAPI() as api:
        operations = list(api.get_operations())

    if not operations:
        logger.warning("API вернул 0 операций")
        return {"added_ops": 0, "skipped_ops": 0, "added_cp": 0, "updated_cp": 0,
                "error": "Нет данных от API"}

    with Session() as session:
        crud = CrudDB(session)
        stats = crud.save_operations(operations)

    logger.info("Синхронизация завершена: %s", stats)
    return stats