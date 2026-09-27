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