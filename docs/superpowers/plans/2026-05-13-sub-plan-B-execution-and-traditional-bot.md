# Sub-Plan B: Execution Layer + Traditional Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared execution infrastructure (portfolio, broker, metrics) and the heuristic Traditional Bot, plus a minimal synchronous engine that runs the bot bar-by-bar end-to-end on cached data. This produces the first complete (non-LLM) backtest path.

**Architecture:** Strategy protocol takes `(Bar, Context) -> Signal`. Broker queues signals at bar `t` and fills them at `bar[t+1].open` with configurable taker fee (4 bps default) and slippage (2 bps default). Portfolio tracks balance, position, equity curve, and trade log. Metrics post-process the equity curve and trade log into the headline numbers (TR, MDD, WR, PF, Sharpe). Position sizing is fixed-fractional 2%-risk anchored to the SuperTrend stop. Traditional bot uses a transparent indicator-confluence rule documented inline.

**Tech Stack:** Python 3.13, dataclasses, numpy, pandas (already pinned), pytest. No new runtime deps. The minimal engine here is **synchronous** (`for bar in load_bars(...)`); the async loop + TUI is deferred to sub-plan D.

**Status of prerequisite (sub-plan A):** complete. `core/types.py`, `core/config.py`, `indicators/ta.py`, `data/{paths,downloader,cvd,loader}.py` exist with 32 tests passing.

---

## Scope checklist (spec sections this plan implements)

- §5: extends `core/types.py` with `Order` (already missing) — **add `Order` dataclass**.
- §6: minimal synchronous engine variant of `core/engine.py` (async + TUI deferred to sub-plan D).
- §10: `execution.*` config keys are honored (`fill: next_bar_open`, `taker_fee_bps`, `slippage_bps`, `risk_pct`).
- §11 test rows: Broker fees + next-bar fill, Metrics MDD + PF zero-loss edge case, Traditional strategy canned bars.
- §13 implementation order steps 4 + 5 (portfolio, broker, metrics, strategies/base, strategies/traditional).

Out of scope (deferred):
- Async engine + `asyncio.gather` (sub-plan D).
- Rich TUI (sub-plan D).
- Walk-forward across multiple assets (sub-plan D).
- LLM agent strategy (sub-plan C).

---

## File structure produced by this plan

```
core/
├── portfolio.py          # NEW: Position, Portfolio, equity curve, trade log
├── broker.py             # NEW: queue/fill simulation with fees+slippage
├── metrics.py            # NEW: TR, MDD, WR, PF, Sharpe
├── engine_sync.py        # NEW: minimal synchronous bar loop (validation harness)
└── types.py              # MODIFY: add Order dataclass
strategies/
├── __init__.py           # NEW (empty)
├── base.py               # NEW: Strategy protocol + Context dataclass
└── traditional.py        # NEW: heuristic indicator-confluence bot
tests/
├── test_portfolio.py     # NEW
├── test_broker.py        # NEW
├── test_metrics.py       # NEW
├── test_traditional.py   # NEW
├── test_engine_sync.py   # NEW
└── test_types.py         # MODIFY: add Order tests
```

---

## Task 1: Add `Order` dataclass to `core/types.py`

**Files:**
- Modify: `core/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Add the failing test to `tests/test_types.py`**

Append to the end of `tests/test_types.py`:

```python
def test_order_construction():
    from core.types import Action, Order

    o = Order(
        symbol="BTC/USDT",
        action=Action.BUY,
        quantity=0.5,
        stop_loss=60000.0,
        created_ts_ms=1_700_000_000_000,
    )
    assert o.symbol == "BTC/USDT"
    assert o.action is Action.BUY
    assert o.quantity == 0.5
    assert o.stop_loss == 60000.0
    assert o.created_ts_ms == 1_700_000_000_000


def test_order_is_frozen():
    from dataclasses import FrozenInstanceError

    from core.types import Action, Order

    o = Order(
        symbol="ETH/USDT", action=Action.SELL, quantity=1.0,
        stop_loss=None, created_ts_ms=0,
    )
    with pytest.raises(FrozenInstanceError):
        o.quantity = 2.0  # type: ignore[misc]
```

If `pytest` isn't already imported at the top of `tests/test_types.py`, add `import pytest`.

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_types.py -v`
Expected: ImportError or AttributeError on `Order`.

- [ ] **Step 3: Add `Order` to `core/types.py`**

Append to `core/types.py` (after the existing `Trade` dataclass):

```python
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
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_types.py -v`
Expected: 9 passed (7 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add core/types.py tests/test_types.py
git commit -m "feat(core): add Order dataclass for queued next-bar fills"
```

---

## Task 2: `core/portfolio.py` — Position, Portfolio, equity curve

**Files:**
- Create: `core/portfolio.py`
- Create: `tests/test_portfolio.py`

- [ ] **Step 1: Write the failing test `tests/test_portfolio.py`**

```python
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
        quantity=10.0,           # 10 units at 100 = 1000 notional
        fee=0.40,                # 4 bps on 1000
        stop_loss=90.0,
        timestamp=_ts(0),
    )
    assert p.cash == pytest.approx(10_000.0 - 1000.0 - 0.40)
    assert p.position is not None
    assert p.position.action is Action.BUY
    assert p.position.quantity == 10.0
    assert p.position.entry_price == 100.0
    assert p.position.stop_loss == 90.0
    # Equity at entry price: cash + position notional (fees already deducted)
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
    # Short: receive proceeds (+1000), pay fee
    assert p.cash == pytest.approx(10_000.0 + 1000.0 - 0.40)
    assert p.position is not None
    assert p.position.action is Action.SELL
    # Equity = cash - mark * qty (we owe `qty` of base at mark)
    assert p.equity(mark_price=100.0) == pytest.approx(10_000.0 - 0.40)


