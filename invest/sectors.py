"""Распределение портфеля по секторам."""
import logging

from config.settings import ACCOUNTS_ID, INVEST_TOKEN, CA_BUNDLE
from invest.portfolio_client import TInvestPortfolioClient, parse_portfolio
import requests

logger = logging.getLogger(__name__)


URL_INSTRUMENT = (
    "https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1"
    ".InstrumentsService/GetInstrumentBy"
)


# Кэш секторов по figi
_SECTOR_CACHE: dict[str, str] = {}


def _get_sector(figi: str) -> str:
    """Получает сектор инструмента по figi. Кэширует результат."""
    if figi in _SECTOR_CACHE:
        return _SECTOR_CACHE[figi]

    try:
        r = requests.post(
            URL_INSTRUMENT,
            headers={
                'Authorization': f'Bearer {INVEST_TOKEN}',
                'Content-Type': 'application/json',
            },
            json={'idType': 'INSTRUMENT_ID_TYPE_FIGI', 'id': figi},
            verify=CA_BUNDLE,
            timeout=15,
        )
        if r.status_code != 200:
            _SECTOR_CACHE[figi] = 'Прочее'
            return 'Прочее'

        data = r.json().get('instrument', {})
        sector = data.get('sector') or data.get('instrumentType') or 'Прочее'

        # Переводим на русский
        translation = {
            'SECTOR_FINANCE': 'Финансы',
            'SECTOR_CONSUMER_GOODS': 'Потребительские товары',
            'SECTOR_ENERGY': 'Энергетика',
            'SECTOR_MATERIALS': 'Сырьё',
            'SECTOR_INDUSTRIALS': 'Промышленность',
            'SECTOR_TELECOM': 'Телеком',
            'SECTOR_HEALTHCARE': 'Здравоохранение',
            'SECTOR_IT': 'IT',
            'SECTOR_REAL_ESTATE': 'Недвижимость',
            'SECTOR_UTILITIES': 'Коммунальные',
            'SECTOR_OTHER': 'Прочее',
        }
        sector_ru = translation.get(sector, sector)

        _SECTOR_CACHE[figi] = sector_ru
        return sector_ru

    except Exception as e:
        logger.warning("Не удалось получить сектор для %s: %s", figi, e)
        _SECTOR_CACHE[figi] = 'Прочее'
        return 'Прочее'


def build_sectors_distribution(account_id: str | None = None) -> dict:
    """
    Распределение портфеля по секторам.

    Возвращает: {sector: {'value': X, 'pct': Y, 'figis': [...]}}
    """
    accounts = [account_id] if account_id else ACCOUNTS_ID
    positions: list[dict] = []

    with TInvestPortfolioClient() as client:
        for acc in accounts:
            raw = client.fetch_portfolio(acc)
            if not raw:
                continue
            p = parse_portfolio(raw)
            for pos in p['positions']:
                qty = pos['quantity']
                price = pos['current_price']
                if qty > 0 and price > 0:
                    positions.append({
                        'figi': pos['figi'],
                        'value': qty * price,
                    })

    if not positions:
        return {'error': 'Портфель пуст'}

    total = sum(p['value'] for p in positions)

    # Группируем по секторам
    sectors: dict[str, dict] = {}
    for p in positions:
        sector = _get_sector(p['figi'])
        if sector not in sectors:
            sectors[sector] = {'value': 0.0, 'figis': []}
        sectors[sector]['value'] += p['value']
        sectors[sector]['figis'].append(p['figi'])

    # Считаем доли
    result = {}
    for sector, data in sorted(sectors.items(),
                                key=lambda x: -x[1]['value']):
        result[sector] = {
            'value': round(data['value'], 2),
            'pct': round(data['value'] / total * 100, 2),
            'count': len(data['figis']),
        }

    return {
        'total': round(total, 2),
        'sectors': result,
    }