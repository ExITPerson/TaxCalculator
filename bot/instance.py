import os

import telebot
from telebot import apihelper

from config.settings import TELEGRAM_TOKEN


# ВАЖНО: включаем middleware ДО создания бота
apihelper.ENABLE_MIDDLEWARE = True


# === Прокси для Telegram — ТОЛЬКО по явному флагу TELEGRAM_USE_PROXY=1 ===
# В Amvera прокси обычно не нужен. Случайно заданный HTTPS_PROXY
# в окружении не должен ломать polling.
USE_PROXY = os.getenv("TELEGRAM_USE_PROXY", "").strip() in ("1", "true", "yes")
proxy_url = os.getenv("TELEGRAM_PROXY_URL", "").strip()

if USE_PROXY and proxy_url:
    apihelper.proxy = {
        "http": proxy_url,
        "https": proxy_url,
    }
    print(f"[bot_tg] Using proxy for Telegram: {proxy_url}")
else:
    print("[bot_tg] No proxy configured, connecting directly")


bot_tg = telebot.TeleBot(TELEGRAM_TOKEN)