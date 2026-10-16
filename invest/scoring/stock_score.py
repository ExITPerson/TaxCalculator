"""Скоринг акций на основе фундаментала.

Два сценария:
- Нефинансовые: ROIC/ROE, EBITDA margin, FCF, долг, D/E,
  P/E, P/B, EV/EBITDA, FCF Yield, перцентиль P/E, DCF.
- Банки: ROE, ROA, NIM, рост портфеля, P/E.

Предупреждения делятся на:
- critical — блокируют BUY (убыток, отрицательный FCF, и т.д.)
- warnings — понижают, но не блокируют
- info     — нейтральная информация
"""
import logging
from decimal import Decimal
from statistics import mean, pstdev

from database.db import Session
from database.fundamentals_crud import StockFundamentalsCrud
from invest.scoring.verdict import Verdict, clamp, decide_action
from invest.scoring import thresholds as th

logger = logging.getLogger(__name__)


# ============================================================
# Утилиты
# ============================================================

def _to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cv(values: list[float | None]) -> float | None:
    clean = [_to_float(v) for v in values]
    clean = [v for v in clean if v is not None]
    if len(clean) < 3:
        return None
    m = mean(clean)
    if m == 0:
        return None
    return pstdev(clean) / abs(m)


def _trend(values: list[float | None]) -> float | None:
    clean = [(i, _to_float(v)) for i, v in enumerate(values)]
    clean = [(i, v) for i, v in clean if v is not None]
    if len(clean) < 3:
        return None
    n = len(clean)
    xs = [x for x, _ in clean]
    ys = [y for _, y in clean]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den == 0:
        return None
    return num / den


def _extract_series(history, field: str) -> list[float | None]:
    return [_to_float(getattr(row, field, None)) for row in reversed(history)]


def _extract_extra(history, field: str) -> list[float | None]:
    result = []
    for row in reversed(history):
        extra = row.extra_metrics or {}
        result.append(_to_float(extra.get(field)))
    return result


def _split_anomalies(anomaly_flags: dict) -> tuple[list[str], list[str]]:
    """Делит флаги аномалий на critical и warnings."""
    critical = []
    warnings = []
    for flag in (anomaly_flags or {}):
        if flag in th.CRITICAL_ANOMALY_FLAGS:
            critical.append(f"Аномалия: {flag}")
        elif flag in th.WARNING_ANOMALY_FLAGS:
            warnings.append(f"Аномалия: {flag}")
    return critical, warnings


# ============================================================
# Скоринг: нефинансовые
# ============================================================

