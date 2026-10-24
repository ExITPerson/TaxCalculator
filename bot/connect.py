# connect.py
import logging
import os
import sys
import time
import threading
from datetime import datetime

import schedule

from telebot.handler_backends import SkipHandler

# Страховка: если файл всё-таки запустят как bot/connect.py,
# корень проекта попадёт в sys.path.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot.instance import bot_tg
from database.db import Session, engine, Base
from database.crud import UserCrud
import database.db  # noqa: F401 — регистрирует все модели в Base.metadata

# --- Задачи для планировщика ---
from scripts.daily_digest import send_digest
from scripts.refresh_scores import refresh_all

# --- Логирование: stdout + файл ---
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

# --- Создаём таблицы ---
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


# --- Хендлеры ---
from bot.handlers import common, moderator, admin, invest, assets  # noqa: E402, F401


# ============================================================
# ПЛАНИРОВЩИК ЗАДАЧ (Фоновый поток)
# ============================================================
def run_scheduler():
    """Фоновый поток для выполнения задач по расписанию."""
    logger.info("Планировщик задач запущен")

    # ВАЖНО: Время в schedule указывается в часовом поясе сервера (обычно UTC).
    # 06:00 UTC = 09:00 МСК
    schedule.every().day.at("06:00").do(send_digest)

    # 00:00 UTC = 03:00 МСК (обновление оценок, пока вы спите)
    schedule.every().day.at("00:00").do(refresh_all)

    # (Опционально) Можно добавить тестовое время, чтобы проверить работу:
    # schedule.every().day.at("12:30").do(send_digest)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}", exc_info=True)
        time.sleep(60)  # Проверяем расписание раз в минуту


# ============================================================
# ЗАПУСК БОТА
# ============================================================
if __name__ == "__main__":
    logger.info("Бот запущен")

    # Запускаем планировщик в фоне
    # daemon=True означает, что поток завершится вместе с основным процессом
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Пауза, чтобы старый процесс успел умереть (защита от 409)
    time.sleep(3)

    # Запускаем бота
    bot_tg.infinity_polling()