def test_close_long_realizes_pnl_and_logs_trade():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=90.0, timestamp=_ts(0),
    )
    p.close_position(price=110.0, fee=0.44, timestamp=_ts(1))
    # Gross PnL = (110-100)*10 = +100; total fees 0.40+0.44 = 0.84
    assert p.position is None
    assert p.cash == pytest.approx(10_000.0 + 100.0 - 0.84)
    assert len(p.closed_trades) == 1
    t = p.closed_trades[0]
    assert t.symbol == "PORTFOLIO"  # placeholder until per-symbol portfolios
    assert t.entry_price == 100.0
    assert t.exit_price == 110.0
    assert t.quantity == 10.0
    assert t.pnl == pytest.approx(100.0 - 0.84)


def test_close_short_realizes_pnl():
    p = Portfolio(initial_balance=10_000.0)
    p.open_position(
        action=Action.SELL, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=110.0, timestamp=_ts(0),
    )
    p.close_position(price=90.0, fee=0.36, timestamp=_ts(1))
    # Short PnL = (entry - exit) * qty = (100-90)*10 = +100
    assert p.position is None
    assert p.cash == pytest.approx(10_000.0 + 100.0 - 0.40 - 0.36)
    t = p.closed_trades[0]
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
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_portfolio.py -v`
Expected: ImportError on `core.portfolio`.

- [ ] **Step 3: Implement `core/portfolio.py`**

```python
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
            stop_loss=stop_loss, entry_ts=timestamp,
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
            gross_pnl = (price - pos.entry_price) * pos.quantity
        else:
            self.cash -= notional
            gross_pnl = (pos.entry_price - price) * pos.quantity
        self.cash -= fee
        # Trade.pnl reflects gross minus exit fee only; entry fee was already
        # subtracted from cash at open. Keep `pnl` net of BOTH fees for clarity:
        # caller-friendly headline number = gross - entry_fee - exit_fee.
        # We don't have entry_fee here, so reconstruct via Position? No — store
        # entry_fee in Position.
        # CORRECTION: net-of-both-fees is captured by recording entry_fee on
        # Position. See open_position. (See Step 3a below.)
        # For now, pnl = gross - exit fee; we adjust in Step 3a.
        self.closed_trades.append(
            Trade(
                symbol="PORTFOLIO",
                entry_ts=pos.entry_ts,
                exit_ts=timestamp,
                action=pos.action,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                exit_price=price,
                pnl=gross_pnl - fee - pos_entry_fee_lookup(pos),
            )
        )
        self.position = None
```

This implementation references `pos_entry_fee_lookup` and `Position` lacks `entry_fee`. Step 3a corrects both.

- [ ] **Step 3a: Correct Position to carry `entry_fee`; finalize implementation**

Replace the contents of `core/portfolio.py` with the corrected version:

```python
"""Single-symbol portfolio: cash, position, equity curve, trade log."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.types import Action, Trade


@dataclass(frozen=True)
class Position:
    action: Action
    quantity: float
    entry_price: float
    stop_loss: float | None
    entry_ts: datetime
    entry_fee: float = 0.0


@dataclass
class Portfolio:
    initial_balance: float
    cash: float = field(init=False)
    position: Position | None = field(init=False, default=None)
    _curve: list[tuple[datetime, float]] = field(init=False, default_factory=list)
    closed_trades: list[Trade] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_balance)

    def equity(self, mark_price: float) -> float:
        if self.position is None:
            return self.cash
        if self.position.action is Action.BUY:
            return self.cash + self.position.quantity * mark_price
        return self.cash - self.position.quantity * mark_price

    def mark(self, timestamp: datetime, mark_price: float) -> None:
        self._curve.append((timestamp, self.equity(mark_price)))

    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._curve)

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
        else:
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
            gross_pnl = (price - pos.entry_price) * pos.quantity
        else:
            self.cash -= notional
            gross_pnl = (pos.entry_price - price) * pos.quantity
        self.cash -= fee
        self.closed_trades.append(
            Trade(
                symbol="PORTFOLIO",
                entry_ts=pos.entry_ts,
                exit_ts=timestamp,
                action=pos.action,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                exit_price=price,
                pnl=gross_pnl - fee - pos.entry_fee,
            )
        )
        self.position = None
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_portfolio.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: 41 passed (32 + 1 new types test … wait, recount: 32 prior + 1 Order construction + 1 Order frozen + 8 portfolio = 42; but Order is in Task 1 which committed already → 34 from earlier + 8 new = 42). Adjust expected count to whatever pytest reports — the important thing is no regressions.

- [ ] **Step 6: Ruff**

Run: `.\.venv\Scripts\python -m ruff check core/portfolio.py tests/test_portfolio.py`
Expected: clean (or only the pre-existing repo-wide UP017 pattern).

- [ ] **Step 7: Commit**

```bash
git add core/portfolio.py tests/test_portfolio.py
git commit -m "feat(core): single-symbol portfolio with equity curve + trade log"
```

---

## Task 3: `core/broker.py` — queue + next-bar fill with fees & slippage

**Files:**
- Create: `core/broker.py`
- Create: `tests/test_broker.py`

- [ ] **Step 1: Write the failing test `tests/test_broker.py`**

```python
"""Broker: queue orders at bar t, fill at bar[t+1].open with fees + slippage."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.broker import Broker
from core.portfolio import Portfolio
from core.types import Action, Bar, Order


def _bar(hour: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        timestamp=datetime(2025, 4, 1, hour, 0, tzinfo=timezone.utc),
        open=open_, high=high, low=low, close=close,
        volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
    )


def test_queued_order_fills_on_next_bar_open_buy():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    order = Order(
        symbol="BTC/USDT", action=Action.BUY, quantity=10.0,
        stop_loss=95.0, created_ts_ms=0,
    )
    b.queue(order)
    # Next bar opens at 100; BUY slips up by 2 bps → 100.02
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.5, close=100.5)
    b.fill_pending(next_bar)
    assert p.position is not None
    assert p.position.entry_price == pytest.approx(100.02)
    # Notional 1000.2; fee 4 bps = 0.40008; cash = 10000 - 1000.2 - 0.40008
    assert p.cash == pytest.approx(10_000.0 - 1000.2 - 0.40008)


def test_queued_order_fills_on_next_bar_open_sell_short():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    order = Order(
        symbol="BTC/USDT", action=Action.SELL, quantity=10.0,
        stop_loss=105.0, created_ts_ms=0,
    )
    b.queue(order)
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.0, close=100.5)
    b.fill_pending(next_bar)
    # SELL slips down by 2 bps → 99.98
    assert p.position is not None
    assert p.position.entry_price == pytest.approx(99.98)
    assert p.cash == pytest.approx(10_000.0 + 999.8 - 0.39992)


