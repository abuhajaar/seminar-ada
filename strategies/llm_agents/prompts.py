"""Prompt templates for the 4 LLM agents.

Kept terse and explicit so MockClient regex extraction is reliable, the parser
in ``nodes/_parse.py`` can find ``ACTION CONFIDENCE`` consistently, and real
OpenRouter calls stay within the per-run budget cap.
"""
from __future__ import annotations

from core.types import AgentReport

_ACTION_FORMAT = (
    "Output one of BUY, SELL, HOLD followed by a confidence in [0,1] and a "
    "one-line rationale.\nFormat: <ACTION> <CONFIDENCE> <RATIONALE>"
)
# NOTE: ``_ACTION_FORMAT`` contains the literal tokens "BUY", "SELL", "HOLD".
# MockClient.decision tallies BUY/SELL word-boundary matches across the prompt;
# the format string contributes one of each so they cancel. Keep these three
# tokens balanced if you edit this constant — otherwise MockClient's decision
# branch will skew before votes are counted.


def _fmt(v: float) -> str:
    """Compact numeric formatter that never emits scientific notation.

    ``f"{v:g}"`` switches to sci notation for ``|v| < 1e-4`` or ``|v| >= 1e6``,
    which breaks MockClient's regex ``key=(-?\\d+\\.?\\d*)`` (no exponent
    support). Real CVD values on Binance routinely exceed 1e6, so we render
    with fixed precision and strip trailing zeros instead.
    """
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def build_technical_prompt(features: dict[str, float]) -> str:
    """Technical analyst: EMA/RSI/MACD/ADX readings."""
    keys = ("ema_fast", "ema_slow", "rsi", "macd_hist", "adx")
    parts = [f"{k}={_fmt(features[k])}" for k in keys if k in features]
    body = " ".join(parts)
    return (
        "You are a technical analyst. Given these indicator readings, "
        f"{_ACTION_FORMAT}\nFeatures: {body}"
    )


def build_qabba_prompt(features: dict[str, float]) -> str:
    """Quantitative order-flow (QABBA) analyst: CVD readings."""
    parts = []
    if "cvd" in features:
        parts.append(f"cvd={_fmt(features['cvd'])}")
    if "cvd_delta" in features:
        parts.append(f"cvd_delta={_fmt(features['cvd_delta'])}")
    body = " ".join(parts)
    return (
        "You are a quantitative order-flow analyst (QABBA). Given the "
        f"cumulative volume delta readings, {_ACTION_FORMAT}\nFeatures: {body}"
    )


def build_visual_prompt() -> str:
    """Chart-pattern analyst (Visual): consumes the attached candlestick image."""
    return (
        "You are a chart-pattern analyst. Examine the attached candlestick "
        f"chart and {_ACTION_FORMAT}"
    )


def _vote(name: str, report: AgentReport | None) -> str:
    if report is None:
        return f"{name}=NA"
    return f"{name}={report.action.name}:{report.confidence:.2f}"


def build_decision_prompt(reports: dict[str, AgentReport | None]) -> str:
    """Decision arbiter prompt — included for transparency/logging only.

    The Decision *node* is deterministic (spec §7.2); this prompt exists so that
    a future audit run can ask the LLM to comment on the math without altering
    it.
    """
    tech = _vote("tech", reports.get("technical"))
    visual = _vote("visual", reports.get("visual"))
    qabba = _vote("qabba", reports.get("qabba"))
    return (
        "You are the decision arbiter. Three analysts have voted. "
        f"{_ACTION_FORMAT}\nVotes: {tech} {visual} {qabba}"
    )
