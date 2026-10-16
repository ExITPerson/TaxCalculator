"""Пороги и правила для скоринга.

Все константы — здесь, чтобы не разбрасывать по коду.
"""

# ============================================================
# Пороги action (score)
# ============================================================

SCORE_BUY_STRONG = 75       # ≥ 75 и нет critical → BUY
SCORE_BUY_WEAK = 65         # ≥ 65, critical нет, warnings ≤ 2 → BUY
SCORE_HOLD_MIN = 40         # ≥ 40 → HOLD
SCORE_AVOID_MIN = 25        # ≥ 25 → AVOID, < 25 → STRONG_AVOID

# Максимум warnings для BUY на каждом уровне
MAX_WARNINGS_FOR_STRONG_BUY = 3
MAX_WARNINGS_FOR_WEAK_BUY = 2


# ============================================================
# Флаги аномалий: какие критичны
# ============================================================

# Эти флаги → AVOID (нельзя покупать)
CRITICAL_ANOMALY_FLAGS = {
    "loss_making",       # убыток
    "negative_equity",   # отрицательный капитал
}

# Эти флаги → только warning (не блокируют)
WARNING_ANOMALY_FLAGS = {
    "roe_anomaly",
    "roa_anomaly",
    "payout_anomaly",
    "revenue_anomaly",
    "ebitda_anomaly",
}


# ============================================================
# Нефинансовые: пороги метрик
# ============================================================

# ROIC / ROE
ROIC_BUY = 0.15             # > 15% — создаёт стоимость
ROIC_OK = 0.08              # > 8% — приемлемо

# EBITDA margin
EBITDA_MARGIN_BUY = 0.20
EBITDA_MARGIN_OK = 0.10

# FCF / Revenue
FCF_REVENUE_BUY = 0.10
FCF_REVENUE_OK = 0.05
FCF_REVENUE_CRITICAL = 0.0   # ← было -0.10, стало 0.0

# Долг / EBITDA
DEBT_EBITDA_OK = 1.0
DEBT_EBITDA_WARN = 2.5
DEBT_EBITDA_CRITICAL = 4.0

# Покрытие процентов
INTEREST_COVERAGE_BUY = 5.0
INTEREST_COVERAGE_OK = 3.0
INTEREST_COVERAGE_CRITICAL = 2.0

# P/E
PE_BUY = 15.0
PE_WARN = 30.0

# P/E перцентиль
PE_PERCENTILE_CHEAP = 0.30
PE_PERCENTILE_EXPENSIVE = 0.70

# P/B
PB_BUY = 1.5
PB_WARN = 3.0

# EV/EBITDA
EV_EBITDA_BUY = 5.0
EV_EBITDA_WARN = 10.0

# Payout
PAYOUT_MIN = 0.20
PAYOUT_MAX = 0.70
PAYOUT_CRITICAL = 2.0          # > 200% — критично

# DCF upside
DCF_UPSIDE_BUY = 0.20          # +20%
DCF_UPSIDE_WARN = -0.20        # -20%

# FCF Yield
FCF_YIELD_BUY = 0.10
FCF_YIELD_OK = 0.05

# D/E
DE_BUY = 0.5
DE_WARN = 1.5


# ============================================================
# Банки: пороги метрик
# ============================================================

# ROE
BANK_ROE_BUY = 0.20
BANK_ROE_OK = 0.15

# ROA
BANK_ROA_BUY = 0.02
BANK_ROA_OK = 0.01

# NIM
BANK_NIM_BUY = 0.05
BANK_NIM_OK = 0.03

# Payout
BANK_PAYOUT_MIN = 0.20
BANK_PAYOUT_MAX = 0.60
BANK_PAYOUT_WARN = 0.80