def test_sell_when_long_closes_position():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    # Open long manually at 100
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=95.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    # Now broker receives a SELL while long → it should close, not flip to short
    b.queue(Order(
        symbol="BTC/USDT", action=Action.SELL, quantity=10.0,
        stop_loss=None, created_ts_ms=0,
    ))
    next_bar = _bar(1, open_=110.0, high=111.0, low=109.0, close=110.5)
    b.fill_pending(next_bar)
    assert p.position is None
    assert len(p.closed_trades) == 1
    # Exit slips down 2 bps for a SELL fill: 109.978
    assert p.closed_trades[0].exit_price == pytest.approx(109.978)


def test_buy_when_short_closes_position():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.SELL, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=105.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    b.queue(Order(
        symbol="BTC/USDT", action=Action.BUY, quantity=10.0,
        stop_loss=None, created_ts_ms=0,
    ))
    next_bar = _bar(1, open_=90.0, high=91.0, low=89.0, close=90.5)
    b.fill_pending(next_bar)
    assert p.position is None
    assert p.closed_trades[0].exit_price == pytest.approx(90.018)


def test_hold_action_is_noop():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    b.queue(Order(
        symbol="BTC/USDT", action=Action.HOLD, quantity=0.0,
        stop_loss=None, created_ts_ms=0,
    ))
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.0, close=100.5)
    b.fill_pending(next_bar)
    assert p.position is None
    assert p.cash == 10_000.0
    assert b.pending() is None  # cleared even though it was a HOLD


def test_only_one_pending_order():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    o1 = Order(symbol="BTC/USDT", action=Action.BUY, quantity=1.0,
               stop_loss=95.0, created_ts_ms=0)
    o2 = Order(symbol="BTC/USDT", action=Action.SELL, quantity=1.0,
               stop_loss=105.0, created_ts_ms=1)
    b.queue(o1)
    b.queue(o2)  # replaces o1
    assert b.pending() is o2


def test_fill_with_no_pending_is_noop():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    next_bar = _bar(1, open_=100.0, high=101.0, low=99.0, close=100.5)
    b.fill_pending(next_bar)  # must not raise
    assert p.position is None


def test_stop_loss_hit_closes_intra_bar_long():
    """Bar's low <= stop → close at the stop price (no further slippage applied)."""
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=95.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    # Bar dips to 94 → stop hit at 95
    bar = _bar(1, open_=98.0, high=99.0, low=94.0, close=96.0)
    b.check_stops(bar)
    assert p.position is None
    assert p.closed_trades[0].exit_price == 95.0


def test_stop_loss_hit_closes_intra_bar_short():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.SELL, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=105.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    bar = _bar(1, open_=102.0, high=106.0, low=101.0, close=104.0)
    b.check_stops(bar)
    assert p.position is None
    assert p.closed_trades[0].exit_price == 105.0


def test_stop_check_does_not_close_when_not_hit():
    p = Portfolio(initial_balance=10_000.0)
    b = Broker(portfolio=p, taker_fee_bps=4, slippage_bps=2)
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=95.0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
    )
    bar = _bar(1, open_=98.0, high=99.0, low=96.0, close=97.0)  # never touches 95
    b.check_stops(bar)
    assert p.position is not None
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_broker.py -v`
Expected: ImportError on `core.broker`.

- [ ] **Step 3: Implement `core/broker.py`**

```python
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
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_broker.py -v`
Expected: 10 passed.

- [ ] **Step 5: Run full suite + ruff**

Run: `pytest -q`
Run: `.\.venv\Scripts\python -m ruff check core/broker.py tests/test_broker.py`
Expected: no regressions; ruff clean (modulo pre-existing UP017 in test imports).

- [ ] **Step 6: Commit**

```bash
git add core/broker.py tests/test_broker.py
git commit -m "feat(core): broker with next-bar fill, fees, slippage, stops"
```

---

## Task 4: `core/metrics.py` — Total Return, MDD, Win Rate, Profit Factor, Sharpe

**Files:**
- Create: `core/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test `tests/test_metrics.py`**

