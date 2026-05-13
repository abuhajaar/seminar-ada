from datetime import datetime, timezone

import pytest

from core.types import Action, AgentReport, Bar, Signal, Trade


def _bar(**overrides):
    base = dict(
        timestamp=datetime(2025, 4, 1, 0, 0, tzinfo=timezone.utc),
        open=100.0, high=101.0, low=99.5, close=100.5,
        volume=1000.0, taker_buy_volume=550.0,
        cvd=120.0, cvd_delta=20.0,
    )
    base.update(overrides)
    return Bar(**base)


def test_bar_is_immutable():
    bar = _bar()
    with pytest.raises(Exception):  # FrozenInstanceError
        bar.close = 200.0  # type: ignore[misc]


def test_bar_round_trip_fields():
    bar = _bar(close=101.25)
    assert bar.close == 101.25
    assert bar.timestamp.tzinfo is timezone.utc


def test_action_enum_values():
    assert Action.BUY.value == "BUY"
    assert Action.SELL.value == "SELL"
    assert Action.HOLD.value == "HOLD"


def test_signal_construct():
    s = Signal(action=Action.BUY, confidence=0.8, reasoning="EMA cross", stop_loss=98.0)
    assert s.action is Action.BUY
    assert s.stop_loss == 98.0


def test_signal_hold_has_no_stop():
    s = Signal(action=Action.HOLD, confidence=0.0, reasoning="no setup", stop_loss=None)
    assert s.stop_loss is None


def test_agent_report_construct():
    r = AgentReport(action=Action.SELL, confidence=0.7, rationale="bearish")
    assert r.action is Action.SELL


def test_trade_pnl_property():
    t = Trade(
        entry_ts=datetime(2025, 4, 1, tzinfo=timezone.utc),
        exit_ts=datetime(2025, 4, 1, 1, tzinfo=timezone.utc),
        entry_price=100.0, exit_price=110.0, qty=2.0,
        side=Action.BUY, fees=0.5,
    )
    # gross = (110 - 100) * 2 = 20; net = 20 - 0.5 = 19.5
    assert t.pnl == pytest.approx(19.5)
