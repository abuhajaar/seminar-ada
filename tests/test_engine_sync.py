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
    # (Position is auto-closed at end-of-run; verify quantity via the
    # closed-trade record.)
    assert len(portfolio.closed_trades) == 1
    assert portfolio.closed_trades[0].qty == pytest.approx(40.0, rel=1e-6)


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
    # (Position is now auto-closed at end-of-run; verify via the closed_trades
    # entry instead of `portfolio.position`.)
    assert len(portfolio.closed_trades) == 1
    assert portfolio.closed_trades[0].entry_price == pytest.approx(90.0)


def test_run_sync_closes_open_position_at_end_of_run():
    """End-of-run accounting invariant.

    A position still open on the last bar must be synth-closed at that bar's
    close so that ``portfolio.closed_trades`` reflects every position taken.
    Without this, ``compute_metrics`` reads `closed_trades` (excludes the
    open leg) while `equity_curve` includes the mark-to-market of the open
    position — they disagree, and ``win_rate``/``profit_factor``/``num_trades``
    silently exclude the unrealized final trade.

    See run-2 (2026-05-14): equity Δ ≠ Σ pnl by ~$1,590 because the open BUY
    was never closed before metrics ran.
    """
    # 10 bars, all flat at 100; strategy buys at bar index 5 with stop at 95.
    # Bar low is 99 so stop never triggers — position stays open to the end.
    bars = _bars([100.0] * 10)
    portfolio, metrics = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    # Invariant 1: no dangling position.
    assert portfolio.position is None, (
        "engine must close any open position at end of run"
    )
    # Invariant 2: the BUY that fired is reflected as a closed trade.
    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    # Invariant 3: synth-close uses the LAST bar's close as exit_price,
    # and the LAST bar's timestamp as exit_ts. Last bar index is 9.
    assert trade.exit_price == pytest.approx(100.0)
    assert trade.exit_ts == bars[-1].timestamp
    # Invariant 4: metrics include the synth-closed trade.
    assert metrics["num_trades"] == 1


def test_run_sync_does_not_double_close_when_flat_at_end():
    """If the position was already closed naturally before the last bar, the
    end-of-run close-out is a no-op — no spurious trade appended."""
    # 10 bars flat at 100, but on bar 7 we drop low enough to trigger the stop.
    base = datetime(2025, 4, 1, tzinfo=UTC)
    bars = []
    for i in range(10):
        close = 100.0
        low = 94.0 if i == 7 else 99.0  # stop=95 triggers at i==7
        bars.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=close, high=close * 1.01, low=low, close=close,
            volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
        ))
    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    assert portfolio.position is None
    # Exactly one trade (the stopped-out BUY); no phantom end-of-run close.
    assert len(portfolio.closed_trades) == 1
    assert portfolio.closed_trades[0].exit_price == pytest.approx(95.0)