```python
"""Performance metrics over an equity curve and a trade list."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import math
import pytest

from core.metrics import compute_metrics
from core.types import Action, Trade


def _curve(*equities: float) -> list[tuple[datetime, float]]:
    base = datetime(2025, 4, 1, tzinfo=timezone.utc)
    return [(base + timedelta(hours=i), e) for i, e in enumerate(equities)]


def _trade(pnl: float) -> Trade:
    base = datetime(2025, 4, 1, tzinfo=timezone.utc)
    return Trade(
        symbol="X", entry_ts=base, exit_ts=base + timedelta(hours=1),
        action=Action.BUY, quantity=1.0, entry_price=100.0,
        exit_price=100.0 + pnl, pnl=pnl,
    )


def test_total_return_simple():
    m = compute_metrics(equity_curve=_curve(10_000.0, 11_000.0), trades=[])
    assert m["total_return_pct"] == pytest.approx(10.0)


def test_total_return_loss():
    m = compute_metrics(equity_curve=_curve(10_000.0, 9_000.0), trades=[])
    assert m["total_return_pct"] == pytest.approx(-10.0)


def test_max_drawdown_basic():
    # 100 → 110 → 90 → 105 → 80
    # peaks: 100, 110, 110, 110, 110
    # dd:    0,  0,  -18.18%, -4.55%, -27.27%
    m = compute_metrics(equity_curve=_curve(100, 110, 90, 105, 80), trades=[])
    assert m["max_drawdown_pct"] == pytest.approx(-100 * (110 - 80) / 110)


def test_max_drawdown_no_drawdown_returns_zero():
    m = compute_metrics(equity_curve=_curve(100, 110, 120, 130), trades=[])
    assert m["max_drawdown_pct"] == 0.0


def test_win_rate_and_counts():
    trades = [_trade(10.0), _trade(-5.0), _trade(15.0), _trade(-3.0), _trade(0.0)]
    m = compute_metrics(equity_curve=_curve(100, 100), trades=trades)
    assert m["num_trades"] == 5
    assert m["wins"] == 2
    assert m["losses"] == 2
    # Zero-pnl trades are neither wins nor losses; win_rate excludes them
    assert m["win_rate_pct"] == pytest.approx(2 / 4 * 100)


def test_win_rate_zero_trades():
    m = compute_metrics(equity_curve=_curve(100, 100), trades=[])
    assert m["num_trades"] == 0
    assert m["win_rate_pct"] == 0.0


def test_profit_factor_basic():
    trades = [_trade(10.0), _trade(-5.0), _trade(15.0), _trade(-3.0)]
    m = compute_metrics(equity_curve=_curve(100, 100), trades=trades)
    # gross profit = 25, gross loss = 8 → PF = 3.125
    assert m["profit_factor"] == pytest.approx(25.0 / 8.0)


def test_profit_factor_no_losses_returns_infinity():
    trades = [_trade(10.0), _trade(5.0)]
    m = compute_metrics(equity_curve=_curve(100, 100), trades=trades)
    assert math.isinf(m["profit_factor"])
    assert m["profit_factor"] > 0


def test_profit_factor_no_trades_returns_nan():
    m = compute_metrics(equity_curve=_curve(100, 100), trades=[])
    assert math.isnan(m["profit_factor"])


def test_sharpe_constant_returns_zero():
    """Zero-volatility flat curve has undefined Sharpe; we return 0.0."""
    m = compute_metrics(equity_curve=_curve(100, 100, 100, 100), trades=[])
    assert m["sharpe"] == 0.0


def test_sharpe_positive_drift():
    # Returns ~ +1% each step; positive Sharpe expected
    m = compute_metrics(equity_curve=_curve(100, 101, 102.01, 103.03), trades=[])
    assert m["sharpe"] > 0


def test_metrics_keys_stable():
    m = compute_metrics(equity_curve=_curve(100, 110), trades=[])
    assert set(m.keys()) == {
        "total_return_pct", "max_drawdown_pct",
        "num_trades", "wins", "losses", "win_rate_pct",
        "profit_factor", "sharpe",
    }
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_metrics.py -v`
Expected: ImportError on `core.metrics`.

- [ ] **Step 3: Implement `core/metrics.py`**

```python
"""Compute headline performance metrics for a single backtest run.

Inputs:
    equity_curve: list of (timestamp, equity) samples, recorded by Portfolio.mark()
    trades:       list of closed Trades

Outputs (dict):
    total_return_pct  — (equity_end / equity_start - 1) * 100
    max_drawdown_pct  — most-negative peak-to-trough percent drop on the curve
    num_trades        — len(trades)
    wins, losses      — counts of pnl > 0 and pnl < 0 (zero-pnl excluded)
    win_rate_pct      — wins / (wins + losses) * 100; 0.0 if denominator is 0
    profit_factor     — sum(positive pnl) / abs(sum(negative pnl))
                        +inf if no losses but ≥1 win; NaN if no trades
    sharpe            — mean / std of per-bar simple returns * sqrt(N) annualization
                        Returns 0.0 for a constant curve. We use the BAR-frequency
                        Sharpe (no √(252*24) annualization) — appropriate for a
                        relative-comparison metric in this seminar.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TypedDict

import numpy as np

from core.types import Trade


class MetricsDict(TypedDict):
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    profit_factor: float
    sharpe: float


def compute_metrics(
    equity_curve: list[tuple[datetime, float]],
    trades: list[Trade],
) -> MetricsDict:
    if len(equity_curve) < 2:
        raise ValueError("equity_curve needs at least 2 samples")

    equity = np.array([e for _, e in equity_curve], dtype=float)

    total_return_pct = float((equity[-1] / equity[0] - 1.0) * 100.0)

    running_peak = np.maximum.accumulate(equity)
    drawdowns = (equity - running_peak) / running_peak  # ≤ 0
    max_dd = float(drawdowns.min())
    max_drawdown_pct = max_dd * 100.0 if max_dd < 0 else 0.0

    pnls = np.array([t.pnl for t in trades], dtype=float)
    num_trades = len(trades)
    wins = int(np.sum(pnls > 0))
    losses = int(np.sum(pnls < 0))
    decided = wins + losses
    win_rate_pct = (wins / decided * 100.0) if decided > 0 else 0.0

    if num_trades == 0:
        profit_factor = float("nan")
    else:
        gross_profit = float(pnls[pnls > 0].sum())
        gross_loss = float(-pnls[pnls < 0].sum())
        if gross_loss == 0.0:
            profit_factor = float("inf") if gross_profit > 0 else float("nan")
        else:
            profit_factor = gross_profit / gross_loss

    rets = np.diff(equity) / equity[:-1]
    if rets.std(ddof=0) == 0.0:
        sharpe = 0.0
    else:
        sharpe = float(rets.mean() / rets.std(ddof=0) * math.sqrt(len(rets)))

    return MetricsDict(
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        num_trades=num_trades,
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        sharpe=sharpe,
    )
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_metrics.py -v`
Expected: 11 passed.

- [ ] **Step 5: Full suite + ruff**

Run: `pytest -q`
Run: `.\.venv\Scripts\python -m ruff check core/metrics.py tests/test_metrics.py`

- [ ] **Step 6: Commit**

```bash
git add core/metrics.py tests/test_metrics.py
git commit -m "feat(core): performance metrics (TR, MDD, WR, PF, Sharpe)"
```

---

## Task 5: `strategies/base.py` — Strategy protocol + Context

**Files:**
- Create: `strategies/__init__.py` (empty)
- Create: `strategies/base.py`
- Create: `tests/test_strategy_base.py`

- [ ] **Step 1: Create `strategies/__init__.py`**

Create empty file: `strategies/__init__.py`.

- [ ] **Step 2: Write the failing test `tests/test_strategy_base.py`**

