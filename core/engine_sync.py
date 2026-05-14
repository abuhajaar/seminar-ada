"""Synchronous bar-by-bar engine for a single strategy.

Wired in this order each bar:
    1. broker.check_stops(bar)            - close on intra-bar stop hit
    2. broker.fill_pending(bar)           - fill the previous bar's queued order
    3. signal = await strategy.on_bar(bar, ctx)
    4. if signal triggers entry/exit, size it and queue an Order
    5. portfolio.mark(bar.timestamp, bar.close)

Order matters: stops first (so a strategy emitting a new signal on a stop-hit
bar starts fresh), then queued fills, then this bar's signal queues for next.

Async signature: `on_bar` is async (per the Strategy protocol) so this engine
is also async; callers wrap with `asyncio.run`. The full async + concurrent
dual-strategy engine is sub-plan D; this is the validation harness.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.broker import Broker
from core.metrics import MetricsDict, compute_metrics
from core.portfolio import Portfolio
from core.types import Action, Bar, Order
from strategies.base import Context, Strategy


def size_position(equity: float, risk_pct: float, entry: float, stop: float) -> float:
    """Fixed-fractional position size: risk_dollars / per-unit risk.

    Shared by both `engine_sync.run_sync` and `engine.run_async` so the two
    engines compute identical quantities for identical inputs.
    """
    risk_dollars = equity * risk_pct
    risk_per_unit = abs(entry - stop)
    if risk_per_unit == 0.0:
        return 0.0
    return risk_dollars / risk_per_unit


async def run_sync(
    *,
    bars: Iterable[Bar],
    strategy: Strategy,
    symbol: str,
    initial_balance: float,
    taker_fee_bps: float,
    slippage_bps: float,
    risk_pct: float,
) -> tuple[Portfolio, MetricsDict]:
    portfolio = Portfolio(initial_balance=initial_balance)
    broker = Broker(
        portfolio=portfolio,
        taker_fee_bps=taker_fee_bps,
        slippage_bps=slippage_bps,
    )
    bar_count = 0

    for bar in bars:
        bar_count += 1
        # 1. Check stops on the freshly-opened bar (uses high/low).
        broker.check_stops(bar)
        # 2. Fill any pending order at this bar's open.
        broker.fill_pending(bar)

        # 3. Strategy sees the bar and emits a Signal.
        ctx = Context(
            symbol=symbol,
            equity=portfolio.equity(mark_price=bar.close),
            risk_pct=risk_pct,
            in_position=portfolio.position is not None,
        )
        signal = await strategy.on_bar(bar, ctx)

        # 4. Queue an Order for next-bar fill.
        if signal.action is not Action.HOLD:
            in_pos = portfolio.position is not None
            if in_pos:
                # Closing trade: quantity must match existing position.
                assert portfolio.position is not None  # for type checker
                qty = portfolio.position.quantity
                broker.queue(Order(
                    symbol=symbol, action=signal.action, quantity=qty,
                    stop_loss=None,
                    created_ts_ms=int(bar.timestamp.timestamp() * 1000),
                ))
            else:
                # Opening trade: size from risk + stop.
                if signal.stop_loss is not None:
                    qty = size_position(
                        equity=ctx.equity, risk_pct=risk_pct,
                        entry=bar.close, stop=signal.stop_loss,
                    )
                    if qty > 0.0:
                        broker.queue(Order(
                            symbol=symbol, action=signal.action, quantity=qty,
                            stop_loss=signal.stop_loss,
                            created_ts_ms=int(bar.timestamp.timestamp() * 1000),
                        ))

        # 5. Record equity sample at bar close.
        portfolio.mark(bar.timestamp, bar.close)

    if bar_count < 2:
        raise ValueError("need at least 2 bars to compute metrics")

    metrics = compute_metrics(
        equity_curve=portfolio.equity_curve(),
        trades=portfolio.closed_trades,
    )
    return portfolio, metrics