def test_run_sync_equity_delta_matches_sum_of_trade_pnl():
    """End-of-run close ensures Σ trade.pnl == equity[-1] − equity[0]
    (zero fees, zero slippage)."""
    bars = _bars([100.0] * 10)
    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    curve = portfolio.equity_curve()
    equity_delta = curve[-1][1] - 10_000.0
    pnl_sum = sum(t.pnl for t in portfolio.closed_trades)
    assert pnl_sum == pytest.approx(equity_delta, abs=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# H4: reject stop on wrong side of price.
# ──────────────────────────────────────────────────────────────────────────


class _BuyWithWrongSidedStop:
    """Emits BUY with stop ABOVE entry — an invalid long stop placement.

    For a long position the stop must sit below the entry price; otherwise
    the implied risk is negative and `size_position` (which uses abs()) will
    still happily produce a position size that is sized off "negative risk".
    The next bar's stop check then triggers immediately, blowing past the
    configured ``risk_pct`` and inflating trade count.
    """

    def __init__(self) -> None:
        self.n = 0

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:  # noqa: ARG002
        self.n += 1
        if self.n == 6 and not ctx.in_position:
            # bar.close == 100; stop=105 is ON THE WRONG SIDE for a long.
            return Signal(action=Action.BUY, confidence=1.0,
                          reasoning="invalid", stop_loss=105.0)
        return Signal(action=Action.HOLD, confidence=0.0,
                      reasoning="hold", stop_loss=None)


class _SellWithWrongSidedStop:
    """Emits SELL (short) with stop BELOW entry — invalid short stop placement."""

    def __init__(self) -> None:
        self.n = 0

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:  # noqa: ARG002
        self.n += 1
        if self.n == 6 and not ctx.in_position:
            # bar.close == 100; stop=95 is ON THE WRONG SIDE for a short.
            return Signal(action=Action.SELL, confidence=1.0,
                          reasoning="invalid", stop_loss=95.0)
        return Signal(action=Action.HOLD, confidence=0.0,
                      reasoning="hold", stop_loss=None)


def test_run_sync_rejects_wrong_sided_long_stop():
    """Engine must NOT open a long position when stop_loss >= entry price.

    Without this guard the strategy can silently blow `risk_pct`: the next
    bar's `check_stops` triggers immediately, fees stack, and the trade
    looks like a normal stop-out in the metrics while in fact the position
    should have been refused at entry.
    """
    bars = _bars([100.0] * 10)
    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_BuyWithWrongSidedStop(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    # No position should ever have been opened ⇒ no closed trades.
    assert portfolio.closed_trades == [], (
        f"engine accepted a wrong-sided long stop: trades={portfolio.closed_trades}"
    )
    assert portfolio.position is None
    # Equity must be untouched (zero fees, zero pnl).
    curve = portfolio.equity_curve()
    assert curve[-1][1] == pytest.approx(10_000.0, abs=1e-9)


def test_run_sync_rejects_wrong_sided_short_stop():
    """Symmetric: SELL with stop below entry must also be refused."""
    bars = _bars([100.0] * 10)
    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_SellWithWrongSidedStop(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    assert portfolio.closed_trades == []
    assert portfolio.position is None
    curve = portfolio.equity_curve()
    assert curve[-1][1] == pytest.approx(10_000.0, abs=1e-9)


# ──────────────────────────────────────────────────────────────────────────
# H5: position sizing must account for fees + slippage so the realized
# loss on a stop-out does not exceed `risk_pct`.
# ──────────────────────────────────────────────────────────────────────────


class _BuyAtSixThenHold:
    """Emits one BUY on the 6th call with a configurable stop."""

    def __init__(self, stop_loss: float) -> None:
        self.n = 0
        self.stop_loss = stop_loss

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:  # noqa: ARG002
        self.n += 1
        if self.n == 6 and not ctx.in_position:
            return Signal(action=Action.BUY, confidence=1.0,
                          reasoning="size-test", stop_loss=self.stop_loss)
        return Signal(action=Action.HOLD, confidence=0.0,
                      reasoning="hold", stop_loss=None)


def test_realized_stop_loss_respects_risk_pct():
    """Round-trip invariant: when fees + slippage are non-zero, the realized
    PnL of a stop-out must be at most ``equity * risk_pct`` (within float
    tolerance) — never more.

    Setup: BUY at bar 6 (fills at bar 7 open). Stop is set 5% below the
    close on the signal bar. Bar 8 dips to 95 → stop triggers. We assert
    the realized loss stays inside the configured 2% risk budget.

    Pre-fix `size_position` ignored fee + slippage drag, so the realized
    loss for any non-trivial fee budget exceeded the cap (audit H5).
    """
    # Bars: flat at 100 until bar 7 (zero-indexed 6) where price is still
    # 100, then bar 8 dips to 94 (stop at 95 hits).
    closes = [100.0] * 7 + [94.0] + [100.0] * 2  # 10 bars total
    bars = _bars(closes)
    # Override bar 8 low so the stop at 95 is breached cleanly.
    bars[7] = Bar(
        timestamp=bars[7].timestamp,
        open=100.0, high=100.0, low=94.0, close=94.0,
        volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
    )
    risk_pct = 0.02
    initial = 10_000.0
    portfolio, _ = asyncio.run(run_sync(
        bars=bars,
        strategy=_BuyAtSixThenHold(stop_loss=95.0),
        symbol="X", initial_balance=initial,
        taker_fee_bps=4.0, slippage_bps=2.0, risk_pct=risk_pct,
    ))
    assert len(portfolio.closed_trades) == 1, (
        f"expected 1 closed trade, got {portfolio.closed_trades}"
    )
    realized_loss = -portfolio.closed_trades[0].pnl  # positive number for a loss
    cap = initial * risk_pct
    # Allow a small float tolerance; reject any meaningful overshoot.
    assert realized_loss <= cap + 1e-6, (
        f"realized loss ${realized_loss:.4f} exceeds risk cap ${cap:.4f}; "
        f"sizer ignored fees/slippage"
    )