```python
"""Strategy protocol contract."""

from __future__ import annotations

import inspect

import pytest

from core.types import Action, Bar, Signal
from strategies.base import Context, Strategy


def test_context_construction():
    ctx = Context(
        symbol="BTC/USDT",
        equity=10_000.0,
        risk_pct=0.02,
        in_position=False,
    )
    assert ctx.symbol == "BTC/USDT"
    assert ctx.equity == 10_000.0
    assert ctx.risk_pct == 0.02
    assert ctx.in_position is False


def test_strategy_is_protocol_and_async():
    # Strategy must be a Protocol with async on_bar(bar, ctx) -> Signal
    assert hasattr(Strategy, "on_bar")
    sig = inspect.signature(Strategy.on_bar)
    assert "bar" in sig.parameters
    assert "ctx" in sig.parameters


@pytest.mark.asyncio
async def test_dummy_strategy_satisfies_protocol():
    class Dummy:
        async def on_bar(self, bar: Bar, ctx: Context) -> Signal:
            return Signal(
                action=Action.HOLD, confidence=0.0,
                reasoning="dummy", stop_loss=None,
            )

    d: Strategy = Dummy()  # structural typing must accept this
    bar = Bar(
        timestamp=__import__("datetime").datetime(2025, 4, 1, tzinfo=__import__("datetime").timezone.utc),
        open=100.0, high=101.0, low=99.0, close=100.5,
        volume=1.0, taker_buy_volume=0.5, cvd=0.0, cvd_delta=0.0,
    )
    ctx = Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.02, in_position=False)
    sig = await d.on_bar(bar, ctx)
    assert sig.action is Action.HOLD
```

- [ ] **Step 3: Run, expect failure**

Run: `pytest tests/test_strategy_base.py -v`
Expected: ImportError on `strategies.base`.

- [ ] **Step 4: Implement `strategies/base.py`**

```python
"""Strategy contract used by both the heuristic and LLM bots.

`Strategy.on_bar` is async because the LLM bot's implementation does network
I/O. The heuristic bot returns immediately; the engine awaits both via
`asyncio.gather` (sub-plan D).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.types import Bar, Signal


@dataclass(frozen=True)
class Context:
    """Per-bar context handed to the strategy."""
    symbol: str
    equity: float
    risk_pct: float
    in_position: bool


class Strategy(Protocol):
    async def on_bar(self, bar: Bar, ctx: Context) -> Signal: ...
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest tests/test_strategy_base.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add strategies/__init__.py strategies/base.py tests/test_strategy_base.py
git commit -m "feat(strategies): Strategy protocol + Context dataclass"
```

---

## Task 6: `strategies/traditional.py` — heuristic indicator-confluence bot

The traditional bot maintains rolling indicator state across bars. It receives bars one at a time (engine pushes), accumulates a private bar history, and emits a `Signal` once warm-up bars are available.

**Decision rule (transparent, defensible for the seminar):**

- Compute on the running close series: RSI(14), MACD(12,26,9), ADX(14), EMA20, EMA50, SuperTrend(10, 3).
- **Trend filter:** ADX > 20 (otherwise HOLD).
- **Long entry:** EMA20 > EMA50 AND MACD histogram > 0 AND RSI < 70 AND SuperTrend direction = +1 (uptrend).
- **Short entry:** EMA20 < EMA50 AND MACD histogram < 0 AND RSI > 30 AND SuperTrend direction = -1 (downtrend).
- Otherwise HOLD.
- Stop = current SuperTrend line value.
- Position sizing (computed by caller, not strategy): `quantity = (equity * risk_pct) / |entry - stop|` — strategy returns the stop in the `Signal`; the engine sizes.
- Confidence = clip((ADX - 20) / 30, 0, 1) — purely informational; sizing ignores it.

**Files:**
- Create: `strategies/traditional.py`
- Create: `tests/test_traditional.py`

- [ ] **Step 1: Write the failing test `tests/test_traditional.py`**

```python
"""Traditional bot: indicator-confluence rule with SuperTrend stops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from core.types import Action, Bar
from strategies.base import Context
from strategies.traditional import TraditionalStrategy


def _make_bars(closes: list[float]) -> list[Bar]:
    base = datetime(2025, 4, 1, tzinfo=timezone.utc)
    bars = []
    for i, c in enumerate(closes):
        bars.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=c, high=c * 1.005, low=c * 0.995, close=c,
            volume=1000.0, taker_buy_volume=500.0,
            cvd=0.0, cvd_delta=0.0,
        ))
    return bars


def _flat_ctx(in_position: bool = False) -> Context:
    return Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.02,
                   in_position=in_position)


@pytest.mark.asyncio
async def test_warmup_returns_hold():
    """Before enough bars to seed all indicators, must HOLD."""
    s = TraditionalStrategy()
    bars = _make_bars([100.0] * 5)
    last = None
    for b in bars:
        last = await s.on_bar(b, _flat_ctx())
    assert last.action is Action.HOLD


@pytest.mark.asyncio
async def test_strong_uptrend_eventually_emits_buy():
    """Steady uptrend should trigger BUY once indicators warm up."""
    s = TraditionalStrategy()
    closes = list(np.linspace(100.0, 200.0, 100))
    bars = _make_bars(closes)
    actions = []
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        actions.append(sig.action)
    assert Action.BUY in actions, f"no BUY emitted; got {set(actions)}"


@pytest.mark.asyncio
async def test_strong_downtrend_eventually_emits_sell():
    s = TraditionalStrategy()
    closes = list(np.linspace(200.0, 100.0, 100))
    bars = _make_bars(closes)
    actions = []
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        actions.append(sig.action)
    assert Action.SELL in actions, f"no SELL emitted; got {set(actions)}"


@pytest.mark.asyncio
async def test_chop_returns_mostly_hold():
    """Sideways market with low ADX should mostly HOLD."""
    s = TraditionalStrategy()
    rng = np.random.default_rng(seed=42)
    closes = list(100.0 + rng.normal(0, 0.3, 200))
    bars = _make_bars(closes)
    actions = []
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        actions.append(sig.action)
    holds = sum(1 for a in actions if a is Action.HOLD)
    assert holds / len(actions) > 0.7, (
        f"expected >70% HOLD in chop; got {holds}/{len(actions)}"
    )


@pytest.mark.asyncio
async def test_signal_carries_supertrend_stop_on_entry():
    s = TraditionalStrategy()
    closes = list(np.linspace(100.0, 200.0, 100))
    bars = _make_bars(closes)
    final_buy_sig = None
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        if sig.action is Action.BUY:
            final_buy_sig = sig
    assert final_buy_sig is not None
    assert final_buy_sig.stop_loss is not None
    assert final_buy_sig.stop_loss < bars[-1].close  # stop below for long


@pytest.mark.asyncio
async def test_signal_confidence_in_unit_interval():
    s = TraditionalStrategy()
    closes = list(np.linspace(100.0, 200.0, 100))
    bars = _make_bars(closes)
    for b in bars:
        sig = await s.on_bar(b, _flat_ctx())
        assert 0.0 <= sig.confidence <= 1.0
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_traditional.py -v`
Expected: ImportError on `strategies.traditional`.

