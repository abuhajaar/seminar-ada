"""Strategy protocol contract."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from core.types import Action, Bar, Signal
from strategies.base import Context, Strategy


def test_context_construction():
    ctx = Context(
        symbol="BTC/USDT",
        equity=10_000.0,
        risk_pct=0.02,
        in_position=False,
    )
    assert ctx.symbol == "BTC/USDT"
    assert ctx.equity == 10_000.0
    assert ctx.risk_pct == 0.02
    assert ctx.in_position is False


def test_strategy_is_protocol_and_async():
    assert hasattr(Strategy, "on_bar")
    sig = inspect.signature(Strategy.on_bar)
    assert "bar" in sig.parameters
    assert "ctx" in sig.parameters


@pytest.mark.asyncio
async def test_dummy_strategy_satisfies_protocol():
    class Dummy:
        async def on_bar(self, bar: Bar, ctx: Context) -> Signal:
            return Signal(
                action=Action.HOLD, confidence=0.0,
                reasoning="dummy", stop_loss=None,
            )

    d: Strategy = Dummy()  # structural typing must accept this
    bar = Bar(
        timestamp=datetime(2025, 4, 1, tzinfo=UTC),
        open=100.0, high=101.0, low=99.0, close=100.5,
        volume=1.0, taker_buy_volume=0.5, cvd=0.0, cvd_delta=0.0,
    )
    ctx = Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.02, in_position=False)
    sig = await d.on_bar(bar, ctx)
    assert sig.action is Action.HOLD
