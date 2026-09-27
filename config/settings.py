from pathlib import Path
from dotenv import load_dotenv
import os
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


BUSINESS_TOKEN = os.getenv('BUSINESS_TOKEN')
BUSINESS_URL = os.getenv('BUSINESS_URL')
DATE_FROM = '2026-08-01'
PAYLOAD = {'from': DATE_FROM}

MY_INN = os.getenv('MY_INN')
BANK_INN = os.getenv('BANK_INN')

# ИНН госорганов
TAX_AUTHORITY_INN = "7727406020"    # Казначейство / ФНС
SOCIAL_FUND_INN = "7703363868"      # ОСФР (бывший СФР)

# KBK-префиксы для классификации взносов
KBK_PENSION_PREFIX = "392"   # ПФР / пенсионные взносы
KBK_SOCIAL_PREFIX = "393"    # ФСС / социальные взносы
KBK_ACCIDENT_PREFIX = "797"  # ФСС от несчастных случаев