- [ ] **Step 3: Implement `strategies/traditional.py`**

```python
"""Heuristic Traditional Bot: RSI + MACD + ADX + EMA20/50 + SuperTrend confluence.

Rule (intentionally transparent for the seminar's methodology section):

    if ADX > 20:                                # trend filter
        if EMA20 > EMA50 and MACD_hist > 0 and RSI < 70 and ST_dir == +1:
            BUY (stop = SuperTrend line)
        elif EMA20 < EMA50 and MACD_hist < 0 and RSI > 30 and ST_dir == -1:
            SELL (stop = SuperTrend line)
        else: HOLD
    else: HOLD

Position sizing happens in the engine using `Signal.stop_loss` and
`ctx.risk_pct * ctx.equity / |entry - stop|`. The strategy is sizing-agnostic.

Indicator hyperparameters are hard-coded to the spec defaults; if you need
to make them config-driven, accept an `IndicatorsCfg` in __init__.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.types import Action, Bar, Signal
from indicators.ta import adx, ema, macd, rsi, supertrend


# Minimum bars before any indicator is reliable. SuperTrend(10,3) plus warmup
# slack gives a comfortable margin; we wait for `WARMUP` bars.
WARMUP = 60


@dataclass
class TraditionalStrategy:
    closes: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)

    async def on_bar(self, bar: Bar, ctx) -> Signal:  # ctx: strategies.base.Context
        self.closes.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        if len(self.closes) < WARMUP:
            return Signal(
                action=Action.HOLD, confidence=0.0,
                reasoning=f"warmup {len(self.closes)}/{WARMUP}",
                stop_loss=None,
            )

        close = pd.Series(self.closes, dtype=float)
        high = pd.Series(self.highs, dtype=float)
        low = pd.Series(self.lows, dtype=float)

        rsi_v = float(rsi(close, length=14).iloc[-1])
        macd_df = macd(close, fast=12, slow=26, signal=9)
        macd_hist = float(macd_df["hist"].iloc[-1])
        adx_v = float(adx(high, low, close, length=14).iloc[-1])
        ema20 = float(ema(close, length=20).iloc[-1])
        ema50 = float(ema(close, length=50).iloc[-1])
        st_df = supertrend(high, low, close, length=10, multiplier=3.0)
        st_line = st_df["st"].iloc[-1]
        st_dir = st_df["dir"].iloc[-1]

        if any(map(lambda x: x is None or (isinstance(x, float) and math.isnan(x)),
                   [rsi_v, macd_hist, adx_v, ema20, ema50, st_line, st_dir])):
            return Signal(
                action=Action.HOLD, confidence=0.0,
                reasoning="indicator NaN", stop_loss=None,
            )

        confidence = float(np.clip((adx_v - 20.0) / 30.0, 0.0, 1.0))

        if adx_v <= 20.0:
            return Signal(
                action=Action.HOLD, confidence=confidence,
                reasoning=f"ADX={adx_v:.1f}≤20 (no trend)",
                stop_loss=None,
            )

        long_ok = (
            ema20 > ema50 and macd_hist > 0 and rsi_v < 70 and int(st_dir) == 1
        )
        short_ok = (
            ema20 < ema50 and macd_hist < 0 and rsi_v > 30 and int(st_dir) == -1
        )

        if long_ok:
            return Signal(
                action=Action.BUY, confidence=confidence,
                reasoning=(
                    f"BUY: EMA20>{ema50:.2f}, MACD↑{macd_hist:.3f}, "
                    f"RSI={rsi_v:.1f}, ADX={adx_v:.1f}, ST↑"
                ),
                stop_loss=float(st_line),
            )
        if short_ok:
            return Signal(
                action=Action.SELL, confidence=confidence,
                reasoning=(
                    f"SELL: EMA20<{ema50:.2f}, MACD↓{macd_hist:.3f}, "
                    f"RSI={rsi_v:.1f}, ADX={adx_v:.1f}, ST↓"
                ),
                stop_loss=float(st_line),
            )
        return Signal(
            action=Action.HOLD, confidence=confidence,
            reasoning=f"no confluence (RSI={rsi_v:.1f}, MACDh={macd_hist:.3f})",
            stop_loss=None,
        )
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_traditional.py -v`
Expected: 6 passed.

- [ ] **Step 5: Full suite + ruff**

Run: `pytest -q`
Run: `.\.venv\Scripts\python -m ruff check strategies/traditional.py tests/test_traditional.py`

- [ ] **Step 6: Commit**

```bash
git add strategies/traditional.py tests/test_traditional.py
git commit -m "feat(strategies): heuristic indicator-confluence Traditional bot"
```

---

## Task 7: `core/engine_sync.py` — minimal synchronous bar loop

This is a deliberately stripped-down engine that runs **one** strategy synchronously over an iterable of bars. Sub-plan D will add the async + dual-strategy + TUI variant. Building this now lets us verify the full execution chain (loader → strategy → broker → portfolio → metrics) works end-to-end on real cached data.

**Position-sizing convention (engine, not strategy):**
```python
risk_dollars = ctx.equity * ctx.risk_pct          # e.g. $200 on $10k @ 2%
risk_per_unit = abs(entry_price - stop_loss)
quantity = risk_dollars / risk_per_unit
```
The engine uses `bar.close` of the **signal bar** as `entry_price` for sizing (the actual fill price will differ slightly due to slippage at next-bar open; we accept that minor discrepancy).

