"""Единый Verdict для оценки актива.

Используется как результат скоринга.
Разделяет предупреждения на три уровня:
- critical — блокируют BUY, компания опасна для покупки
- warnings — понижают, но не блокируют
- info     — нейтральная информация
"""
from dataclasses import dataclass, field
from typing import Literal


Action = Literal["BUY", "HOLD", "AVOID", "STRONG_AVOID"]


@dataclass
class Verdict:
    asset: str
    action: Action
    score: float
    kind: str = "share"

    critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # ← НОВОЕ

    metrics_used: dict = field(default_factory=dict)

    # ---------- Форматирование ----------

    def emoji(self) -> str:
        return {
            "BUY": "🟢",
            "HOLD": "🟡",
            "AVOID": "🔴",
            "STRONG_AVOID": "⛔",
        }[self.action]

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "action": self.action,
            "score": self.score,
            "kind": self.kind,
            "critical": self.critical,
            "warnings": self.warnings,
            "info": self.info,
            "metrics_used": self.metrics_used,
        }

    def __str__(self) -> str:
        return (f"{self.emoji()} {self.asset} ({self.kind}) — "
                f"{self.action} [{self.score:.0f}/100]")


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def add_score(score: float, delta: float, max_score: float = 100.0) -> float:
    return clamp(score + delta, 0.0, max_score)


def decide_action(
    score: float,
    critical: list[str],
    warnings: list[str],
) -> Action:
    """
    Финальное решение по action.

    Логика:
    - critical → AVOID (нельзя покупать)
    - score >= 75 и warnings ≤ 3 → BUY
    - score >= 65 и warnings ≤ 2 → BUY
    - score >= 40 → HOLD
    - score >= 25 → AVOID
    - score < 25  → STRONG_AVOID
    """
    from invest.scoring.thresholds import (
        SCORE_BUY_STRONG, SCORE_BUY_WEAK,
        SCORE_HOLD_MIN, SCORE_AVOID_MIN,
        MAX_WARNINGS_FOR_STRONG_BUY, MAX_WARNINGS_FOR_WEAK_BUY,
    )

    if critical:
        return "AVOID"

    n_warn = len(warnings)

    if score >= SCORE_BUY_STRONG and n_warn <= MAX_WARNINGS_FOR_STRONG_BUY:
        return "BUY"
    if score >= SCORE_BUY_WEAK and n_warn <= MAX_WARNINGS_FOR_WEAK_BUY:
        return "BUY"
    if score >= SCORE_HOLD_MIN:
        return "HOLD"
    if score >= SCORE_AVOID_MIN:
        return "AVOID"
    return "STRONG_AVOID"