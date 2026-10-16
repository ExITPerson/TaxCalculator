import os
import telebot
from telebot import apihelper

from config.settings import TELEGRAM_TOKEN


# ВАЖНО: включаем middleware ДО создания бота
apihelper.ENABLE_MIDDLEWARE = True


# === Прокси для Telegram (только для api.telegram.org) ===
proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('SOCKS_PROXY')

if proxy_url:
    # Telebot понимает socks5://user:pass@host:port
    apihelper.proxy = {
        'http': proxy_url,
        'https': proxy_url,
    }
    print(f"[bot] Using proxy for Telegram: {proxy_url}")
else:
    print("[bot] No proxy configured, connecting directly")


bot = telebot.TeleBot(TELEGRAM_TOKEN)