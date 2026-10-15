import json
from pathlib import Path

import certifi
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def _require(name: str) -> str:
    """Читает переменную окружения и падает, если её нет """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return value


BUSINESS_TOKEN = _require('BUSINESS_TOKEN')
BUSINESS_URL = _require('BUSINESS_URL')
MY_INN = _require('MY_INN')
BANK_INN = _require('BANK_INN')

INVEST_TOKEN = _require('INVEST_TOKEN')
INVEST_URL = _require('INVEST_URL')

ACCOUNTS_ID = [
    acc.strip()
    for acc in os.getenv('ACCOUNTS_ID', '').split(',')
    if acc.strip()
]
INVEST_DATE_FROM = os.getenv(
    'INVEST_DATE_FROM',
    (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
)

# дефолт сегодня - 30 дней, DATE_FROM в .env
DATE_FROM = os.getenv('DATE_FROM', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))

RISK_FREE_RATE = float(os.getenv('RISK_FREE_RATE', '0.13'))

def build_invest_payload(account_id: str) -> dict:

    payload = {
        'accountId': account_id,
        'from': (datetime.utcnow() - timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'to': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    if cursor:
        payload['cursor'] = cursor
    return payload

# payload собирается функцией, чтобы не было мутабельного объекта на уровне модуля
def build_payload() -> dict:
    return {'from': DATE_FROM}


# ИНН госорганов
TAX_AUTHORITY_INN = "7727406020"    # Казначейство / ФНС
SOCIAL_FUND_INN = "7703363868"      # ОСФР (бывший СФР)

# КБК
KBK_TAX_PREFIX = "182"
KBK_PENSION_PREFIX = "392"
KBK_SOCIAL_PREFIX = "393"
KBK_ACCIDENT_PREFIX = "797"

# Тип операции «платёж» в API Т-Банка
OPERATION_TYPE_PAYMENT = "01"
# Тип операции «по карте / счёту» в API Т-Банка
OPERATION_TYPE_CARD = "17"

# Налоговые ставки
INGURE_RATE = 0.009
RATE_CB = 0.16
USN_LIMIT = float(os.getenv('USN_LIMIT', '19999999'))

# HTTP
API_TIMEOUT = float(os.getenv('API_TIMEOUT', '30'))
API_RETRIES = int(os.getenv('API_RETRIES', '3'))
CA_BUNDLE = certifi.where()

#Telegram
TELEGRAM_TOKEN = _require('TELEGRAM_TOKEN')
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv('ADMIN_IDS', '').split(',')
    if x.strip().isdigit()
}