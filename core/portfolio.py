"""Single-symbol portfolio: cash, position, equity curve, trade log.

This is intentionally minimal:
- One open position at a time (long OR short).
- No partial fills; one close = full close.
- Per-symbol multi-asset portfolios are out of scope for sub-plan B
  (the engine instantiates one Portfolio per symbol-strategy pair).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.types import Action, Trade


@dataclass(frozen=True)
class Position:
    action: Action               # BUY = long, SELL = short
    quantity: float              # base-asset units, always positive
    entry_price: float
    stop_loss: float | None
    entry_ts: datetime
    entry_fee: float = 0.0


@dataclass
class Portfolio:
    """Tracks cash, optional position, equity history, and closed trades."""

    initial_balance: float
    cash: float = field(init=False)
    position: Position | None = field(init=False, default=None)
    _curve: list[tuple[datetime, float]] = field(init=False, default_factory=list)
    closed_trades: list[Trade] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_balance)

    # ── equity ────────────────────────────────────────────────────────────
    def equity(self, mark_price: float) -> float:
        if self.position is None:
            return self.cash
        if self.position.action is Action.BUY:
            return self.cash + self.position.quantity * mark_price
        # short: we owe `quantity` of base at mark
        return self.cash - self.position.quantity * mark_price

    def mark(self, timestamp: datetime, mark_price: float) -> None:
        """Record an equity sample at this timestamp."""
        self._curve.append((timestamp, self.equity(mark_price)))

    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._curve)

    # ── trading ───────────────────────────────────────────────────────────
    def open_position(
        self,
        *,
        action: Action,
        price: float,
        quantity: float,
        fee: float,
        stop_loss: float | None,
        timestamp: datetime,
    ) -> None:
        if self.position is not None:
            raise ValueError("already in position; close before opening a new one")
        if action is Action.HOLD:
            raise ValueError("cannot open a HOLD position")
        notional = price * quantity
        if action is Action.BUY:
            self.cash -= notional
        else:  # SELL → short, receive proceeds
            self.cash += notional
        self.cash -= fee
        self.position = Position(
            action=action, quantity=quantity, entry_price=price,
            stop_loss=stop_loss, entry_ts=timestamp, entry_fee=fee,
        )

    def close_position(
        self,
        *,
        price: float,
        fee: float,
        timestamp: datetime,
    ) -> None:
        if self.position is None:
            raise ValueError("no open position to close")
        pos = self.position
        notional = price * pos.quantity
        if pos.action is Action.BUY:
            self.cash += notional
        else:
            self.cash -= notional
        self.cash -= fee
        # Trade.pnl is a computed property based on side, prices, qty, fees.
        # Total fees on the trade = entry_fee (paid at open) + exit fee (now).
        self.closed_trades.append(
            Trade(
                entry_ts=pos.entry_ts,
                exit_ts=timestamp,
                entry_price=pos.entry_price,
                exit_price=price,
                qty=pos.quantity,
                side=pos.action,
                fees=pos.entry_fee + fee,
                symbol="PORTFOLIO",
            )
        )
        self.position = None
