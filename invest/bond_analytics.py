"""Получение данных по облигациям через MOEX ISS.

Возвращает: купон, YTM, дюрацию, дату погашения, оферту, НКД.
Рейтинг и метрики эмитента — вручную (см. update_bond_ratings.py).
"""
import logging

import requests

logger = logging.getLogger(__name__)

MOEX_BASE = "https://iss.moex.com/iss"


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_bond_analytics(isin: str) -> dict | None:
    """Возвращает данные об облигации из MOEX ISS."""
    url = f"{MOEX_BASE}/engines/stock/markets/bonds/securities/{isin}.json"
    params = {"iss.meta": "off"}

    try:
        r = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        logger.error("MOEX ISS %s: сеть: %s", isin, e)
        return None

    if r.status_code != 200:
        logger.warning("MOEX ISS %s: HTTP %s", isin, r.status_code)
        return None

    try:
        data = r.json()
    except Exception:
        return None

    sec = data.get("securities", {})
    sec_cols = sec.get("columns", [])
    sec_rows = sec.get("data", [])

    mkt = data.get("marketdata", {})
    mkt_cols = mkt.get("columns", [])
    mkt_rows = mkt.get("data", [])

    if not sec_rows:
        return None

    sec_row = dict(zip(sec_cols, sec_rows[0]))
    mkt_row = dict(zip(mkt_cols, mkt_rows[0])) if mkt_rows else {}

    # Оферта из bondization.json
    offer_date = _get_offer_date(isin)

    return {
        "isin": isin,
        "secid": sec_row.get("SECID"),
        "short_name": sec_row.get("SHORTNAME"),
        "coupon_percent": _to_float(sec_row.get("COUPONPERCENT")),
        "coupon_value": _to_float(sec_row.get("COUPONVALUE")),
        "next_coupon": sec_row.get("NEXTCOUPON"),
        "yield_at_prev_wap": _to_float(sec_row.get("YIELDATPREVWAPRICE")),
        "duration": _to_float(mkt_row.get("DURATION")),
        "mat_date": sec_row.get("MATDATE"),
        "offer_date": offer_date,
        "bond_subtype": sec_row.get("BONDSUBTYPE"),
        "accrued_int": _to_float(sec_row.get("ACCRUEDINT")),
        "face_value": _to_float(sec_row.get("FACEVALUE")),
    }


def _get_offer_date(isin: str) -> str | None:
    """Дата оферты из bondization.json."""
    url = f"{MOEX_BASE}/securities/{isin}/bondization.json"
    params = {"iss.meta": "off", "iss.only": "offers"}

    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    offers = data.get("offers", {})
    cols = offers.get("columns", [])
    rows = offers.get("data", [])

    for row in rows:
        d = dict(zip(cols, row))
        date = d.get("offerdate")
        if date and date != "0000-00-00":
            return date
    return None


def format_duration(duration_days: float | None) -> str:
    """Дюрация в днях → 'X лет Y мес'."""
    if duration_days is None:
        return "—"

    years = int(duration_days // 365)
    months = int((duration_days % 365) // 30)

    if years == 0:
        return f"{months} мес"
    if months == 0:
        return f"{years} г"
    return f"{years} г {months} мес"