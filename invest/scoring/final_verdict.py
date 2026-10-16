"""Комплексный Verdict: базовый скоринг + перцентиль P/E + DCF."""
import logging

from invest.scoring.stock_score import score_stock
from invest.scoring.percentiles import pe_percentile
from invest.scoring.dcf import build_dcf
from invest.scoring.verdict import decide_action, clamp
from invest.scoring import thresholds as th

logger = logging.getLogger(__name__)


def final_verdict(ticker: str, auto_backfill: bool = True) -> dict:
    base = score_stock(ticker, auto_backfill=auto_backfill)

    pe_data = pe_percentile(ticker)
    dcf_data = build_dcf(ticker)

    score = base.score
    critical = list(base.critical)
    warnings = list(base.warnings)
    info = list(base.info)

    # ---- Перцентиль P/E ----
    if pe_data:
        pct = pe_data["percentile"]
        verdict = pe_data["verdict"]

        if verdict == "cheap":
            score += 10
            info.append(
                f"P/E {pe_data['current_pe']} — ниже "
                f"{int(pct * 100)}% исторических значений (дёшево)"
            )
        elif verdict == "expensive":
            score -= 10
            warnings.append(
                f"P/E {pe_data['current_pe']} — выше "
                f"{int(pct * 100)}% исторических значений (дорого)"
            )
        else:
            info.append(
                f"P/E {pe_data['current_pe']} — "
                f"{int(pct * 100)}-й перцентиль (справедливо)"
            )
    else:
        info.append("Нет истории P/E — перцентиль не посчитан")

    # ---- DCF ----
    notes = []
    if dcf_data:
        ups = dcf_data["upside_pct"]
        if dcf_data["verdict"] == "undervalued":
            score += 10
            info.append(
                f"DCF: апсайд {ups:+.1f}% "
                f"(fair {dcf_data['fair_price']} ₽ vs current "
                f"{dcf_data['current_price']} ₽)"
            )
        elif dcf_data["verdict"] == "overvalued":
            score -= 10
            warnings.append(
                f"DCF: переоценка {ups:+.1f}% "
                f"(fair {dcf_data['fair_price']} ₽ vs current "
                f"{dcf_data['current_price']} ₽)"
            )
        else:
            info.append(f"DCF: справедливо ({ups:+.1f}%)")
    else:
        # Для банков DCF не применяется
        if base.kind == "bank":
            notes.append("DCF не применяется для банков")
        else:
            from database.db import Session
            from database.fundamentals_crud import StockFundamentalsCrud
            with Session() as s:
                latest = StockFundamentalsCrud(s).get_latest(ticker)
            fcf = None
            if latest:
                try:
                    fcf = float(latest.fcf) if latest.fcf else None
                except (TypeError, ValueError):
                    pass
            if fcf is None or fcf <= 0:
                notes.append("DCF не применим: отрицательный FCF")
            else:
                notes.append("DCF не посчитан: недостаточно данных")

    score = clamp(score)
    action = decide_action(score, critical, warnings)

    return {
        "ticker": base.asset,
        "kind": base.kind,
        "action": action,
        "score": round(score, 1),
        "critical": critical,
        "warnings": warnings,
        "info": info,
        "notes": notes,
        "base_score": base.score,
        "pe_data": pe_data,
        "dcf_data": dcf_data,
    }


def print_final_verdict(ticker: str) -> None:
    v = final_verdict(ticker)

    emoji = {
        "BUY": "🟢", "HOLD": "🟡",
        "AVOID": "🔴", "STRONG_AVOID": "⛔",
    }[v["action"]]

    print(f"\n{emoji} {v['ticker']} [{v['kind']}] — "
          f"{v['action']} (score {v['score']}/100)")

    if v["critical"]:
        print("  ⛔ Критично:")
        for c in v["critical"]:
            print(f"    ⛔ {c}")

    if v["info"]:
        print("  Плюсы:")
        for r in v["info"]:
            print(f"    ✅ {r}")

    if v["warnings"]:
        print("  Риски:")
        for w in v["warnings"]:
            print(f"    ⚠️  {w}")

    if v["pe_data"]:
        pe = v["pe_data"]
        print(f"  P/E история: {pe['min']}…{pe['max']}, "
              f"median {pe['median']}, current {pe['current_pe']}, "
              f"percentile {int(pe['percentile'] * 100)}%")

    if v["dcf_data"]:
        d = v["dcf_data"]
        print(f"  DCF: fair {d['fair_price']} ₽ vs current "
              f"{d['current_price']} ₽ ({d['upside_pct']:+.1f}%)")

    if v["notes"]:
        print("  ℹ️ Примечания:")
        for n in v["notes"]:
            print(f"    ℹ️ {n}")


if __name__ == "__main__":
    import logging
    import sys

    logging.basicConfig(level=logging.WARNING)
    tickers = sys.argv[1:] or ["SBER", "GAZP", "LKOH", "GMKN", "MTSS"]
    for t in tickers:
        print_final_verdict(t)