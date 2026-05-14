"""End-to-end LangGraph wiring tests using the deterministic MockClient.

These verify:
1. The compiled graph runs all three analyst nodes and the decision node.
2. The deterministic weighted-consensus guardrail (spec §7.2) is enforced —
   majority vote alone is NOT enough; the side score must exceed 0.50.
3. Symmetric bull/bear inputs produce symmetric (HOLD) outputs at MockClient
   confidence levels, proving the threshold gate is active.
"""
from __future__ import annotations

import pytest

from core.types import Action
from llm.client import MockClient
from strategies.llm_agents.graph import build_graph


def _initial_state(features: dict[str, float]) -> dict:
    return {
        "bar_ts": 1,
        "features": features,
        "image_b64": None,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }


@pytest.mark.asyncio
async def test_build_graph_runs_end_to_end_with_mock_client() -> None:
    graph = build_graph(client=MockClient())
    initial = _initial_state(
        {
            "ema_fast": 110.0,
            "ema_slow": 100.0,
            "macd_hist": 0.5,
            "rsi": 60.0,
            "cvd": 1000.0,
            "cvd_delta": 500.0,
        }
    )
    final = await graph.ainvoke(initial)

    # All analyst slots filled.
    assert final["technical"] is not None
    assert final["visual"] is not None
    assert final["qabba"] is not None
    assert final["decision"] is not None

    # Bullish features: tech=BUY@0.70, qabba=BUY@0.65, visual=HOLD@0.50.
    assert final["technical"].action is Action.BUY
    assert final["qabba"].action is Action.BUY
    assert final["visual"].action is Action.HOLD

    # buy_score = 0.40*0.65 + 0.25*0.70 = 0.435 < 0.50 → HOLD per guardrail.
    assert final["decision"].action is Action.HOLD


@pytest.mark.asyncio
async def test_build_graph_sell_path_below_threshold_holds() -> None:
    graph = build_graph(client=MockClient())
    initial = _initial_state(
        {
            "ema_fast": 90.0,
            "ema_slow": 100.0,
            "macd_hist": -0.5,
            "rsi": 40.0,
            "cvd": -1000.0,
            "cvd_delta": -500.0,
        }
    )
    final = await graph.ainvoke(initial)

    assert final["technical"].action is Action.SELL
    assert final["qabba"].action is Action.SELL
    assert final["visual"].action is Action.HOLD

    # sell_score = 0.40*0.65 + 0.25*0.70 = 0.435 < 0.50 → HOLD per guardrail.
    assert final["decision"].action is Action.HOLD


@pytest.mark.asyncio
async def test_build_graph_decision_rationale_includes_weights() -> None:
    """Spec §7.2: rationale must record the math so reviewers can audit it."""
    graph = build_graph(client=MockClient())
    final = await graph.ainvoke(
        _initial_state(
            {
                "ema_fast": 110.0,
                "ema_slow": 100.0,
                "macd_hist": 0.5,
                "rsi": 60.0,
                "cvd": 1000.0,
                "cvd_delta": 500.0,
            }
        )
    )
    rationale = final["decision"].rationale
    assert "buy=" in rationale
    assert "sell=" in rationale
    assert "Q=0.4" in rationale
    assert "V=0.35" in rationale
    assert "T=0.25" in rationale
    assert "thr=0.5" in rationale


@pytest.mark.asyncio
async def test_build_graph_returns_compiled_object_reusable_across_invocations() -> None:
    """A compiled graph must be safe to invoke multiple times with different inputs."""
    graph = build_graph(client=MockClient())
    bull = await graph.ainvoke(
        _initial_state(
            {
                "ema_fast": 110.0,
                "ema_slow": 100.0,
                "macd_hist": 0.5,
                "rsi": 60.0,
                "cvd": 1000.0,
                "cvd_delta": 500.0,
            }
        )
    )
    bear = await graph.ainvoke(
        _initial_state(
            {
                "ema_fast": 90.0,
                "ema_slow": 100.0,
                "macd_hist": -0.5,
                "rsi": 40.0,
                "cvd": -1000.0,
                "cvd_delta": -500.0,
            }
        )
    )
    assert bull["technical"].action is Action.BUY
    assert bear["technical"].action is Action.SELL
