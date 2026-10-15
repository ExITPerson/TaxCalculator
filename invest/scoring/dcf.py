"""DCF-модель — «второе мнение» для оценки справедливой цены."""
import logging

from database.db import Session
from database.fundamentals_crud import StockFundamentalsCrud

logger = logging.getLogger(__name__)


# Параметры модели (можно вынести в .env)
DEFAULT_WACC = 0.16              # ставка дисконтирования (16% — под ключевую)
DEFAULT_TERMINAL_GROWTH = 0.03   # терминальный рост (3%)
DEFAULT_FORECAST_YEARS = 5


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_dcf(
    ticker: str,
    wacc: float = DEFAULT_WACC,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
    forecast_years: int = DEFAULT_FORECAST_YEARS,
) -> dict | None:
    """
    Строит DCF на основе FCF из фундаментала.

    Логика:
    1. Берём исторический FCF (5 лет).
    2. Считаем средний темп роста FCF.
    3. Прогнозируем FCF на forecast_years лет.
    4. Дисконтируем по WACC.
    5. Прибавляем терминальную стоимость (Gordon).
    6. Делим на shares → fair_price.
    7. Сравниваем с текущей ценой.

    Возвращает:
    {
        "fair_price": 1234.5,
        "current_price": 5678.9,
        "upside_pct": -78.2,      # -78% — переоценён
        "verdict": "overvalued" | "fair" | "undervalued",
        "wacc": 0.16,
        "terminal_growth": 0.03,
        "fcf_history": [...],
        "fcf_forecast": [...],
        "enterprise_value": 12345.6,
        "shares": 2138.0,
    }
    """
    with Session() as s:
        crud = StockFundamentalsCrud(s)
        history = crud.get_history(ticker, years=10)
        latest = crud.get_latest(ticker)

    if not history or not latest:
        return None

    # ---- FCF история ----
    fcf_series = [_to_float(h.fcf) for h in reversed(history)]
    fcf_series = [f for f in fcf_series if f is not None and f > 0]

    extra = latest.extra_metrics or {}
    shares = _to_float(extra.get("shares_outstanding"))
    if not shares or shares <= 0:
        logger.warning("DCF %s: нет shares_outstanding", ticker)
        return None

    if len(fcf_series) < 3:
        return None

    # ---- Средний темп роста FCF ----
    growth_rates = []
    for i in range(1, len(fcf_series)):
        prev, curr = fcf_series[i - 1], fcf_series[i]
        if prev > 0:
            growth_rates.append(curr / prev - 1)
    avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0.05

    # Ограничиваем рост: не больше 20%, не меньше 0%
    avg_growth = max(0.0, min(0.20, avg_growth))

    # ---- Прогноз FCF ----
    last_fcf = fcf_series[-1]
    fcf_forecast = []
    for i in range(1, forecast_years + 1):
        fcf_forecast.append(last_fcf * (1 + avg_growth) ** i)

    # ---- Дисконтирование ----
    if wacc <= terminal_growth:
        return None

    discounted = []
    for i, fcf in enumerate(fcf_forecast, start=1):
        discounted.append(fcf / (1 + wacc) ** i)

    # Терминальная стоимость (Gordon)
    terminal_fcf = fcf_forecast[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    discounted_terminal = terminal_value / (1 + wacc) ** forecast_years

    enterprise_value = sum(discounted) + discounted_terminal

    # ---- Стоимость акции ----
    extra = latest.extra_metrics or {}
    shares = _to_float(extra.get("shares_outstanding"))
    if not shares or shares <= 0:
        return None

    # shares в млн, EV в млрд руб → fair_price в руб
    fair_price = enterprise_value * 1000 / shares

    # ---- Текущая цена ----
    current_price = _to_float(extra.get("share_price"))
    if not current_price:
        return None

    upside = (fair_price / current_price - 1) * 100

    if upside > 20:
        verdict = "undervalued"
    elif upside < -20:
        verdict = "overvalued"
    else:
        verdict = "fair"

    return {
        "fair_price": round(fair_price, 2),
        "current_price": round(current_price, 2),
        "upside_pct": round(upside, 2),
        "verdict": verdict,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "avg_growth": round(avg_growth, 4),
        "fcf_history": [round(f, 2) for f in fcf_series],
        "fcf_forecast": [round(f, 2) for f in fcf_forecast],
        "enterprise_value": round(enterprise_value, 2),
        "shares": shares,
    }


def dcf_opinion(ticker: str) -> str:
    """Короткое мнение DCF: 'undervalued' / 'fair' / 'overvalued' / 'no_data'."""
    result = build_dcf(ticker)
    if not result:
        return "no_data"
    return result["verdict"]