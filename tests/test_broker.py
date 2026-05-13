"""Broker: queue orders at bar t, fill at bar[t+1].open with fees + slippage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.broker import Broker
from core.portfolio import Portfolio
from core.types import Action, Bar, Order


def _bar(hour: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        timestamp=datetime(2025, 4, 1, hour, 0, tzinfo=UTC),
        open=open_, high=high, low=low, close=close,
        volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
    )


def test_queued_order_fills_on_next_bar_open_buy():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    order = Order(
        symbol="BTC/USDT", action=Action.BUY, quantity=10.0,
        stop_loss=95.0, created_ts_ms=0,
    )
    b.queue(order)
    # Next bar opens at 100; BUY slips up by 2 bps → 100.02
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.5, close=100.5)
    b.fill_pending(next_bar)
    assert p.position is not None
    assert p.position.entry_price == pytest.approx(100.02)
    # Notional 1000.2; fee 4 bps = 0.40008; cash = 10000 - 1000.2 - 0.40008
    assert p.cash == pytest.approx(10_000.0 - 1000.2 - 0.40008)


def test_queued_order_fills_on_next_bar_open_sell_short():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    order = Order(
        symbol="BTC/USDT", action=Action.SELL, quantity=10.0,
        stop_loss=105.0, created_ts_ms=0,
    )
    b.queue(order)
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.0, close=100.5)
    b.fill_pending(next_bar)
    # SELL slips down by 2 bps → 99.98
    assert p.position is not None
    assert p.position.entry_price == pytest.approx(99.98)
    assert p.cash == pytest.approx(10_000.0 + 999.8 - 0.39992)


def test_sell_when_long_closes_position():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    # Open long manually at 100
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=95.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    # Now broker receives a SELL while long → it should close, not flip to short
    b.queue(Order(
        symbol="BTC/USDT", action=Action.SELL, quantity=10.0,
        stop_loss=None, created_ts_ms=0,
    ))
    next_bar = _bar(1, open_=110.0, high=111.0, low=109.0, close=110.5)
    b.fill_pending(next_bar)
    assert p.position is None
    assert len(p.closed_trades) == 1
    # Exit slips down 2 bps for a SELL fill: 109.978
    assert p.closed_trades[0].exit_price == pytest.approx(109.978)


def test_buy_when_short_closes_position():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.SELL, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=105.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    b.queue(Order(
        symbol="BTC/USDT", action=Action.BUY, quantity=10.0,
        stop_loss=None, created_ts_ms=0,
    ))
    next_bar = _bar(1, open_=90.0, high=91.0, low=89.0, close=90.5)
    b.fill_pending(next_bar)
    assert p.position is None
    assert p.closed_trades[0].exit_price == pytest.approx(90.018)


def test_hold_action_is_noop():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    b.queue(Order(
        symbol="BTC/USDT", action=Action.HOLD, quantity=0.0,
        stop_loss=None, created_ts_ms=0,
    ))
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.0, close=100.5)
    b.fill_pending(next_bar)
    assert p.position is None
    assert p.cash == 10_000.0
    assert b.pending() is None  # cleared even though it was a HOLD


def test_only_one_pending_order():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    o1 = Order(symbol="BTC/USDT", action=Action.BUY, quantity=1.0,
               stop_loss=95.0, created_ts_ms=0)
    o2 = Order(symbol="BTC/USDT", action=Action.SELL, quantity=1.0,
               stop_loss=105.0, created_ts_ms=1)
    b.queue(o1)
    b.queue(o2)  # replaces o1
    assert b.pending() is o2


def test_fill_with_no_pending_is_noop():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.0, close=100.5)
    b.fill_pending(next_bar)  # must not raise
    assert p.position is None


def test_stop_loss_hit_closes_intra_bar_long():
    """Bar's low <= stop → close at the stop price (no further slippage applied)."""
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=95.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    # Bar dips to 94 → stop hit at 95
    bar = _bar(1, open_=98.0, high=99.0, low=94.0, close=96.0)
    b.check_stops(bar)
    assert p.position is None
    assert p.closed_trades[0].exit_price == 95.0


def test_stop_loss_hit_closes_intra_bar_short():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.SELL, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=105.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    bar = _bar(1, open_=102.0, high=106.0, low=101.0, close=104.0)
    b.check_stops(bar)
    assert p.position is None
    assert p.closed_trades[0].exit_price == 105.0


def test_stop_check_does_not_close_when_not_hit():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=95.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    bar = _bar(1, open_=98.0, high=99.0, low=96.0, close=97.0)  # never touches 95
    b.check_stops(bar)
    assert p.position is not None
