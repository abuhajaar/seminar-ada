"""Tests for `core/run_state.py` — shared engine↔UI state container."""

from __future__ import annotations

from collections import deque

from core.run_state import RunState

# Every field name that must be exposed on RunState and surfaced in snapshot().
# Locked here so downstream UI tests can rely on the contract.
EXPECTED_KEYS = {
    "symbol",
    "timeframe",
    "total_bars",
    "current_bar",
    "bar_ts",
    "bar_close",
    "trad_equity",
    "llm_equity",
    "trad_curve",
    "llm_curve",
    "trad_trades",
    "llm_trades",
    "trad_win_pct",
    "llm_win_pct",
    "trad_mdd",
    "llm_mdd",
    "last_trad_signal",
    "last_trad_rationale",
    "llm_reasoning",
    "cache_hits",
    "cache_misses",
    "spend_usd",
    "budget_usd",
}


def test_run_state_construction_defaults() -> None:
    state = RunState(symbol="BTCUSDT", timeframe="1h", total_bars=500)

    assert state.symbol == "BTCUSDT"
    assert state.timeframe == "1h"
    assert state.total_bars == 500
    assert state.current_bar == 0
    assert state.bar_ts is None
    assert state.bar_close == 0.0
    assert state.trad_equity == 0.0
    assert state.llm_equity == 0.0
    assert state.trad_curve == []
    assert state.llm_curve == []
    assert state.trad_trades == 0
    assert state.llm_trades == 0
    assert state.trad_win_pct == 0.0
    assert state.llm_win_pct == 0.0
    assert state.trad_mdd == 0.0
    assert state.llm_mdd == 0.0
    assert state.last_trad_signal == "HOLD"
    assert state.last_trad_rationale == ""
    assert isinstance(state.llm_reasoning, deque)
    assert state.llm_reasoning.maxlen == 10
    assert len(state.llm_reasoning) == 0
    assert state.cache_hits == 0
    assert state.cache_misses == 0
    assert state.spend_usd == 0.0
    assert state.budget_usd == 0.0


def test_run_state_independent_default_collections() -> None:
    """Default mutable fields must not be shared between instances."""
    a = RunState(symbol="BTCUSDT", timeframe="1h", total_bars=10)
    b = RunState(symbol="ETHUSDT", timeframe="4h", total_bars=20)

    a.trad_curve.append(1.0)
    a.llm_curve.append(2.0)
    a.llm_reasoning.append("hello")

    assert b.trad_curve == []
    assert b.llm_curve == []
    assert len(b.llm_reasoning) == 0


def test_llm_reasoning_bounded_to_ten() -> None:
    state = RunState(symbol="BTCUSDT", timeframe="1h", total_bars=10)
    for i in range(15):
        state.llm_reasoning.append(f"r{i}")

    assert len(state.llm_reasoning) == 10
    # Oldest entries dropped; the last 10 (r5..r14) remain.
    assert list(state.llm_reasoning) == [f"r{i}" for i in range(5, 15)]


def test_snapshot_contains_all_expected_keys() -> None:
    state = RunState(symbol="BTCUSDT", timeframe="1h", total_bars=10)
    snap = state.snapshot()

    assert isinstance(snap, dict)
    assert set(snap.keys()) == EXPECTED_KEYS


def test_snapshot_copies_mutable_collections() -> None:
    """`snapshot()` must return shallow copies of lists/deque so the UI sees
    a consistent frame even if the engine mutates the originals mid-render.
    """
    state = RunState(symbol="BTCUSDT", timeframe="1h", total_bars=10)
    state.trad_curve.append(100.0)
    state.llm_curve.append(101.0)
    state.llm_reasoning.append("first")

    snap = state.snapshot()

    # Snapshot reflects current values.
    assert snap["trad_curve"] == [100.0]
    assert snap["llm_curve"] == [101.0]
    assert snap["llm_reasoning"] == ["first"]

    # Snapshot collections are plain lists (not the live deque / same list ref).
    assert isinstance(snap["trad_curve"], list)
    assert isinstance(snap["llm_curve"], list)
    assert isinstance(snap["llm_reasoning"], list)
    assert snap["trad_curve"] is not state.trad_curve
    assert snap["llm_curve"] is not state.llm_curve

    # Mutating live state after snapshot must not affect the snapshot.
    state.trad_curve.append(200.0)
    state.llm_curve.append(202.0)
    state.llm_reasoning.append("second")

    assert snap["trad_curve"] == [100.0]
    assert snap["llm_curve"] == [101.0]
    assert snap["llm_reasoning"] == ["first"]


def test_snapshot_passes_through_scalars() -> None:
    state = RunState(symbol="BTCUSDT", timeframe="1h", total_bars=10)
    state.current_bar = 7
    state.bar_close = 42_000.5
    state.trad_equity = 10_500.0
    state.llm_equity = 9_800.0
    state.trad_trades = 3
    state.llm_trades = 2
    state.trad_win_pct = 66.6
    state.llm_win_pct = 50.0
    state.trad_mdd = -0.042
    state.llm_mdd = -0.075
    state.last_trad_signal = "BUY"
    state.last_trad_rationale = "ST flip + MACD bull"
    state.cache_hits = 9
    state.cache_misses = 1
    state.spend_usd = 0.37
    state.budget_usd = 5.00

    snap = state.snapshot()

    assert snap["symbol"] == "BTCUSDT"
    assert snap["timeframe"] == "1h"
    assert snap["total_bars"] == 10
    assert snap["current_bar"] == 7
    assert snap["bar_close"] == 42_000.5
    assert snap["trad_equity"] == 10_500.0
    assert snap["llm_equity"] == 9_800.0
    assert snap["trad_trades"] == 3
    assert snap["llm_trades"] == 2
    assert snap["trad_win_pct"] == 66.6
    assert snap["llm_win_pct"] == 50.0
    assert snap["trad_mdd"] == -0.042
    assert snap["llm_mdd"] == -0.075
    assert snap["last_trad_signal"] == "BUY"
    assert snap["last_trad_rationale"] == "ST flip + MACD bull"
    assert snap["cache_hits"] == 9
    assert snap["cache_misses"] == 1
    assert snap["spend_usd"] == 0.37
    assert snap["budget_usd"] == 5.00
    assert snap["bar_ts"] is None