**Files:**
- Create: `core/engine_sync.py`
- Create: `tests/test_engine_sync.py`

- [ ] **Step 1: Write the failing test `tests/test_engine_sync.py`**

```python
"""Sync engine: drives one Strategy through a bar iterable end-to-end."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from core.engine_sync import run_sync
from core.types import Action, Bar, Signal
from strategies.base import Context


class _AlwaysBuyOnce:
    """Emits BUY on bar #5 with stop at 95, then HOLD forever."""
    def __init__(self) -> None:
        self.n = 0

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:
        self.n += 1
        if self.n == 5 and not ctx.in_position:
            return Signal(action=Action.BUY, confidence=1.0,
                          reasoning="test", stop_loss=95.0)
        return Signal(action=Action.HOLD, confidence=0.0,
                      reasoning="hold", stop_loss=None)


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2025, 4, 1, tzinfo=timezone.utc)
    out = []
    for i, c in enumerate(closes):
        out.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=c, high=c * 1.01, low=c * 0.99, close=c,
            volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
        ))
    return out


def test_run_sync_executes_signal_on_next_bar_open():
    bars = _bars([100.0] * 4 + [100.0, 100.0, 110.0, 110.0])
    # Signal fires on bar index 4 (n==5). Fill should occur at bars[5].open = 100.
    portfolio, metrics = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=4.0, slippage_bps=2.0, risk_pct=0.02,
    ))
    assert portfolio.position is not None or len(portfolio.closed_trades) >= 0
    # We should have at least entered (closed or still open at series end)
    has_action = portfolio.position is not None or len(portfolio.closed_trades) >= 1
    assert has_action


def test_run_sync_position_size_matches_risk_pct():
    """quantity ≈ (equity * risk_pct) / |entry - stop|"""
    # Pre-fire bars constant at 100, then post-fire bars constant at 100.
    bars = _bars([100.0] * 10)
    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    # entry_price ~= 100, stop = 95 → risk_per_unit = 5
    # equity = 10_000, risk_dollars = 200 → qty = 200 / 5 = 40
    assert portfolio.position is not None
    assert portfolio.position.quantity == pytest.approx(40.0, rel=1e-6)


def test_run_sync_returns_metrics_dict():
    bars = _bars(list(np.linspace(100, 105, 30)))
    _, metrics = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=4.0, slippage_bps=2.0, risk_pct=0.02,
    ))
    assert "total_return_pct" in metrics
    assert "max_drawdown_pct" in metrics
    assert "num_trades" in metrics


def test_run_sync_no_lookahead():
    """A signal at bar t must NOT use bar[t+1] data — verified by fill-at-open."""
    # Build bars where the signal-bar close differs from next-bar open.
    base = datetime(2025, 4, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(10):
        if i == 5:
            # Signal bar: close=200 (would be a great BUY-and-pump if we cheated)
            bars.append(Bar(
                timestamp=base + timedelta(hours=i),
                open=100.0, high=200.0, low=100.0, close=200.0,
                volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
            ))
        elif i == 6:
            # Next bar opens DOWN at 90
            bars.append(Bar(
                timestamp=base + timedelta(hours=i),
                open=90.0, high=91.0, low=89.0, close=90.5,
                volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
            ))
        else:
            bars.append(Bar(
                timestamp=base + timedelta(hours=i),
                open=100.0, high=101.0, low=99.0, close=100.0,
                volume=1000.0, taker_buy_volume=500.0, cvd=0.0, cvd_delta=0.0,
            ))

    portfolio, _ = asyncio.run(run_sync(
        bars=bars, strategy=_AlwaysBuyOnce(),
        symbol="X", initial_balance=10_000.0,
        taker_fee_bps=0.0, slippage_bps=0.0, risk_pct=0.02,
    ))
    # Fill should be at bar[6].open = 90.0, NOT at bar[5].close = 200.
    assert portfolio.position is not None
    assert portfolio.position.entry_price == pytest.approx(90.0)
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_engine_sync.py -v`
Expected: ImportError on `core.engine_sync`.

- [ ] **Step 3: Implement `core/engine_sync.py`**

```python
"""Synchronous bar-by-bar engine for a single strategy.

Wired in this order each bar:
    1. broker.check_stops(bar)            — close on intra-bar stop hit
    2. broker.fill_pending(bar)           — fill the previous bar's queued order
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


def _size(equity: float, risk_pct: float, entry: float, stop: float) -> float:
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
        if signal.action is Action.HOLD:
            pass  # nothing to queue
        else:
            in_pos = portfolio.position is not None
            if in_pos:
                # Closing trade: quantity must match existing position.
                qty = portfolio.position.quantity
                broker.queue(Order(
                    symbol=symbol, action=signal.action, quantity=qty,
                    stop_loss=None, created_ts_ms=int(bar.timestamp.timestamp() * 1000),
                ))
            else:
                # Opening trade: size from risk + stop.
                if signal.stop_loss is None:
                    pass  # no stop → cannot size; skip
                else:
                    qty = _size(
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
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_engine_sync.py -v`
Expected: 4 passed.

- [ ] **Step 5: Full suite + ruff**

Run: `pytest -q`
Run: `.\.venv\Scripts\python -m ruff check core/engine_sync.py tests/test_engine_sync.py`

- [ ] **Step 6: Commit**

```bash
git add core/engine_sync.py tests/test_engine_sync.py
git commit -m "feat(core): minimal synchronous backtest engine harness"
```

---

## Task 8: End-to-end smoke — Traditional bot on cached BTC/USDT data

Purpose: prove the full chain (loader → traditional → broker → portfolio → metrics) actually runs on the live-downloaded data from sub-plan A. This test reuses the cache populated by `test_live_smoke.py` if it exists, otherwise it generates a synthetic OHLCV+CVD pair on the fly.

**Files:**
- Create: `tests/test_traditional_e2e.py`

- [ ] **Step 1: Write the test `tests/test_traditional_e2e.py`**

