"""LLMAgentStrategy: bridges the Strategy protocol to the 4-agent LangGraph.

These tests use ``MockClient`` and ``render_image=False`` so they stay fast and
deterministic and don't depend on mplfinance rendering.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.types import Action, Bar, Signal
from llm.client import MockClient
from strategies.base import Context
from strategies.llm_agents.strategy import WARMUP_BARS, LLMAgentStrategy


def _bar(i: int, *, close: float | None = None) -> Bar:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    c = close if close is not None else 50_000.0 + i * 10.0
    return Bar(
        timestamp=start + timedelta(hours=i),
        open=c - 5.0,
        high=c + 50.0,
        low=c - 50.0,
        close=c,
        volume=1.0,
        taker_buy_volume=0.6,
        cvd=100.0 * i,
        cvd_delta=100.0,
    )


def _ctx(in_position: bool = False) -> Context:
    return Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.01, in_position=in_position)


@pytest.mark.asyncio
async def test_warmup_returns_hold_without_invoking_graph() -> None:
    """During warmup the strategy must NOT call the graph."""
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
    )
    sig: Signal | None = None
    for i in range(WARMUP_BARS - 1):
        sig = await strat.on_bar(_bar(i), _ctx())
    assert sig is not None
    assert sig.action is Action.HOLD
    assert sig.confidence == 0.0
    assert "warmup" in sig.reasoning


@pytest.mark.asyncio
async def test_returns_signal_after_warmup_bullish_ramp() -> None:
    """After warmup, the strategy returns a well-formed Signal.

    We only assert the *shape* of the return — action in {BUY, SELL, HOLD},
    confidence in [0, 1], rationale containing the decision-node audit trail
    — because the actual decision depends on weighted-consensus math that is
    covered exhaustively in test_llm_graph.py / test_llm_decision.py.
    """
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
    )
    last: Signal | None = None
    # +1 past WARMUP so the gate clears.
    for i in range(WARMUP_BARS + 5):
        last = await strat.on_bar(_bar(i), _ctx())
    assert last is not None
    assert isinstance(last, Signal)
    assert last.action in (Action.BUY, Action.SELL, Action.HOLD)
    assert 0.0 <= last.confidence <= 1.0
    # Rationale comes from the deterministic decision node.
    assert "buy=" in last.reasoning
    assert "sell=" in last.reasoning


@pytest.mark.asyncio
async def test_stop_loss_is_none_for_llm_strategy() -> None:
    """LLM bot defers stop placement to broker default (spec)."""
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
    )
    last: Signal | None = None
    for i in range(WARMUP_BARS + 2):
        last = await strat.on_bar(_bar(i), _ctx())
    assert last is not None
    assert last.stop_loss is None


@pytest.mark.asyncio
async def test_strategy_routes_through_cached_client_per_agent(tmp_path) -> None:
    """Strategy must invoke the graph via the injected (Cached) client.

    Indirectly validates the bar_ts plumbing: CachedClient writes one file per
    (model, agent, prompt_hash, image_hash, bar_ts) tuple. After running past
    warmup, all three analyst agents must have cache entries in their own
    sub-directories — this confirms (a) the strategy uses the injected client
    (not a fresh one), (b) bar_ts is hashable / serializable, and (c) the
    layout matches spec §6.
    """
    from llm.cache import CachedClient

    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    strat = LLMAgentStrategy(client=cached, model="mock", render_image=False)
    for i in range(WARMUP_BARS + 2):
        await strat.on_bar(_bar(i), _ctx())
    files = list(tmp_path.rglob("*.json"))
    assert len(files) > 0
    # Cache layout: <cache_dir>/<model_safe>/<agent>/<key>.json
    agents = {p.parent.name for p in files}
    assert agents == {"technical", "visual", "qabba"}


@pytest.mark.asyncio
async def test_render_image_true_path_does_not_crash() -> None:
    """Exercise the mplfinance render path end-to-end (one bar past warmup)."""
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        image_window_bars=30,
        render_image=True,
    )
    last: Signal | None = None
    for i in range(WARMUP_BARS + 1):
        last = await strat.on_bar(_bar(i), _ctx())
    assert last is not None
    assert isinstance(last, Signal)