def _score_nonfinancial(ticker: str, history: list) -> Verdict:
    critical: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    score = 0.0

    latest = history[0]
    extra = latest.extra_metrics or {}

    roe = _to_float(latest.roe)
    roa = _to_float(latest.roa)
    roic = _to_float(latest.roic)
    revenue = _to_float(latest.revenue)
    ebitda = _to_float(latest.ebitda)
    net_profit = _to_float(latest.net_profit)
    fcf = _to_float(latest.fcf)
    payout = _to_float(latest.payout_ratio)

    d2e = _to_float(extra.get("debt_to_ebitda"))
    ebitda_margin = _to_float(extra.get("ebitda_margin"))
    interest = _to_float(extra.get("interest_expense"))
    market_cap = _to_float(extra.get("market_cap"))
    pe = _to_float(extra.get("pe"))
    pb = _to_float(extra.get("pb"))
    ev_ebitda = _to_float(extra.get("ev_ebitda"))
    fcf_yield = _to_float(extra.get("fcf_yield"))
    de = _to_float(extra.get("debt_to_equity"))
    debt = _to_float(extra.get("debt"))
    equity = _to_float(extra.get("equity"))

    # ---- Аномалии ----
    crit_flags, warn_flags = _split_anomalies(latest.anomaly_flags or {})
    critical.extend(crit_flags)
    warnings.extend(warn_flags)

    # ============================================================
    # КАЧЕСТВО
    # ============================================================

    quality = roic if roic is not None else roe
    if quality is not None and not (latest.anomaly_flags or {}).get("roe_anomaly"):
        if quality > th.ROIC_BUY:
            score += 15
            info.append(f"ROIC/ROE {quality:.1%} > 15% — создаёт стоимость")
        elif quality > th.ROIC_OK:
            score += 8
            info.append(f"ROIC/ROE {quality:.1%} — приемлемо")
        elif quality > 0:
            score += 3
        else:
            critical.append(f"ROIC/ROE {quality:.1%} — отрицательная доходность")

    # Стабильность ROE
    roe_series = [v for v in _extract_series(history, "roe")
                  if v is not None and -1 < v < 1]
    roe_cv = _cv(roe_series)
    if roe_cv is not None:
        if roe_cv < 0.3:
            score += 8
            info.append("ROE стабильный (CV < 0.3)")
        elif roe_cv > 0.7:
            warnings.append("ROE волатильный (CV > 0.7)")

    # EBITDA margin
    if ebitda_margin is not None:
        if ebitda_margin > th.EBITDA_MARGIN_BUY:
            score += 7
            info.append(f"EBITDA margin {ebitda_margin:.1%} > 20%")
        elif ebitda_margin > th.EBITDA_MARGIN_OK:
            score += 4
        elif ebitda_margin < 0:
            warnings.append(f"EBITDA margin {ebitda_margin:.1%} — убыток")

    # ============================================================
    # УСТОЙЧИВОСТЬ
    # ============================================================

    if d2e is not None:
        if d2e < th.DEBT_EBITDA_OK:
            score += 12
            info.append(f"Долг/EBITDA {d2e:.2f} — низкий")
        elif d2e < th.DEBT_EBITDA_WARN:
            score += 7
        elif d2e < th.DEBT_EBITDA_CRITICAL:
            score += 2
            warnings.append(f"Долг/EBITDA {d2e:.2f} — выше нормы")
        else:
            critical.append(f"Долг/EBITDA {d2e:.2f} — критично высокий")

    # Покрытие процентов
    if interest and ebitda and interest > 0:
        coverage = ebitda / interest
        if coverage > th.INTEREST_COVERAGE_BUY:
            score += 8
            info.append(f"Покрытие процентов {coverage:.1f}× — отличное")
        elif coverage > th.INTEREST_COVERAGE_OK:
            score += 5
        elif coverage < th.INTEREST_COVERAGE_CRITICAL:
            critical.append(f"Покрытие процентов {coverage:.1f}× — критично")
        elif coverage < th.INTEREST_COVERAGE_OK:
            warnings.append(f"Покрытие процентов {coverage:.1f}× < 3 — риск")

    # D/E
    if de is not None:
        if de < th.DE_BUY:
            score += 6
            info.append(f"D/E {de:.2f} — низкий долг")
        elif de > th.DE_WARN:
            warnings.append(f"D/E {de:.2f} — высокий долг")

    # ============================================================
    # FCF
    # ============================================================

    if fcf is not None and revenue:
        fcf_rev = fcf / revenue
        if fcf_rev > th.FCF_REVENUE_BUY:
            score += 12
            info.append(f"FCF/Revenue {fcf_rev:.1%} — высокий")
        elif fcf_rev > th.FCF_REVENUE_OK:
            score += 8
            info.append(f"FCF/Revenue {fcf_rev:.1%} — приемлемо")
        elif fcf_rev > 0:
            score += 3
        elif fcf_rev < th.FCF_REVENUE_CRITICAL:
            critical.append(f"FCF/Revenue {fcf_rev:.1%} — отрицательный FCF")
        else:
            warnings.append(f"FCF/Revenue {fcf_rev:.1%} — отрицательный")

    if fcf_yield is not None:
        if fcf_yield > th.FCF_YIELD_BUY:
            score += 10
            info.append(f"FCF Yield {fcf_yield:.1%} — отличная доходность")
        elif fcf_yield > th.FCF_YIELD_OK:
            score += 6
            info.append(f"FCF Yield {fcf_yield:.1%} — интересно")
        elif fcf_yield < 0:
            warnings.append(f"FCF Yield {fcf_yield:.1%} — отрицательный")

    fcf_series = [v for v in _extract_series(history, "fcf") if v is not None]
    fcf_cv = _cv(fcf_series)
    if fcf_cv is not None and fcf_cv < 0.5:
        score += 8
        info.append("FCF стабильный")

    # ============================================================
    # МУЛЬТИПЛИКАТОРЫ
    # ============================================================

    if market_cap and market_cap > 0:
        info.append(f"Market cap: {market_cap:,.0f} млрд ₽")

    if pe is not None and pe > 0:
        if pe < th.PE_BUY:
            score += 10
            info.append(f"P/E {pe:.1f} — дёшево")
        elif pe < th.PE_WARN:
            score += 2
        else:
            warnings.append(f"P/E {pe:.1f} — дорого")

    if pb is not None and pb > 0:
        if pb < th.PB_BUY:
            score += 6
            info.append(f"P/B {pb:.2f} < 1.5")
        elif pb > th.PB_WARN:
            warnings.append(f"P/B {pb:.2f} — дорого к капиталу")

    if ev_ebitda is not None and ev_ebitda > 0:
        if ev_ebitda < th.EV_EBITDA_BUY:
            score += 6
            info.append(f"EV/EBITDA {ev_ebitda:.1f} — дёшево")
        elif ev_ebitda > th.EV_EBITDA_WARN:
            warnings.append(f"EV/EBITDA {ev_ebitda:.1f} — дорого")

    # ============================================================
    # ТРЕНДЫ
    # ============================================================

    revenue_series = [v for v in _extract_series(history, "revenue") if v is not None]
    rev_trend = _trend(revenue_series)
    if rev_trend is not None and rev_trend > 0:
        score += 7
        info.append("Выручка растёт")
    elif rev_trend is not None and rev_trend < 0:
        warnings.append("Выручка падает")

    np_series = [v for v in _extract_series(history, "net_profit") if v is not None]
    np_trend = _trend(np_series)
    if np_trend is not None and np_trend > 0:
        score += 5
        info.append("Чистая прибыль растёт")

    # Payout
    if payout is not None:
        if th.PAYOUT_MIN <= payout <= th.PAYOUT_MAX:
            score += 5
            info.append(f"Payout {payout:.0%} — здоровый")
        elif payout > th.PAYOUT_CRITICAL:
            critical.append(f"Payout {payout:.0%} > 200% — критично")
        elif payout > 1.0:
            warnings.append(f"Payout {payout:.0%} > 100% — unsustainable")

    # Убыток — критично
    if (latest.anomaly_flags or {}).get("loss_making"):
        critical.append("Компания убыточна")

    score = clamp(score)
    action = decide_action(score, critical, warnings)

    return Verdict(
        asset=ticker, action=action, score=score, kind="share",
        critical=critical, warnings=warnings, info=info,
        metrics_used={
            "roe": roe, "roic": roic, "revenue": revenue,
            "ebitda": ebitda, "net_profit": net_profit, "fcf": fcf,
            "debt_to_ebitda": d2e, "pe": pe, "pb": pb,
            "ev_ebitda": ev_ebitda, "fcf_yield": fcf_yield,
        },
    )


