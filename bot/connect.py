import logging
import os
import sys

from telebot.handler_backends import SkipHandler

# Страховка: если файл всё-таки запустят как bot/connect.py,
# корень проекта попадёт в sys.path.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot.instance import bot_tg
from database.db import Session, engine, Base
from database.crud import UserCrud
import database.db  # noqa: F401  — регистрирует все модели в Base.metadata


# --- Логирование: stdout + файл рядом с проектом (не в CWD) ---
LOG_PATH = os.path.join(project_root, "bot.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot_tg")
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("telebot").setLevel(logging.WARNING)


# --- Создаём таблицы (users, counterparty, operations) ---
try:
    Base.metadata.create_all(engine)
    logger.info("DB schema OK")
except Exception:
    logger.exception("DB init failed")
    raise


# --- Middleware: автосоздание пользователя + проверка бана ---
@bot_tg.middleware_handler(update_types=["message"])
def track_user(bot_instance, message):
    if not message.from_user:
        return
    u = message.from_user
    full_name = f"{u.first_name or ''} {u.last_name or ''}".strip()
    with Session() as session:
        crud = UserCrud(session)
        crud.get_or_create(u.id, u.username or "", full_name)
        if crud.is_banned(u.id):
            bot_tg.send_message(message.chat.id, "🚫 Вы забанены.")
            raise SkipHandler()


# --- Хендлеры (регистрируются на bot_tg при импорте) ---
from bot.handlers import common, moderator, admin, invest  # noqa: E402, F401


if __name__ == "__main__":
    logger.info("Бот запущен")
    bot_tg.infinity_polling()