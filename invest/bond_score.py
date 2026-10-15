"""Оценка облигации: YTM + дюрация + рейтинг + метрики эмитента."""
from dataclasses import dataclass

from database.db import Session
from database.instrument_crud import InstrumentCrud
from invest.bond_analytics import get_bond_analytics, format_duration


# Рейтинги: чем выше — тем лучше
RATING_SCORE = {
    "AAA": 5, "AA+": 5, "AA": 4, "AA-": 4,
    "A+": 3, "A": 3, "A-": 3,
    "BBB+": 2, "BBB": 2, "BBB-": 2,
    "BB+": 1, "BB": 1, "BB-": 1,
    "B+": 0, "B": 0, "B-": 0,
    "CCC": 0, "CC": 0, "C": 0, "D": 0,
}


def _rating_score(rating: str | None) -> int:
    if not rating:
        return -1
    return RATING_SCORE.get(rating.upper(), 0)


def evaluate_bond(figi: str) -> dict:
    with Session() as s:
        crud = InstrumentCrud(s)
        info = crud.get(figi)
        if not info or info.instrument_type != 'bond':
            return {'error': 'Не облигация'}

        ticker = info.ticker or figi[:15]
        # Для MOEX используем ISIN (если есть) или ticker
        isin = getattr(info, 'isin', None) or info.ticker or figi
        rating = info.credit_rating
        d2e = float(info.net_debt_ebitda) if info.net_debt_ebitda else None
        ic = float(info.interest_coverage) if info.interest_coverage else None
        ocf = info.ocf_positive

    # Данные из MOEX
    analytics = get_bond_analytics(isin) or {}

    ytm = analytics.get('yield_at_prev_wap') or 0
    coupon = analytics.get('coupon_percent') or 0
    duration = analytics.get('duration')
    mat_date = analytics.get('mat_date')
    offer_date = analytics.get('offer_date')
    subtype = analytics.get('bond_subtype')

    warnings = []
    reasons = []

    # --- Рейтинг ---
    r_score = _rating_score(rating)
    if r_score == -1:
        warnings.append("Рейтинг не указан")
    elif r_score >= 3:
        reasons.append(f"Рейтинг {rating} — надёжный")
    elif r_score == 2:
        reasons.append(f"Рейтинг {rating} — средний")
    elif r_score <= 1:
        warnings.append(f"Низкий рейтинг: {rating}")

    # --- YTM ---
    if ytm is None:
        warnings.append("Нет данных по YTM")
    elif ytm >= 18:
        reasons.append(f"YTM {ytm:.1f}% — высокая")
    elif ytm >= 16:
        reasons.append(f"YTM {ytm:.1f}% — хорошая")
    elif ytm < 13:
        warnings.append(f"YTM {ytm:.1f}% — низкая")

    # --- Дюрация ---
    if duration:
        dur_years = duration / 365
        if dur_years > 3:
            warnings.append(f"Длинная дюрация: {format_duration(duration)}")
        elif dur_years < 1:
            reasons.append(f"Короткая дюрация: {format_duration(duration)}")

    # --- Оферта ---
    if offer_date:
        warnings.append(f"Оферта: {offer_date}")
    elif subtype and 'call' in (subtype or '').lower():
        warnings.append("Call-оферта (дата не указана)")

    # --- Метрики эмитента ---
    if d2e is not None:
        if d2e < 2.5:
            reasons.append(f"Долг/EBITDA {d2e:.1f} — низкий")
        elif d2e > 4:
            warnings.append(f"Долг/EBITDA {d2e:.1f} — высокий")

    if ic is not None:
        if ic > 3:
            reasons.append(f"Покрытие процентов {ic:.1f} — хорошее")
        elif ic < 2:
            warnings.append(f"Покрытие процентов {ic:.1f} — низкое")

    if ocf is True:
        reasons.append("OCF положительный")
    elif ocf is False:
        warnings.append("OCF отрицательный")

    # --- Вердикт ---
    positive = len(reasons)
    negative = len(warnings)

    if r_score == -1:
        # Рейтинг не указан — не отправляем в AVOID
        verdict = "HOLD"
    elif r_score >= 3 and (ytm or 0) >= 16 and negative == 0:
        verdict = "BUY"
    elif r_score <= 1 or (ytm or 0) < 13 or negative >= 3:
        verdict = "AVOID"
    else:
        verdict = "HOLD"

    return {
        'figi': figi,
        'ticker': ticker,
        'rating': rating,
        'coupon': coupon,
        'ytm': ytm,
        'duration_days': duration,
        'duration_human': format_duration(duration),
        'mat_date': mat_date,
        'offer_date': offer_date,
        'net_debt_ebitda': d2e,
        'interest_coverage': ic,
        'ocf_positive': ocf,
        'reasons': reasons,
        'warnings': warnings,
        'verdict': verdict,
    }