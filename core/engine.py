"""Async dual-strategy bar-by-bar engine (Traditional + LLM).

This engine runs two independent `Strategy` legs in lock-step over the same
bar stream, awaiting both `on_bar` coroutines concurrently via
`asyncio.gather`. Each leg owns its own `Portfolio` + `Broker`; sizing and
order-queueing logic is identical to `engine_sync.run_sync` so that, given
the same strategy in both legs, results are bit-identical to the sync
reference engine (see `tests/test_engine.py::test_engine_parity_with_engine_sync`).

Per-bar order (mirrors `engine_sync.run_sync` exactly, per leg):
    1. broker.check_stops(bar)
    2. broker.fill_pending(bar)
    3. await strategy.on_bar(bar, ctx)   # both legs in parallel
    4. size + queue Order (if non-HOLD)
    5. portfolio.mark(bar.timestamp, bar.close)
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from core.broker import Broker
from core.engine_sync import size_position
from core.metrics import MetricsDict, compute_metrics
from core.portfolio import Portfolio
from core.types import Action, Bar, Order, Signal
from strategies.base import Context, Strategy


def _queue_from_signal(
    *,
    broker: Broker,
    portfolio: Portfolio,
    signal: Signal,
    bar: Bar,
    symbol: str,
    risk_pct: float,
    ctx_equity: float,
) -> None:
    """Apply the same close-vs-open + sizing logic as engine_sync.run_sync."""
    if signal.action is Action.HOLD:
        return
    in_pos = portfolio.position is not None
    if in_pos:
        assert portfolio.position is not None  # for type checker
        qty = portfolio.position.quantity
        broker.queue(Order(
            symbol=symbol, action=signal.action, quantity=qty,
            stop_loss=None,
            created_ts_ms=int(bar.timestamp.timestamp() * 1000),
        ))
        return
    # Opening trade.
    if signal.stop_loss is None:
        return
    qty = size_position(
        equity=ctx_equity, risk_pct=risk_pct,
        entry=bar.close, stop=signal.stop_loss,
    )
    if qty > 0.0:
        broker.queue(Order(
            symbol=symbol, action=signal.action, quantity=qty,
            stop_loss=signal.stop_loss,
            created_ts_ms=int(bar.timestamp.timestamp() * 1000),
        ))


async def run_async(
    *,
    bars: Iterable[Bar],
    trad_strategy: Strategy,
    llm_strategy: Strategy,
    symbol: str,
    initial_balance: float,
    taker_fee_bps: float,
    slippage_bps: float,
    risk_pct: float,
) -> tuple[Portfolio, Portfolio, MetricsDict, MetricsDict]:
    portfolio_trad = Portfolio(initial_balance=initial_balance)
    portfolio_llm = Portfolio(initial_balance=initial_balance)
    broker_trad = Broker(
        portfolio=portfolio_trad,
        taker_fee_bps=taker_fee_bps,
        slippage_bps=slippage_bps,
    )
    broker_llm = Broker(
        portfolio=portfolio_llm,
        taker_fee_bps=taker_fee_bps,
        slippage_bps=slippage_bps,
    )
    bar_count = 0

    for bar in bars:
        bar_count += 1
        # 1. Stops first, per leg.
        broker_trad.check_stops(bar)
        broker_llm.check_stops(bar)
        # 2. Fill pending, per leg.
        broker_trad.fill_pending(bar)
        broker_llm.fill_pending(bar)

        # 3. Build per-leg Context (equity differs).
        ctx_trad = Context(
            symbol=symbol,
            equity=portfolio_trad.equity(mark_price=bar.close),
            risk_pct=risk_pct,
            in_position=portfolio_trad.position is not None,
        )
        ctx_llm = Context(
            symbol=symbol,
            equity=portfolio_llm.equity(mark_price=bar.close),
            risk_pct=risk_pct,
            in_position=portfolio_llm.position is not None,
        )

        # 4. Await both signals concurrently.
        sig_trad, sig_llm = await asyncio.gather(
            trad_strategy.on_bar(bar, ctx_trad),
            llm_strategy.on_bar(bar, ctx_llm),
        )

        # 5. Queue orders per leg.
        _queue_from_signal(
            broker=broker_trad, portfolio=portfolio_trad, signal=sig_trad,
            bar=bar, symbol=symbol, risk_pct=risk_pct,
            ctx_equity=ctx_trad.equity,
        )
        _queue_from_signal(
            broker=broker_llm, portfolio=portfolio_llm, signal=sig_llm,
            bar=bar, symbol=symbol, risk_pct=risk_pct,
            ctx_equity=ctx_llm.equity,
        )

        # 6. Mark equity per leg.
        portfolio_trad.mark(bar.timestamp, bar.close)
        portfolio_llm.mark(bar.timestamp, bar.close)

    if bar_count < 2:
        raise ValueError("need at least 2 bars to compute metrics")

    metrics_trad = compute_metrics(
        equity_curve=portfolio_trad.equity_curve(),
        trades=portfolio_trad.closed_trades,
    )
    metrics_llm = compute_metrics(
        equity_curve=portfolio_llm.equity_curve(),
        trades=portfolio_llm.closed_trades,
    )
    return portfolio_trad, portfolio_llm, metrics_trad, metrics_llm
