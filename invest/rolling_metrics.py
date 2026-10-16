"""Rolling-метрики портфеля: скользящий Sharpe, волатильность, доходность."""
import math
from datetime import date

from config.settings import RISK_FREE_RATE
from database.db import Session
from database.snapshot_crud import SnapshotCrud


def _daily_returns(prices: list[float]) -> list[float]:
    result = []
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        curr = prices[i]
        if prev > 0:
            result.append(curr / prev - 1)
    return result


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _sharpe_from_returns(returns: list[float],
                          risk_free_rate: float = None,
                          periods_per_year: int = 252) -> float:
    """
    Sharpe по списку дневных доходностей.

    ВАЖНО: используем ЛИНЕЙНУЮ аннулизацию, а не компаундную.
    Компаундирование на коротких окнах (7-30 дней) даёт абсурдные
    значения (Sharpe +14). Линейная — стандарт для Sharpe.
    """
    if risk_free_rate is None:
        risk_free_rate = RISK_FREE_RATE

    if len(returns) < 2:
        return 0.0

    mean_daily = _mean(returns)
    # Линейная аннулизация
    annual_return = mean_daily * periods_per_year

    std_daily = _stdev(returns)
    annual_vol = std_daily * math.sqrt(periods_per_year)

    if annual_vol == 0:
        return 0.0

    return (annual_return - risk_free_rate) / annual_vol


# ============================================================
# Rolling-серии
# ============================================================

def rolling_sharpe(index_values: list[float],
                   window: int = 30,
                   risk_free_rate: float = None) -> list:
    """Скользящий Sharpe по окну N дней."""
    if risk_free_rate is None:
        risk_free_rate = RISK_FREE_RATE

    result: list = []
    for i in range(len(index_values)):
        if i < window:
            result.append(None)
            continue
        window_values = index_values[i - window: i + 1]
        returns = _daily_returns(window_values)
        if len(returns) < 2:
            result.append(None)
            continue
        result.append(round(_sharpe_from_returns(returns, risk_free_rate), 3))
    return result


def rolling_volatility(index_values: list[float],
                       window: int = 30) -> list:
    """Скользящая годовая волатильность (%)."""
    result: list = []
    for i in range(len(index_values)):
        if i < window:
            result.append(None)
            continue
        window_values = index_values[i - window: i + 1]
        returns = _daily_returns(window_values)
        if len(returns) < 2:
            result.append(None)
            continue
        vol = _stdev(returns) * math.sqrt(252) * 100
        result.append(round(vol, 2))
    return result


def rolling_return(index_values: list[float],
                   window: int = 30) -> list:
    """Скользящая доходность за окно N дней (%)."""
    result: list = []
    for i in range(len(index_values)):
        if i < window:
            result.append(None)
            continue
        start = index_values[i - window]
        end = index_values[i]
        if start == 0:
            result.append(None)
            continue
        result.append(round((end / start - 1) * 100, 2))
    return result


# ============================================================
# Загрузка
# ============================================================

def get_index_values(account_id: str = 'all') -> tuple:
    """Возвращает (dates, index_values) из snapshots."""
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots(account_id)

    dates = []
    values = []
    for s in snapshots:
        if s.index_value > 0 and s.total_value > 0:
            dates.append(s.date.date())
            values.append(float(s.index_value))

    return dates, values


# ============================================================
# Отчёт
# ============================================================

def build_rolling_sharpe_report(account_id: str = 'all',
                                 windows: tuple = (7, 30, 90)) -> dict:
    dates, values = get_index_values(account_id)

    if len(values) < 2:
        return {'error': 'Мало данных — нужно минимум 2 дня'}

    windows_data = {}
    current_data = {}

    for w in windows:
        sharpe_series = rolling_sharpe(values, window=w)
        vol_series = rolling_volatility(values, window=w)
        return_series = rolling_return(values, window=w)

        windows_data[w] = {
            'sharpe': sharpe_series,
            'volatility': vol_series,
            'return': return_series,
        }

        current_data[w] = {
            'sharpe': sharpe_series[-1],
            'volatility': vol_series[-1],
            'return': return_series[-1],
            'has_enough_data': sharpe_series[-1] is not None,
        }

    return {
        'dates': dates,
        'values': values,
        'windows': windows_data,
        'current': current_data,
        'days_total': len(values),
        'risk_free_rate': RISK_FREE_RATE,
    }