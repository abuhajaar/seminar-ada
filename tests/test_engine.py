"""Async dual-strategy engine parity with engine_sync.run_sync.

Given the same `Strategy` impl in both legs, `engine.run_async` must produce
bit-identical portfolio state and metrics versus `engine_sync.run_sync`.
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from core.engine import run_async
from core.engine_sync import run_sync
from core.run_state import RunState
from core.types import Bar
from strategies.traditional import TraditionalStrategy

# Backtest knobs shared by parity tests.
SYMBOL = "TEST"
INITIAL_BALANCE = 10_000.0
TAKER_FEE_BPS = 4.0
SLIPPAGE_BPS = 2.0
RISK_PCT = 0.02


def _make_bars(n: int = 400, start_price: float = 100.0, seed: int = 42) -> list[Bar]:
    """Deterministic synthetic bars with a sine-wave + drift trend.

    The Traditional strategy has a 60-bar warmup and needs an ADX > 20
    trending regime plus EMA20/EMA50 + MACD + SuperTrend confluence to emit
    non-HOLD signals. These parameters (n=400, amp=10, period=30, drift=0.2)
    were tuned empirically to produce >= 2 closed trades — enough to exercise
    open/close + stop-hit paths in the engine.
    """
    rng = random.Random(seed)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = start_price
    swing_amp = 10.0
    swing_period = 30.0
    drift = 0.2
    for i in range(n):
        swing = swing_amp * math.sin(i / swing_period)
        d = drift * i
        noise = rng.uniform(-0.4, 0.4)
        target = start_price + swing + d + noise
        open_ = price
        close = max(1.0, target)
        high = max(open_, close) + abs(rng.uniform(0.0, 0.5))
        low = min(open_, close) - abs(rng.uniform(0.0, 0.5))
        bars.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=open_, high=high, low=low, close=close,
            volume=1000.0, taker_buy_volume=500.0,
            cvd=0.0, cvd_delta=0.0,
        ))
        price = close
    return bars


async def test_engine_parity_with_engine_sync():
    """Both async-engine legs (with TraditionalStrategy in each) match engine_sync."""
    bars = _make_bars()

    # Reference: sync engine, single leg.
    p_ref, m_ref = await run_sync(
        bars=bars, strategy=TraditionalStrategy(),
        symbol=SYMBOL, initial_balance=INITIAL_BALANCE,
        taker_fee_bps=TAKER_FEE_BPS, slippage_bps=SLIPPAGE_BPS,
        risk_pct=RISK_PCT,
    )

    # Async engine: same strategy in both legs ⇒ both legs must match ref.
    p_trad, p_llm, m_trad, m_llm = await run_async(
        bars=bars,
        trad_strategy=TraditionalStrategy(),
        llm_strategy=TraditionalStrategy(),
        symbol=SYMBOL, initial_balance=INITIAL_BALANCE,
        taker_fee_bps=TAKER_FEE_BPS, slippage_bps=SLIPPAGE_BPS,
        risk_pct=RISK_PCT,
    )

    last_close = bars[-1].close
    ref_equity = p_ref.equity(last_close)

    # Sanity: the test must actually exercise the trading path.
    assert len(p_ref.closed_trades) >= 1, (
        "synthetic bars produced no trades — increase n or volatility"
    )

    # Final equity parity.
    assert p_trad.equity(last_close) == pytest.approx(ref_equity, abs=1e-8)
    assert p_llm.equity(last_close) == pytest.approx(ref_equity, abs=1e-8)

    # Trade count parity.
    assert len(p_trad.closed_trades) == len(p_ref.closed_trades)
    assert len(p_llm.closed_trades) == len(p_ref.closed_trades)

    # Per-trade pnl parity to 1e-8.
    for t_async, t_ref in zip(p_trad.closed_trades, p_ref.closed_trades, strict=True):
        assert t_async.pnl == pytest.approx(t_ref.pnl, abs=1e-8)
    for t_async, t_ref in zip(p_llm.closed_trades, p_ref.closed_trades, strict=True):
        assert t_async.pnl == pytest.approx(t_ref.pnl, abs=1e-8)

    # Metrics parity (per-key float tolerance).
    assert set(m_trad.keys()) == set(m_ref.keys())
    for k in m_ref:
        v_ref = m_ref[k]
        v_trad = m_trad[k]
        v_llm = m_llm[k]
        if isinstance(v_ref, float):
            assert v_trad == pytest.approx(v_ref, abs=1e-8, nan_ok=True)
            assert v_llm == pytest.approx(v_ref, abs=1e-8, nan_ok=True)
        else:
            assert v_trad == v_ref
            assert v_llm == v_ref


async def test_engine_updates_run_state():
    """Engine writes per-bar snapshots into RunState when supplied."""
    bars = _make_bars(400, seed=42)
    run_state = RunState(symbol="TEST", timeframe="1h", total_bars=400)

    portfolio_trad, portfolio_llm, _m_trad, _m_llm = await run_async(
        bars=bars,
        trad_strategy=TraditionalStrategy(),
        llm_strategy=TraditionalStrategy(),
        symbol=SYMBOL, initial_balance=INITIAL_BALANCE,
        taker_fee_bps=TAKER_FEE_BPS, slippage_bps=SLIPPAGE_BPS,
        risk_pct=RISK_PCT,
        run_state=run_state,
    )

    last_bar = bars[-1]
    assert run_state.current_bar == 400
    assert len(run_state.trad_curve) == 400
    assert len(run_state.llm_curve) == 400
    assert run_state.bar_ts == last_bar.timestamp
    assert run_state.bar_close == last_bar.close
    assert run_state.trad_equity == pytest.approx(
        portfolio_trad.equity(last_bar.close), abs=1e-8
    )
    assert run_state.llm_equity == pytest.approx(
        portfolio_llm.equity(last_bar.close), abs=1e-8
    )
    assert run_state.trad_trades == len(portfolio_trad.closed_trades)
    assert run_state.llm_trades == len(portfolio_llm.closed_trades)
    assert run_state.trad_trades >= 1
    assert run_state.llm_trades >= 1
    assert run_state.last_trad_signal in {"BUY", "SELL", "HOLD"}
    assert isinstance(run_state.last_trad_rationale, str)
    assert len(run_state.last_trad_rationale) > 0
    assert 0.0 <= run_state.trad_win_pct <= 100.0
    assert 0.0 <= run_state.llm_win_pct <= 100.0
    assert run_state.trad_mdd <= 0.0
    assert run_state.llm_mdd <= 0.0


async def test_engine_run_state_is_optional():
    """Omitting run_state keeps the 4-tuple return and parity behavior."""
    bars = _make_bars(400, seed=42)
    result = await run_async(
        bars=bars,
        trad_strategy=TraditionalStrategy(),
        llm_strategy=TraditionalStrategy(),
        symbol=SYMBOL, initial_balance=INITIAL_BALANCE,
        taker_fee_bps=TAKER_FEE_BPS, slippage_bps=SLIPPAGE_BPS,
        risk_pct=RISK_PCT,
    )
    assert len(result) == 4


async def test_engine_curve_caps_at_500():
    """Equity curves in RunState are capped at 500 most-recent points."""
    bars = _make_bars(600, seed=42)
    run_state = RunState(symbol="TEST", timeframe="1h", total_bars=600)
    await run_async(
        bars=bars,
        trad_strategy=TraditionalStrategy(),
        llm_strategy=TraditionalStrategy(),
        symbol=SYMBOL, initial_balance=INITIAL_BALANCE,
        taker_fee_bps=TAKER_FEE_BPS, slippage_bps=SLIPPAGE_BPS,
        risk_pct=RISK_PCT,
        run_state=run_state,
    )
    assert len(run_state.trad_curve) == 500
    assert len(run_state.llm_curve) == 500
    assert run_state.current_bar == 600


def test_engine_requires_two_bars():
    """Feeding a single bar must raise ValueError (matches engine_sync behavior)."""
    bars = _make_bars(n=1)
    with pytest.raises(ValueError, match="at least 2 bars"):
        asyncio.run(run_async(
            bars=bars,
            trad_strategy=TraditionalStrategy(),
            llm_strategy=TraditionalStrategy(),
            symbol=SYMBOL, initial_balance=INITIAL_BALANCE,
            taker_fee_bps=TAKER_FEE_BPS, slippage_bps=SLIPPAGE_BPS,
            risk_pct=RISK_PCT,
        ))
