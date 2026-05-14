"""Tests for `strategies.llm_agents.state` and `strategies.llm_agents.prompts`."""
from __future__ import annotations

from core.types import Action, AgentReport
from strategies.llm_agents.prompts import (
    build_decision_prompt,
    build_qabba_prompt,
    build_technical_prompt,
    build_visual_prompt,
)
from strategies.llm_agents.state import GraphState


def test_graph_state_typed_dict_has_required_keys():
    s: GraphState = {
        "bar_ts": 1,
        "features": {"ema_fast": 1.0},
        "image_b64": None,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }
    assert s["bar_ts"] == 1
    assert s["features"]["ema_fast"] == 1.0
    assert s["technical"] is None


def test_build_technical_prompt_includes_features():
    p = build_technical_prompt(
        {"ema_fast": 110.0, "ema_slow": 100.0, "rsi": 60.0, "macd_hist": 0.5}
    )
    assert "ema_fast=110" in p
    assert "ema_slow=100" in p
    assert "rsi=60" in p
    assert "macd_hist=0.5" in p
    # Mentions output format so the model knows to emit ACTION CONFIDENCE
    assert "BUY" in p and "SELL" in p and "HOLD" in p


def test_build_technical_prompt_skips_missing_keys():
    p = build_technical_prompt({"ema_fast": 100.0})
    assert "ema_fast=100" in p
    assert "ema_slow" not in p
    assert "rsi" not in p


def test_build_qabba_prompt_includes_cvd():
    p = build_qabba_prompt({"cvd_delta": 1234.5, "cvd": 9999.0})
    assert "cvd_delta=1234.5" in p
    assert "cvd=9999" in p


def test_build_qabba_prompt_handles_missing_cvd():
    p = build_qabba_prompt({})
    # Should still be a valid prompt with no key=value pairs but with format guidance
    assert "BUY" in p


def test_build_visual_prompt_mentions_chart():
    p = build_visual_prompt()
    assert "chart" in p.lower()
    assert "BUY" in p


def test_build_decision_prompt_summarises_reports():
    reports: dict[str, AgentReport | None] = {
        "technical": AgentReport(action=Action.BUY, confidence=0.7, rationale="x"),
        "visual": AgentReport(action=Action.HOLD, confidence=0.5, rationale="y"),
        "qabba": AgentReport(action=Action.BUY, confidence=0.8, rationale="z"),
    }
    p = build_decision_prompt(reports)
    assert "tech=BUY:0.70" in p
    assert "visual=HOLD:0.50" in p
    assert "qabba=BUY:0.80" in p


def test_build_decision_prompt_handles_missing_reports():
    reports: dict[str, AgentReport | None] = {
        "technical": None,
        "visual": None,
        "qabba": AgentReport(action=Action.BUY, confidence=1.0, rationale="z"),
    }
    p = build_decision_prompt(reports)
    assert "tech=NA" in p
    assert "visual=NA" in p
    assert "qabba=BUY:1.00" in p


def test_build_decision_prompt_handles_empty_dict():
    p = build_decision_prompt({})
    assert "tech=NA" in p
    assert "visual=NA" in p
    assert "qabba=NA" in p


def test_prompt_formatter_never_uses_scientific_notation():
    """Spec invariant: MockClient regex `key=(-?\\d+\\.?\\d*)` has no exponent
    support, so large CVD (>1e6) or tiny macd_hist (<1e-4) must NOT render as
    `1.23e+06` / `1e-05`. Confirms the `_fmt` hardening."""
    import re

    sci_re = re.compile(r"\d[eE][+-]?\d")  # only matches inside number literals

    p = build_qabba_prompt({"cvd": 1_234_567.0, "cvd_delta": 12_345_678.5})
    assert "1234567" in p
    assert "12345678.5" in p
    assert sci_re.search(p) is None

    p2 = build_technical_prompt({"macd_hist": 0.000012})
    assert "0.000012" in p2
    assert sci_re.search(p2) is None
