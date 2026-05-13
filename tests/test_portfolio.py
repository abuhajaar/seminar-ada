"""Portfolio: tracks cash, single-symbol position, equity curve, closed trades."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.portfolio import Portfolio, Position
from core.types import Action


def _ts(hour: int) -> datetime:
    return datetime(2025, 4, 1, hour, 0, tzinfo=timezone.utc)


def test_portfolio_starts_flat():
    p = Portfolio(initial_balance=10_000.0)
    assert p.cash == 10_000.0
    assert p.position is None
    assert p.equity(mark_price=100.0) == 10_000.0
    assert p.closed_trades == []


def test_open_long_decreases_cash_and_records_position():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.BUY,
        price=100.0,
        quantity=10.0,
        fee=0.40,
        stop_loss=90.0,
        timestamp=_ts(0),
    )
    assert p.cash == pytest.approx(10_000.0 - 1000.0 - 0.40)
    assert p.position is not None
    assert p.position.action is Action.BUY
    assert p.position.quantity == 10.0
    assert p.position.entry_price == 100.0
    assert p.position.stop_loss == 90.0
    assert p.equity(mark_price=100.0) == pytest.approx(10_000.0 - 0.40)


def test_open_short_increases_cash_and_records_position():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.SELL,
        price=100.0,
        quantity=10.0,
        fee=0.40,
        stop_loss=110.0,
        timestamp=_ts(0),
    )
    assert p.cash == pytest.approx(10_000.0 + 1000.0 - 0.40)
    assert p.position is not None
    assert p.position.action is Action.SELL
    assert p.equity(mark_price=100.0) == pytest.approx(10_000.0 - 0.40)


def test_close_long_realizes_pnl_and_logs_trade():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=90.0, timestamp=_ts(0),
    )
    p.close_position(price=110.0, fee=0.44, timestamp=_ts(1))
    assert p.position is None
    assert p.cash == pytest.approx(10_000.0 + 100.0 - 0.84)
    assert len(p.closed_trades) == 1
    t = p.closed_trades[0]
    assert t.symbol == "PORTFOLIO"
    assert t.entry_price == 100.0
    assert t.exit_price == 110.0
    assert t.qty == 10.0
    assert t.side is Action.BUY
    assert t.fees == pytest.approx(0.84)
    # Trade.pnl is a property: gross - fees = 100.0 - 0.84 = 99.16
    assert t.pnl == pytest.approx(100.0 - 0.84)


def test_close_short_realizes_pnl():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.SELL, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=110.0, timestamp=_ts(0),
    )
    p.close_position(price=90.0, fee=0.36, timestamp=_ts(1))
    assert p.position is None
    assert p.cash == pytest.approx(10_000.0 + 100.0 - 0.40 - 0.36)
    t = p.closed_trades[0]
    assert t.fees == pytest.approx(0.76)
    assert t.pnl == pytest.approx(100.0 - 0.76)


def test_open_when_already_in_position_raises():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=1.0,
        fee=0.0, stop_loss=90.0, timestamp=_ts(0),
    )
    with pytest.raises(ValueError, match="already in position"):
        p.open_position(
            action=Action.BUY, price=101.0, quantity=1.0,
            fee=0.0, stop_loss=91.0, timestamp=_ts(1),
        )


def test_close_when_flat_raises():
    p = Portfolio(initial_balance=10_000.0)
    with pytest.raises(ValueError, match="no open position"):
        p.close_position(price=100.0, fee=0.0, timestamp=_ts(0))


def test_equity_curve_records_each_mark():
    p = Portfolio(initial_balance=10_000.0)
    p.mark(timestamp=_ts(0), mark_price=100.0)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.0, stop_loss=90.0, timestamp=_ts(1),
    )
    p.mark(timestamp=_ts(2), mark_price=105.0)
    p.mark(timestamp=_ts(3), mark_price=110.0)
    curve = p.equity_curve()
    assert len(curve) == 3
    assert curve[0] == (_ts(0), 10_000.0)
    assert curve[1] == (_ts(2), pytest.approx(10_050.0))
    assert curve[2] == (_ts(3), pytest.approx(10_100.0))


def test_position_dataclass_is_frozen():
    from dataclasses import FrozenInstanceError
    pos = Position(action=Action.BUY, quantity=1.0, entry_price=100.0,
                   stop_loss=90.0, entry_ts=_ts(0))
    with pytest.raises(FrozenInstanceError):
        pos.quantity = 2.0  # type: ignore[misc]
