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
from pathlib import Path

from core.broker import Broker, _fee
from core.metrics import MetricsDict, compute_metrics
from core.portfolio import Portfolio
from core.types import Action, Bar, Order
from strategies.base import Context, Strategy


def size_position(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    *,
    action: Action = Action.BUY,
    taker_fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> float:
    """Fixed-fractional position size, accounting for fees + slippage drag.

    Returns the largest ``qty`` such that a stop-out loses no more than
    ``equity * risk_pct``. For a long entry the realized stop-out loss per
    unit is::

        (entry_eff - stop) + entry_eff * f + stop * f      [BUY]

    where ``entry_eff = entry * (1 + slippage_bps/1e4)`` and ``f =
    taker_fee_bps/1e4``. The symmetric short formula uses ``entry_eff =
    entry * (1 - slippage_bps/1e4)`` and the stop sits *above* entry.

    Pre-fix this function ignored both fees and slippage (audit H5), so the
    realized loss on a stop-out routinely exceeded ``risk_pct`` (~2% drag
    for the seminar's 4 bps + 2 bps configuration).

    Args:
        equity: Current portfolio equity used as the risk base.
        risk_pct: Fraction of equity at risk on a stop-out (e.g. ``0.02``).
        entry: Quoted entry price (bar close on signal bar; fill happens at
            the next bar's open at this same level for sizing purposes).
        stop: Stop-loss price.
        action: ``Action.BUY`` (long) or ``Action.SELL`` (short). Defaults
            to BUY for backwards compat with old call sites; tests in
            ``tests/test_engine_sync.py`` cover both directions.
        taker_fee_bps: Taker fee in basis points (4 bps = 0.04%).
        slippage_bps: Symmetric slippage in basis points.

    Returns:
        ``qty`` (>= 0) such that worst-case stop-out loss <= ``equity *
        risk_pct``. Returns ``0.0`` if the stop is on the wrong side of
        entry or if per-unit risk is non-positive (defense in depth — the
        engine already rejects wrong-sided stops; see H4).
    """
    risk_dollars = equity * risk_pct
    f = taker_fee_bps / 10_000.0
    s = slippage_bps / 10_000.0
    if action is Action.BUY:
        entry_eff = entry * (1.0 + s)
        # Stop must sit below entry_eff; otherwise per-unit loss is non-positive.
        per_unit_loss = (entry_eff - stop) + entry_eff * f + stop * f
    elif action is Action.SELL:
        entry_eff = entry * (1.0 - s)
        # Short: stop sits above entry_eff.
        per_unit_loss = (stop - entry_eff) + entry_eff * f + stop * f
    else:
        return 0.0
    if per_unit_loss <= 0.0:
        return 0.0
    return risk_dollars / per_unit_loss


async def run_sync(
    *,
    bars: Iterable[Bar],
    strategy: Strategy,
    symbol: str,
    initial_balance: float,
    taker_fee_bps: float,
    slippage_bps: float,
    risk_pct: float,
    artifact_root: Path | None = None,
    total_bars: int | None = None,
) -> tuple[Portfolio, MetricsDict]:
    portfolio = Portfolio(initial_balance=initial_balance)
    broker = Broker(
        portfolio=portfolio,
        taker_fee_bps=taker_fee_bps,
        slippage_bps=slippage_bps,
    )
    bar_count = 0
    last_bar: Bar | None = None

    for bar_idx, bar in enumerate(bars, start=1):
        bar_count += 1
        last_bar = bar
        # 1. Check stops on the freshly-opened bar (uses high/low).
        broker.check_stops(bar)
        # 2. Fill any pending order at this bar's open.
        broker.fill_pending(bar)

        sink = None
        if artifact_root is not None and total_bars is not None:
            from core.bar_artifacts import BarArtifactSink, bar_folder_name

            sink = BarArtifactSink(
                artifact_root / bar_folder_name(bar_idx, total=total_bars)
            )

        # 3. Strategy sees the bar and emits a Signal.
        ctx = Context(
            symbol=symbol,
            equity=portfolio.equity(mark_price=bar.close),
            risk_pct=risk_pct,
            in_position=portfolio.position is not None,
            bar_index=bar_idx,
            artifact_sink=sink,
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
                    # Reject wrong-sided stops (audit H4): a long needs stop
                    # below entry; a short needs stop above. Otherwise
                    # `size_position` uses abs() and produces a position
                    # that gets stopped out on the next bar at a guaranteed
                    # loss far exceeding `risk_pct`.
                    wrong_side = (
                        (signal.action is Action.BUY and signal.stop_loss >= bar.close)
                        or (signal.action is Action.SELL and signal.stop_loss <= bar.close)
                    )
                    if wrong_side:
                        pass  # refuse; no order queued
                    else:
                        qty = size_position(
                            equity=ctx.equity, risk_pct=risk_pct,
                            entry=bar.close, stop=signal.stop_loss,
                            action=signal.action,
                            taker_fee_bps=taker_fee_bps,
                            slippage_bps=slippage_bps,
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

    # End-of-run flatten: any dangling position is synth-closed at the last
    # bar's close so `closed_trades` accounts for every position taken. Without
    # this, `compute_metrics` sees Σ trade.pnl ≠ equity[-1] - equity[0] and
    # silently drops the open final leg from win/loss/profit-factor counts.
    # Uses the taker fee path; no slippage (mirrors stop-fill semantics).
    if portfolio.position is not None:
        assert last_bar is not None  # bar_count >= 2 guarantees this
        exit_price = last_bar.close
        exit_fee = _fee(exit_price * portfolio.position.quantity, taker_fee_bps)
        portfolio.close_position(
            price=exit_price, fee=exit_fee, timestamp=last_bar.timestamp,
        )

    metrics = compute_metrics(
        equity_curve=portfolio.equity_curve(),
        trades=portfolio.closed_trades,
    )
    return portfolio, metrics
