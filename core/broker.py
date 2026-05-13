"""Order queue + execution simulator.

Conventions:
- An order queued during processing of bar t is filled at bar[t+1].open.
- Slippage is applied symmetrically: BUY fills above open, SELL fills below.
- Fees are taker-side (Binance default 4 bps).
- A SELL while flat opens a short; a SELL while long closes the long.
  Symmetrically for BUY. No flips in a single fill — close + reopen is
  the strategy's job (queue two orders on consecutive bars).
- Stops are checked intra-bar: if low <= stop (long) or high >= stop (short),
  the position closes at the stop price (no extra slippage applied to stops —
  this models a stop-market fill at the exchange-quoted level).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.portfolio import Portfolio
from core.types import Action, Bar, Order


def _apply_slippage(price: float, action: Action, slippage_bps: float) -> float:
    """BUY fills slip up, SELL fills slip down."""
    factor = slippage_bps / 10_000.0
    if action is Action.BUY:
        return price * (1.0 + factor)
    if action is Action.SELL:
        return price * (1.0 - factor)
    return price


def _fee(notional: float, fee_bps: float) -> float:
    return notional * (fee_bps / 10_000.0)


@dataclass
class Broker:
    portfolio: Portfolio
    taker_fee_bps: float
    slippage_bps: float
    _pending: Order | None = field(init=False, default=None)

    def queue(self, order: Order) -> None:
        """Queue (or replace) the next-bar order. HOLD is allowed and clears on fill."""
        self._pending = order

    def pending(self) -> Order | None:
        return self._pending

    def fill_pending(self, next_bar: Bar) -> None:
        order = self._pending
        self._pending = None
        if order is None or order.action is Action.HOLD or order.quantity == 0.0:
            return

        fill_price = _apply_slippage(next_bar.open, order.action, self.slippage_bps)
        fee = _fee(fill_price * order.quantity, self.taker_fee_bps)

        pos = self.portfolio.position
        if pos is not None and pos.action is not order.action:
            # Opposing direction → close existing position; do not open new one.
            self.portfolio.close_position(
                price=fill_price, fee=fee, timestamp=next_bar.timestamp,
            )
            return

        if pos is not None and pos.action is order.action:
            # Same direction → ignore (no pyramiding in sub-plan B).
            return

        self.portfolio.open_position(
            action=order.action, price=fill_price, quantity=order.quantity,
            fee=fee, stop_loss=order.stop_loss, timestamp=next_bar.timestamp,
        )

    def check_stops(self, bar: Bar) -> None:
        """Close position at stop if intra-bar high/low breaches it."""
        pos = self.portfolio.position
        if pos is None or pos.stop_loss is None:
            return
        stop = pos.stop_loss
        hit = (
            (pos.action is Action.BUY and bar.low <= stop)
            or (pos.action is Action.SELL and bar.high >= stop)
        )
        if not hit:
            return
        fee = _fee(stop * pos.quantity, self.taker_fee_bps)
        self.portfolio.close_position(price=stop, fee=fee, timestamp=bar.timestamp)
