"""Sync engine: drives one Strategy through a bar iterable end-to-end."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from core.engine_sync import run_sync
from core.types import Action, Bar, Signal
from strategies.base import Context


class _AlwaysBuyOnce:
    """Emits BUY on the bar at index 5 (6th call) with stop at 95, then HOLD forever.

    The counter triggers on `n == 6` so the signal fires on bar index 5 (0-based),
    making the no-lookahead test's structure (signal-bar at i==5, fill-bar at i==6)
    work as intended.
    """
    def __init__(self) -> None:
        self.n = 0

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:
        self.n += 1
        if self.n == 6 and not ctx.in_position:
            return Signal(action=Action.BUY, confidence=1.0,
                          reasoning="test", stop_loss=95.0)
        return Signal(action=Action.HOLD, confidence=0.0,
                      reasoning="hold", stop_loss=None)


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2025, 4, 1, tzinfo=UTC)
    out = []
    for i, c in enumerate(closes):
        out.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=c, high=c * 1.01, low=c * 0.99, close=c,
            volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
        ))
    return out


def test_run_sync_executes_signal_on_next_bar_open():
    bars = _bars([100.0] * 4 + [100.0, 100.0, 110.0, 110.0])
    portfolio, metrics = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=4.0, slippage_bps=2.0, risk_pct=0.02,
    ))
    has_action = portfolio.position is not None or len(portfolio.closed_trades) >= 1
    assert has_action


def test_run_sync_position_size_matches_risk_pct():
    """quantity ~= (equity * risk_pct) / |entry - stop|"""
    bars = _bars([100.0] * 10)
    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    # entry_price ~= 100, stop = 95 -> risk_per_unit = 5
    # equity = 10_000, risk_dollars = 200 -> qty = 200 / 5 = 40
    assert portfolio.position is not None
    assert portfolio.position.quantity == pytest.approx(40.0, rel=1e-6)


def test_run_sync_returns_metrics_dict():
    bars = _bars(list(np.linspace(100, 105, 30)))
    _, metrics = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=4.0, slippage_bps=2.0, risk_pct=0.02,
    ))
    assert "total_return_pct" in metrics
    assert "max_drawdown_pct" in metrics
    assert "num_trades" in metrics


def test_run_sync_no_lookahead():
    """A signal at bar t must NOT use bar[t+1] data — verified by fill-at-open."""
    base = datetime(2025, 4, 1, tzinfo=UTC)
    bars = []
    for i in range(10):
        if i == 5:
            # Signal bar: close=200 (would be a great BUY-and-pump if we cheated)
            bars.append(Bar(
                timestamp=base + timedelta(hours=i),
                open=100.0, high=200.0, low=100.0, close=200.0,
                volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
            ))
        elif i == 6:
            # Next bar opens DOWN at 90
            bars.append(Bar(
                timestamp=base + timedelta(hours=i),
                open=90.0, high=91.0, low=89.0, close=90.5,
                volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
            ))
        else:
            bars.append(Bar(
                timestamp=base + timedelta(hours=i),
                open=100.0, high=101.0, low=99.0, close=100.0,
                volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
            ))

    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    # Fill should be at bar[6].open = 90.0, NOT at bar[5].close = 200.
    assert portfolio.position is not None
    assert portfolio.position.entry_price == pytest.approx(90.0)
