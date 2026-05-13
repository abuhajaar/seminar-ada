"""Shared dataclasses used across engine, strategies, broker, and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar with attached cumulative-volume-delta fields.

    `cvd` is cumulative across the entire backtest window; `cvd_delta` is
    this bar's contribution. Both are computed up-front by `data/cvd.py`
    so the engine can read them in O(1) per bar.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    taker_buy_volume: float
    cvd: float
    cvd_delta: float


@dataclass
class Signal:
    """A strategy's decision for a given bar.

    `confidence` is informational only — position sizing uses the
    fixed-fractional rule from `config.execution.risk_pct`.
    `stop_loss` is the SuperTrend stop for the traditional bot;
    LLM-bot signals may set it to None, in which case the broker uses
    a default ATR-based stop (see sub-plan B).
    """

    action: Action
    confidence: float
    reasoning: str
    stop_loss: float | None


@dataclass
class AgentReport:
    """Output of one LLM analyst node (Technical, Visual, QABBA)."""

    action: Action
    confidence: float
    rationale: str


@dataclass
class Trade:
    """A completed round-trip trade. Used by metrics + persistence."""

    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    qty: float
    side: Action  # Action.BUY for long, Action.SELL for short
    fees: float
    symbol: str = "PORTFOLIO"

    @property
    def pnl(self) -> float:
        direction = 1.0 if self.side is Action.BUY else -1.0
        gross = (self.exit_price - self.entry_price) * self.qty * direction
        return gross - self.fees


@dataclass(frozen=True)
class Order:
    """A pending order, queued at bar t and filled at bar[t+1].open.

    `quantity` is in base-asset units (e.g. BTC), always positive.
    `action` indicates direction (BUY = open/extend long, SELL = close/flip).
    `stop_loss` is the SuperTrend-derived stop price; sizing was computed against it.
    """
    symbol: str
    action: Action
    quantity: float
    stop_loss: float | None
    created_ts_ms: int
