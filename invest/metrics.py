"""Метрики портфеля: rolling-доходность, волатильность, Sharpe, Sortino, Calmar, Beta, Alpha."""
import math
from datetime import date, datetime, timedelta

from config.settings import RISK_FREE_RATE
from database.db import Session
from database.snapshot_crud import SnapshotCrud


# FIGI бенчмарка по умолчанию (RGBI — индекс гособлигаций)
DEFAULT_BENCHMARK_FIGI = 'BBG000V0SJ39'
DEFAULT_BENCHMARK_NAME = 'RGBI'


# ============================================================
# Базовые расчёты
# ============================================================

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
    """Sharpe с линейной аннулизацией."""
    if risk_free_rate is None:
        risk_free_rate = RISK_FREE_RATE

    if len(returns) < 2:
        return 0.0

    mean_daily = _mean(returns)
    annual_return = mean_daily * periods_per_year

    std_daily = _stdev(returns)
    annual_vol = std_daily * math.sqrt(periods_per_year)

    # Защита от бессмысленного Sharpe при почти нулевой волатильности
    if annual_vol < 0.005:
        return 0.0

    return (annual_return - risk_free_rate) / annual_vol


# ============================================================
# Rolling-серии
# ============================================================

def rolling_return(index_values: list[float],
                   window: int = 30) -> list:
    result = []
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


def rolling_volatility(index_values: list[float],
                       window: int = 30) -> list:
    result = []
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


def rolling_sharpe(index_values: list[float],
                   window: int = 30,
                   risk_free_rate: float = None) -> list:
    if risk_free_rate is None:
        risk_free_rate = RISK_FREE_RATE

    result = []
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


# ============================================================
# Maximum Drawdown / Calmar
# ============================================================

def max_drawdown(index_values: list[float]) -> dict:
    """Максимальная просадка от пика."""
    if not index_values:
        return {'max_dd_pct': 0.0, 'current_dd_pct': 0.0}

    peak = index_values[0]
    max_dd = 0.0

    for v in index_values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd

    global_peak = max(index_values)
    current_dd = (
        (index_values[-1] - global_peak) / global_peak * 100
        if global_peak > 0 else 0.0
    )

    return {
        'max_dd_pct': round(max_dd, 2),
        'current_dd_pct': round(current_dd, 2),
    }


def calmar_ratio(index_values: list[float], days: int) -> float:
    """Calmar = годовая доходность / max drawdown (по модулю)."""
    if days <= 0 or len(index_values) < 2:
        return 0.0

    total_ret = index_values[-1] / index_values[0] - 1
    annual_ret = (1 + total_ret) ** (365 / days) - 1

    dd = abs(max_drawdown(index_values)['max_dd_pct']) / 100
    if dd == 0:
        return 0.0

    return annual_ret / dd


# ============================================================
# Sortino
# ============================================================

def sortino_ratio(index_values: list[float],
                  risk_free_rate: float = None,
                  periods_per_year: int = 252) -> float:
    """Sortino = (доходность − rf) / downside deviation."""
    if risk_free_rate is None:
        risk_free_rate = RISK_FREE_RATE

    returns = _daily_returns(index_values)
    if len(returns) < 2:
        return 0.0

    mean_daily = _mean(returns)
    annual_return = mean_daily * periods_per_year

    negative_returns = [r for r in returns if r < 0]
    if not negative_returns:
        return 0.0

    downside_var = sum(r ** 2 for r in negative_returns) / len(negative_returns)
    downside_std = math.sqrt(downside_var)
    annual_downside = downside_std * math.sqrt(periods_per_year)

    if annual_downside == 0:
        return 0.0

    return (annual_return - risk_free_rate) / annual_downside


# ============================================================
# Beta / Alpha
# ============================================================

def beta_alpha(portfolio_values: list[float],
               benchmark_values: list[float],
               risk_free_rate: float = None) -> tuple:
    """
    Beta = cov(portfolio, benchmark) / var(benchmark).
    Alpha = annual_return_portfolio − rf − Beta × (annual_return_bench − rf).

    Доходности — CAGR (компаундирование), не линейная аннулизация.
    """
    if risk_free_rate is None:
        risk_free_rate = RISK_FREE_RATE

    n = min(len(portfolio_values), len(benchmark_values))
    if n < 3:
        return 0.0, 0.0

    p = portfolio_values[-n:]
    b = benchmark_values[-n:]

    # CAGR за период
    total_ret_p = p[-1] / p[0] - 1 if p[0] > 0 else 0.0
    total_ret_b = b[-1] / b[0] - 1 if b[0] > 0 else 0.0

    annual_ret_p = (1 + total_ret_p) ** (252 / n) - 1
    annual_ret_b = (1 + total_ret_b) ** (252 / n) - 1

    # Beta через дневные доходности
    p_ret = _daily_returns(p)
    b_ret = _daily_returns(b)

    m = min(len(p_ret), len(b_ret))
    if m < 2:
        return 0.0, 0.0

    p_ret = p_ret[-m:]
    b_ret = b_ret[-m:]

    mean_p = _mean(p_ret)
    mean_b = _mean(b_ret)

    cov = sum((p_ret[i] - mean_p) * (b_ret[i] - mean_b) for i in range(m)) / (m - 1)
    var_b = sum((b_ret[i] - mean_b) ** 2 for i in range(m)) / (m - 1)

    if var_b == 0:
        return 0.0, 0.0

    beta = cov / var_b
    alpha = annual_ret_p - risk_free_rate - beta * (annual_ret_b - risk_free_rate)

    return round(beta, 3), round(alpha * 100, 2)


