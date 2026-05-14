"""Tests for `strategies.llm_agents.nodes` — _parse + 3 analyst nodes."""
from __future__ import annotations

import pytest

from core.types import Action
from llm.client import MockClient
from strategies.llm_agents.nodes._parse import parse_response
from strategies.llm_agents.nodes.qabba import qabba_node
from strategies.llm_agents.nodes.technical import technical_node
from strategies.llm_agents.nodes.visual import visual_node
from strategies.llm_agents.state import GraphState


def test_parse_response_buy():
    r = parse_response("BUY 0.72 strong cross")
    assert r.action is Action.BUY
    assert r.confidence == pytest.approx(0.72)
    assert "cross" in r.rationale


def test_parse_response_sell():
    r = parse_response("SELL 0.40 weak")
    assert r.action is Action.SELL
    assert r.confidence == pytest.approx(0.40)


def test_parse_response_hold_default_on_garbage():
    r = parse_response("nonsense")
    assert r.action is Action.HOLD
    assert 0.0 <= r.confidence <= 1.0


def test_parse_response_clamps_confidence_high():
    r = parse_response("BUY 1.7 too eager")
    assert r.confidence == 1.0


def test_parse_response_clamps_confidence_low():
    r = parse_response("SELL -0.3 weird")
    assert r.confidence == 0.0


def test_parse_response_case_insensitive():
    r = parse_response("buy 0.6 lowercase")
    assert r.action is Action.BUY


def test_parse_response_missing_confidence_defaults_to_half():
    r = parse_response("HOLD just an action")
    assert r.action is Action.HOLD
    assert r.confidence == 0.5


def test_parse_response_rationale_truncated_at_200_chars():
    long = "BUY 0.5 " + "x" * 500
    r = parse_response(long)
    assert len(r.rationale) <= 200


def _state(features: dict[str, float], image_b64: str | None = None) -> GraphState:
    return {
        "bar_ts": 1,
        "features": features,
        "image_b64": image_b64,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }


async def test_technical_node_writes_report():
    client = MockClient()
    s = _state({"ema_fast": 110, "ema_slow": 100, "macd_hist": 0.5, "rsi": 60})
    out = await technical_node(s, client=client)
    assert out["technical"] is not None
    assert out["technical"].action is Action.BUY


async def test_technical_node_sell_on_bearish_features():
    client = MockClient()
    s = _state({"ema_fast": 90, "ema_slow": 100, "macd_hist": -0.5, "rsi": 40})
    out = await technical_node(s, client=client)
    assert out["technical"].action is Action.SELL


async def test_qabba_node_sell_on_negative_cvd():
    client = MockClient()
    s = _state({"cvd_delta": -500, "cvd": -1000})
    out = await qabba_node(s, client=client)
    assert out["qabba"].action is Action.SELL


async def test_qabba_node_buy_on_positive_cvd():
    client = MockClient()
    s = _state({"cvd_delta": 500, "cvd": 1000})
    out = await qabba_node(s, client=client)
    assert out["qabba"].action is Action.BUY


async def test_visual_node_hold_with_mock():
    client = MockClient()
    s = _state({}, image_b64=None)
    out = await visual_node(s, client=client)
    assert out["visual"].action is Action.HOLD


async def test_nodes_preserve_other_state_keys():
    """Each node must not clobber peer slots written in parallel."""
    client = MockClient()
    s = _state({"ema_fast": 110, "ema_slow": 100, "macd_hist": 0.5})
    out = await technical_node(s, client=client)
    # bar_ts/model/features preserved
    assert out["bar_ts"] == s["bar_ts"]
    assert out["model"] == s["model"]
    assert out["features"] == s["features"]


async def test_cached_client_receives_bar_ts(tmp_path):
    """Technical node must forward bar_ts when client is a CachedClient."""
    from llm.cache import CachedClient

    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    s = _state({"ema_fast": 110, "ema_slow": 100, "macd_hist": 0.5})
    out = await technical_node(s, client=cached)
    assert out["technical"] is not None
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1  # confirms bar_ts was forwarded (otherwise CachedClient would TypeError)
