import telebot
from telebot import apihelper

from config.settings import TELEGRAM_TOKEN


# ВАЖНО: включаем middleware ДО создания бота
apihelper.ENABLE_MIDDLEWARE = True


bot = telebot.TeleBot(TELEGRAM_TOKEN)