# ============================================================
# Загрузка данных
# ============================================================

def get_index_values(account_id: str = 'all') -> tuple:
    """(dates, index_values) из snapshots."""
    with Session() as s:
        snapshots = SnapshotCrud(s).get_snapshots(account_id)

    dates = []
    values = []
    for s in snapshots:
        if s.index_value > 0 and s.total_value > 0:
            dates.append(s.date.date())
            values.append(float(s.index_value))

    return dates, values


def _load_benchmark_normalized(figi: str, date_from: date, date_to: date) -> list:
    """Загружает бенчмарк и нормализует к 100."""
    from invest.candles_client import TInvestCandlesClient

    with Session() as session:
        crud = SnapshotCrud(session)
        cached = crud.get_cached_candles(figi, date_from, date_to)

        all_days = set()
        current = date_from
        while current <= date_to:
            all_days.add(current)
            current += timedelta(days=1)

        missing = all_days - set(cached.keys())
        if missing:
            with TInvestCandlesClient() as client:
                fetched = client.fetch_candles(
                    figi,
                    datetime.combine(min(missing), datetime.min.time()),
                    datetime.combine(max(missing), datetime.min.time()),
                )
            if fetched:
                crud.save_candles(figi, fetched)
                cached.update(fetched)

    sorted_items = sorted(cached.items())
    if not sorted_items:
        return []

    base = None
    for d, p in sorted_items:
        if d >= date_from and p > 0:
            base = p
            break

    if base is None:
        return []

    return [(p / base) * 100 for d, p in sorted_items if d >= date_from]


# ============================================================
# Полный отчёт
# ============================================================

def build_metrics_report(account_id: str = 'all',
                          benchmark_figi: str = DEFAULT_BENCHMARK_FIGI,
                          benchmark_name: str = DEFAULT_BENCHMARK_NAME) -> dict:
    """Полная сводка метрик портфеля."""
    dates, values = get_index_values(account_id)

    if len(values) < 2:
        return {'error': 'Мало данных — нужно минимум 2 дня'}

    days_total = (dates[-1] - dates[0]).days or 1

    # Rolling-метрики
    rolling = {
        7: rolling_return(values, 7),
        30: rolling_return(values, 30),
        90: rolling_return(values, 90),
    }

    current_rolling = {
        7: rolling[7][-1] if rolling[7][-1] is not None else None,
        30: rolling[30][-1] if rolling[30][-1] is not None else None,
        90: rolling[90][-1] if rolling[90][-1] is not None else None,
    }

    # Основные метрики
    annual_vol = annualized_volatility(values)
    sharpe = _sharpe_from_returns(_daily_returns(values))
    sortino = sortino_ratio(values)
    calmar = calmar_ratio(values, days_total)
    dd = max_drawdown(values)

    # Бенчмарк
    benchmark_values = _load_benchmark_normalized(
        benchmark_figi, dates[0], dates[-1],
    )

    beta = alpha = 0.0
    benchmark_return_pct = None

    if benchmark_values and len(benchmark_values) >= 2:
        beta, alpha = beta_alpha(values, benchmark_values)
        benchmark_return_pct = round(benchmark_values[-1] - 100, 2)

    information_ratio_value = None
    if benchmark_values and len(benchmark_values) >= 2:
        information_ratio_value = information_ratio(values, benchmark_values)

    return {
        'days_total': len(values),
        'date_from': dates[0],
        'date_to': dates[-1],
        'days_span': days_total,

        'current_index': round(values[-1], 2),
        'total_return_pct': round(values[-1] - 100, 2),

        'rolling_7d': current_rolling[7],
        'rolling_30d': current_rolling[30],
        'rolling_90d': current_rolling[90],

        'volatility_annual_pct': round(annual_vol, 2),
        'sharpe': round(sharpe, 3),
        'sortino': round(sortino, 3),
        'calmar': round(calmar, 3),

        'max_drawdown_pct': dd['max_dd_pct'],
        'current_drawdown_pct': dd['current_dd_pct'],

        'benchmark_name': benchmark_name,
        'benchmark_return_pct': benchmark_return_pct,
        'beta': beta,
        'alpha': alpha,

        'risk_free_rate': RISK_FREE_RATE,

        'information_ratio': information_ratio_value,
    }


def annualized_volatility(index_values: list[float]) -> float:
    returns = _daily_returns(index_values)
    if len(returns) < 2:
        return 0.0
    return _stdev(returns) * math.sqrt(252) * 100

def information_ratio(portfolio_values: list[float],
                      benchmark_values: list[float]) -> float | None:
    """
    IR = средняя(portfolio − benchmark) / stdev(portfolio − benchmark).
    Показывает сверхдоходность на единицу tracking error.
    """
    n = min(len(portfolio_values), len(benchmark_values))
    if n < 3:
        return None

    p = portfolio_values[-n:]
    b = benchmark_values[-n:]

    p_ret = _daily_returns(p)
    b_ret = _daily_returns(b)

    m = min(len(p_ret), len(b_ret))
    if m < 2:
        return None

    p_ret = p_ret[-m:]
    b_ret = b_ret[-m:]

    # Excess returns
    excess = [p_ret[i] - b_ret[i] for i in range(m)]

    mean_excess = _mean(excess)
    std_excess = _stdev(excess)

    if std_excess == 0:
        return None

    # Аннуализируем: mean × 252 / (std × √252)
    return round((mean_excess * 252) / (std_excess * math.sqrt(252)), 3)