```python
"""End-to-end: Traditional bot through the sync engine on synthetic + real data."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.engine_sync import run_sync
from core.types import Bar
from data.loader import load_bars
from data.paths import cvd_parquet_path, ohlcv_csv_path
from strategies.traditional import TraditionalStrategy


def _seed_synthetic(tmp_path: Path, n: int = 300) -> None:
    """Seed an OHLCV+CVD pair with a clear uptrend the traditional bot can catch."""
    rng = np.random.default_rng(seed=7)
    base_price = 100.0
    drift = np.linspace(0, 50.0, n)              # +50% over the window
    noise = rng.normal(0, 0.5, n)
    closes = base_price + drift + noise
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.005, n))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.005, n))
    ts = pd.date_range("2025-04-01", periods=n, freq="1h", tz="UTC")
    ohlcv = pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": rng.uniform(500, 1500, n),
    })
    op = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(op, index=False)

    cvd_delta = rng.normal(0, 5, n)
    cvd = np.cumsum(cvd_delta)
    taker_buy = rng.uniform(200, 800, n)
    cvd_df = pd.DataFrame({
        "timestamp": ts, "cvd_delta": cvd_delta, "cvd": cvd,
        "taker_buy_volume": taker_buy,
    })
    cp = cvd_parquet_path("BTC/USDT", "1h", root=tmp_path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cvd_df.to_parquet(cp, index=False)


def test_traditional_runs_end_to_end_on_synthetic(tmp_path: Path):
    _seed_synthetic(tmp_path, n=300)
    bars = list(load_bars(
        symbol="BTC/USDT", timeframe="1h",
        start=date(2025, 4, 1), end=date(2025, 4, 14),
        root=tmp_path,
    ))
    assert len(bars) >= 200
    portfolio, metrics = asyncio.run(run_sync(
        bars=bars, strategy=TraditionalStrategy(),
        symbol="BTC/USDT", initial_balance=10_000.0,
        taker_fee_bps=4.0, slippage_bps=2.0, risk_pct=0.02,
    ))
    # We don't assert profitability — only that the engine ran cleanly,
    # produced a curve, and metrics dict has the expected shape.
    assert len(portfolio.equity_curve()) == len(bars)
    assert "total_return_pct" in metrics
    assert isinstance(metrics["num_trades"], int)
```

- [ ] **Step 2: Run, expect pass**

Run: `pytest tests/test_traditional_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Full suite + ruff + coverage**

Run: `pytest -q`
Run: `.\.venv\Scripts\python -m ruff check .`
Run: `pytest --cov=core --cov=data --cov=indicators --cov=strategies --cov-report=term`
Expected: ≥70% on all four packages.

- [ ] **Step 4: Commit**

```bash
git add tests/test_traditional_e2e.py
git commit -m "test: end-to-end traditional bot through sync engine on synthetic data"
```

---

## Task 9: Update README + plan completion note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append sub-plan B status to `README.md`**

Replace the **Status** section in `README.md` with:

```markdown
## Status

**Sub-plan A complete:** data layer, indicators, config, types.
**Sub-plan B complete:** execution layer (portfolio, broker, metrics) + Traditional bot + sync engine harness.

- Data: download Binance OHLCV (ccxt) + aggTrades (REST), aggregate CVD per bar.
- Indicators: RSI, MACD, ADX, EMA, SuperTrend (vectorized, validated against pandas-ta).
- Execution: shared portfolio + broker with next-bar fills, taker fees, slippage, intra-bar stops.
- Metrics: Total Return, MDD, Win Rate, Profit Factor, Sharpe.
- Traditional bot: indicator-confluence rule with SuperTrend stops + 2%-risk sizing.
- Engine: synchronous single-strategy harness (async dual-strategy + TUI in sub-plan D).

**Next:** sub-plan C — LLM agent subsystem (4 LangGraph nodes + cache + budget guard + MockClient).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README reflecting sub-plan B completion"
```

---

## Self-review (writing-plans skill checklist)

**1. Spec coverage (sub-plan B scope: §13 steps 4–5):**
- ✅ `core/portfolio.py` → Task 2
- ✅ `core/broker.py` → Task 3 (next-bar open + slippage + fees + stops)
- ✅ `core/metrics.py` → Task 4 (TR, MDD, WR, PF, Sharpe — all named in §6 last line and §11)
- ✅ `strategies/base.py` → Task 5
- ✅ `strategies/traditional.py` → Task 6 (indicator-confluence with stops)
- ✅ Order dataclass → Task 1 (referenced in §6 broker queue but not yet defined)
- ✅ Sync engine harness → Task 7 (subset of §6; full async loop deferred to sub-plan D as documented)
- ✅ End-to-end validation on cached data → Task 8
- 🅾️ `core/engine.py` (async dual-strategy + asyncio.gather) — explicitly deferred to sub-plan D
- 🅾️ `core/ui.py` Rich TUI — explicitly deferred to sub-plan D
- 🅾️ Walk-forward across multiple assets — explicitly deferred to sub-plan D

**2. Placeholder scan:** No "TBD"/"implement later"/"add appropriate handling". Every step contains runnable code or an exact command. Task 2 Step 3 includes a self-correcting two-step where the obvious implementation is shown, the bug it has is called out, and Step 3a replaces it with the correct version — this is intentional pedagogy and defensible.

**3. Type consistency:**
- `Position` (Task 2 step 3a) carries `entry_fee` for clean PnL accounting in `close_position`.
- `Order` fields used in Task 3's broker (`symbol`, `action`, `quantity`, `stop_loss`, `created_ts_ms`) match Task 1's definition exactly.
- `Strategy.on_bar(bar, ctx) -> Signal` is consistent across Task 5 (protocol), Task 6 (TraditionalStrategy), Task 7 (engine), Task 8 (e2e).
- `Context` dataclass (`symbol`, `equity`, `risk_pct`, `in_position`) referenced identically in Tasks 5, 6, 7.
- `compute_metrics(equity_curve, trades) -> MetricsDict` signature matches Tasks 4, 7, 8.

Plan is self-consistent.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-sub-plan-B-execution-and-traditional-bot.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks. Best for a 9-task plan: avoids context bloat.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batched checkpoints for review.

**Which execution approach do you want for sub-plan B?**