# ============================================================
# Скоринг: банки
# ============================================================

def _score_bank(ticker: str, history: list) -> Verdict:
    critical: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    score = 0.0

    latest = history[0]
    extra = latest.extra_metrics or {}

    roe = _to_float(latest.roe)
    roa = _to_float(latest.roa)
    nii = _to_float(latest.net_interest_income)
    noi = _to_float(latest.net_operating_income)
    fee = _to_float(latest.net_fee_income)
    net_profit = _to_float(latest.net_profit)
    payout = _to_float(latest.payout_ratio)
    bank_assets = _to_float(extra.get("bank_assets"))
    pe = _to_float(extra.get("pe"))

    crit_flags, warn_flags = _split_anomalies(latest.anomaly_flags or {})
    critical.extend(crit_flags)
    warnings.extend(warn_flags)

    # ---- Прибыльность ----
    if roe is not None and not (latest.anomaly_flags or {}).get("roe_anomaly"):
        if roe > th.BANK_ROE_BUY:
            score += 18
            info.append(f"ROE {roe:.1%} > 20% — отличная прибыльность")
        elif roe > th.BANK_ROE_OK:
            score += 12
            info.append(f"ROE {roe:.1%} — высокая")
        elif roe > 0.10:
            score += 6
        elif roe > 0:
            score += 2
        else:
            critical.append(f"ROE {roe:.1%} — отрицательная")

    if roa is not None and not (latest.anomaly_flags or {}).get("roa_anomaly"):
        if roa > th.BANK_ROA_BUY:
            score += 12
            info.append(f"ROA {roa:.1%} > 2% — эффективный банк")
        elif roa > th.BANK_ROA_OK:
            score += 6
        elif roa > 0:
            score += 2
        else:
            warnings.append(f"ROA {roa:.1%} — отрицательная")

    # ---- NIM ----
    if nii is not None and bank_assets and bank_assets > 0:
        nim = nii / bank_assets
        if nim > th.BANK_NIM_BUY:
            score += 15
            info.append(f"NIM {nim:.1%} > 5% — высокая маржа")
        elif nim > th.BANK_NIM_OK:
            score += 10
            info.append(f"NIM {nim:.1%} — приемлемая")
        elif nim > 0.01:
            score += 4
        else:
            warnings.append(f"NIM {nim:.1%} — низкая")

    # Доля комиссий
    if fee is not None and noi and noi > 0:
        fee_share = fee / noi
        if fee_share > 0.25:
            score += 5
            info.append(f"Доля комиссий {fee_share:.0%} — диверсификация")

    # ---- Рост ----
    loans_series = [v for v in _extract_extra(history, "loan_portfolio")
                    if v is not None]
    loans_trend = _trend(loans_series)
    if loans_trend is not None and loans_trend > 0:
        score += 12
        info.append("Кредитный портфель растёт")
    elif loans_trend is not None and loans_trend < 0:
        warnings.append("Кредитный портфель сокращается")

    np_series = [v for v in _extract_series(history, "net_profit") if v is not None]
    np_trend = _trend(np_series)
    if np_trend is not None and np_trend > 0:
        score += 8
        info.append("Чистая прибыль растёт")

    # ---- Устойчивость ----
    roe_series = [v for v in _extract_series(history, "roe")
                  if v is not None and -1 < v < 1]
    roe_cv = _cv(roe_series)
    if roe_cv is not None:
        if roe_cv < 0.25:
            score += 10
            info.append("ROE стабильный (CV < 0.25)")
        elif roe_cv > 0.5:
            warnings.append("ROE волатильный")

    # Payout
    if payout is not None:
        if th.BANK_PAYOUT_MIN <= payout <= th.BANK_PAYOUT_MAX:
            score += 5
            info.append(f"Payout {payout:.0%} — комфортный")
        elif payout > th.BANK_PAYOUT_WARN:
            warnings.append(f"Payout {payout:.0%} — высокий")

    # P/E
    if pe is not None and pe > 0:
        if pe < 5:
            score += 5
            info.append(f"P/E {pe:.2f} — очень дёшево")
        elif pe < 10:
            score += 3
            info.append(f"P/E {pe:.2f} — дёшево")
        elif pe > 15:
            warnings.append(f"P/E {pe:.2f} — дорого")

    score = clamp(score)
    action = decide_action(score, critical, warnings)

    return Verdict(
        asset=ticker, action=action, score=score, kind="bank",
        critical=critical, warnings=warnings, info=info,
        metrics_used={
            "roe": roe, "roa": roa,
            "net_interest_income": nii,
            "bank_assets": bank_assets,
            "net_profit": net_profit, "pe": pe,
        },
    )


