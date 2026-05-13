"""Traditional bot: indicator-confluence rule with SuperTrend stops."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from core.types import Action, Bar
from strategies.base import Context
from strategies.traditional import TraditionalStrategy


def _make_bars(closes: list[float]) -> list[Bar]:
    base = datetime(2025, 4, 1, tzinfo=UTC)
    bars = []
    for i, c in enumerate(closes):
        bars.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=c, high=c * 1.005, low=c * 0.995, close=c,
            volume=1000.0, taker_buy_volume=500.0,
            cvd=0.0, cvd_delta=0.0,
        ))
    return bars


def _flat_ctx(in_position: bool = False) -> Context:
    return Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.02,
                   in_position=in_position)


@pytest.mark.asyncio
async def test_warmup_returns_hold():
    s = TraditionalStrategy()
    bars = _make_bars([100.0] * 5)
    last = None
    for b in bars:
        last = await s.on_bar(b, _flat_ctx())
    assert last.action is Action.HOLD


@pytest.mark.asyncio
async def test_strong_uptrend_eventually_emits_buy():
    s = TraditionalStrategy()
    closes = list(np.linspace(100.0, 200.0, 100))
    bars = _make_bars(closes)
    actions = []
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        actions.append(sig.action)
    assert Action.BUY in actions, f"no BUY emitted; got {set(actions)}"


@pytest.mark.asyncio
async def test_strong_downtrend_eventually_emits_sell():
    s = TraditionalStrategy()
    closes = list(np.linspace(200.0, 100.0, 100))
    bars = _make_bars(closes)
    actions = []
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        actions.append(sig.action)
    assert Action.SELL in actions, f"no SELL emitted; got {set(actions)}"


@pytest.mark.asyncio
async def test_chop_returns_mostly_hold():
    s = TraditionalStrategy()
    rng = np.random.default_rng(seed=42)
    closes = list(100.0 + rng.normal(0, 0.3, 200))
    bars = _make_bars(closes)
    actions = []
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        actions.append(sig.action)
    holds = sum(1 for a in actions if a is Action.HOLD)
    assert holds / len(actions) > 0.7, (
        f"expected >70% HOLD in chop; got {holds}/{len(actions)}"
    )


@pytest.mark.asyncio
async def test_signal_carries_supertrend_stop_on_entry():
    s = TraditionalStrategy()
    closes = list(np.linspace(100.0, 200.0, 100))
    bars = _make_bars(closes)
    final_buy_sig = None
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        if sig.action is Action.BUY:
            final_buy_sig = sig
    assert final_buy_sig is not None
    assert final_buy_sig.stop_loss is not None
    assert final_buy_sig.stop_loss < bars[-1].close


@pytest.mark.asyncio
async def test_signal_confidence_in_unit_interval():
    s = TraditionalStrategy()
    closes = list(np.linspace(100.0, 200.0, 100))
    bars = _make_bars(closes)
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        assert 0.0 <= sig.confidence <= 1.0
