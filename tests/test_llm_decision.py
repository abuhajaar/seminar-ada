"""Tests for the deterministic Decision node (spec §7.2 weighted consensus).

Weights: 0.40 QABBA / 0.35 Visual / 0.25 Technical. Threshold > 0.50. HOLD on
tie or sub-threshold.
"""
from __future__ import annotations

import pytest

from core.types import Action, AgentReport
from strategies.llm_agents.nodes.decision import (
    THRESHOLD,
    W_QABBA,
    W_TECH,
    W_VISUAL,
    decision_node,
)
from strategies.llm_agents.state import GraphState


def _state(tech, visual, qabba) -> GraphState:
    return {
        "bar_ts": 1,
        "features": {},
        "image_b64": None,
        "model": "mock",
        "technical": tech,
        "visual": visual,
        "qabba": qabba,
        "decision": None,
    }


def test_weights_sum_to_one():
    assert W_QABBA + W_VISUAL + W_TECH == pytest.approx(1.0)  # noqa: SIM300


def test_threshold_is_one_half():
    assert THRESHOLD == 0.50


async def test_decision_buy_when_all_buy():
    s = _state(
        AgentReport(action=Action.BUY, confidence=0.8, rationale="t"),
        AgentReport(action=Action.BUY, confidence=0.7, rationale="v"),
        AgentReport(action=Action.BUY, confidence=0.9, rationale="q"),
    )
    out = await decision_node(s)
    assert out["decision"].action is Action.BUY
    # buy_score = 0.40*0.9 + 0.35*0.7 + 0.25*0.8 = 0.36 + 0.245 + 0.20 = 0.805
    assert out["decision"].confidence == pytest.approx(0.805)


async def test_decision_hold_when_split_under_threshold():
    s = _state(
        AgentReport(action=Action.BUY, confidence=0.5, rationale="t"),
        AgentReport(action=Action.SELL, confidence=0.5, rationale="v"),
        AgentReport(action=Action.HOLD, confidence=0.5, rationale="q"),
    )
    out = await decision_node(s)
    assert out["decision"].action is Action.HOLD


async def test_decision_qabba_dominates_due_to_largest_weight():
    s = _state(
        AgentReport(action=Action.SELL, confidence=0.9, rationale="t"),
        AgentReport(action=Action.SELL, confidence=0.9, rationale="v"),
        AgentReport(action=Action.BUY, confidence=1.0, rationale="q"),
    )
    out = await decision_node(s)
    # buy_score = 0.40*1.0 = 0.40 ; sell_score = 0.35*0.9 + 0.25*0.9 = 0.315+0.225 = 0.54
    # 0.54 > 0.50 and > 0.40 → SELL
    assert out["decision"].action is Action.SELL
    assert out["decision"].confidence == pytest.approx(0.54)


async def test_decision_handles_none_reports_gracefully():
    s = _state(None, None, AgentReport(action=Action.BUY, confidence=1.0, rationale="q"))
    out = await decision_node(s)
    # buy_score = 0.40, threshold > 0.50 → HOLD
    assert out["decision"].action is Action.HOLD


async def test_decision_all_none_returns_hold():
    s = _state(None, None, None)
    out = await decision_node(s)
    assert out["decision"].action is Action.HOLD


async def test_decision_buy_just_above_threshold():
    """buy_score=0.51 (just above 0.50) and clearly dominates sell_score=0.25 → BUY."""
    s = _state(
        AgentReport(action=Action.SELL, confidence=1.0, rationale="t"),  # 0.25 sell
        AgentReport(action=Action.BUY, confidence=1.0, rationale="v"),  # 0.35 buy
        AgentReport(action=Action.BUY, confidence=0.40, rationale="q"),  # 0.16 buy
    )
    # buy_score=0.51, sell_score=0.25 → BUY
    out = await decision_node(s)
    assert out["decision"].action is Action.BUY


async def test_decision_exact_threshold_is_not_above():
    """buy_score == THRESHOLD must NOT trigger BUY (spec: > 0.50, strict)."""
    # Make buy_score exactly 0.50: 0.25*1.0 + 0.25*1.0... can't with these weights.
    # 0.40 + 0.10 → q=1.0 buy + something=0.10. Use tech_conf=0.4 → 0.25*0.4=0.10.
    s = _state(
        AgentReport(action=Action.BUY, confidence=0.4, rationale="t"),   # 0.10
        None,
        AgentReport(action=Action.BUY, confidence=1.0, rationale="q"),   # 0.40
    )
    # buy_score = 0.50, not > 0.50 → HOLD
    out = await decision_node(s)
    assert out["decision"].action is Action.HOLD


async def test_decision_rationale_contains_scores():
    s = _state(
        AgentReport(action=Action.BUY, confidence=0.5, rationale="t"),
        AgentReport(action=Action.SELL, confidence=0.5, rationale="v"),
        AgentReport(action=Action.HOLD, confidence=0.5, rationale="q"),
    )
    out = await decision_node(s)
    rat = out["decision"].rationale
    assert "buy=" in rat
    assert "sell=" in rat