# ============================================================
# Точка входа
# ============================================================

def _is_bank(latest) -> bool:
    if latest.net_operating_income is not None:
        return True
    if latest.net_interest_income is not None:
        return True
    if latest.net_fee_income is not None:
        return True
    extra = latest.extra_metrics or {}
    if "bank_assets" in extra:
        return True
    return False


def score_stock(
    ticker: str,
    years: int = 10,
    auto_backfill: bool = True,
    backfill_delay: float = 0.5,
) -> Verdict:
    from invest.fundamentals.smartlab_parser import _normalize_ticker
    ticker = _normalize_ticker(ticker)

    with Session() as s:
        crud = StockFundamentalsCrud(s)
        history = crud.get_history(ticker, years=years)

    if not history and auto_backfill:
        logger.info("Нет фундаментала для %s — запускаю backfill...", ticker)
        try:
            from invest.fundamentals.backfill_fundamentals import (
                backfill_portfolio_fundamentals,
            )
            backfill_portfolio_fundamentals(
                force=False, delay=backfill_delay,
                only_tickers=[ticker], create_tables=True,
            )
            with Session() as s:
                history = StockFundamentalsCrud(s).get_history(
                    ticker, years=years,
                )
        except Exception as e:
            logger.error("Ошибка backfill для %s: %s", ticker, e)
            return Verdict(
                asset=ticker, action="HOLD", score=0.0, kind="share",
                warnings=[f"Не удалось загрузить фундаментал: {e}"],
            )

    if not history:
        return Verdict(
            asset=ticker, action="HOLD", score=0.0, kind="share",
            warnings=["Нет фундаментала — тикер не найден на Smart-Lab"],
        )

    if _is_bank(history[0]):
        return _score_bank(ticker, history)
    return _score_nonfinancial(ticker, history)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    import logging
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s: %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.all:
        with Session() as s:
            tickers = StockFundamentalsCrud(s).get_all_tickers()
    else:
        tickers = args.tickers or ["SBER", "GAZP", "LKOH", "GMKN", "MTSS"]

    print(f"\n=== Скоринг {len(tickers)} тикеров ===\n")
    for t in tickers:
        v = score_stock(t)
        print(f"{v.emoji()} {v.asset:<8} [{v.kind:<6}] "
              f"score={v.score:5.1f}  {v.action}")
        for c in v.critical:
            print(f"    ⛔ {c}")
        for r in v.info:
            print(f"    ✅ {r}")
        for w in v.warnings:
            print(f"    ⚠️  {w}")
        print()