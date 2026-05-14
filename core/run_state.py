"""Shared engine↔UI state container.

`RunState` is the single source of truth shared between the async engine
(writer) and the Rich TUI (reader). With a single asyncio event loop (no
threads), `snapshot()` returns a shallow dict copy so the UI sees a
consistent frame even if the engine mutates lists between renders.

`llm_reasoning` is a bounded `deque(maxlen=10)` so the UI only ever shows
the last 10 LLM rationales without unbounded memory growth.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RunState:
    """Live state for one walk-forward run, shared between engine and TUI.

    Engine code mutates fields in place; the UI reads via `snapshot()`.
    Field names are part of the public contract — downstream UI code and
    tests rely on these exact names.
    """

    # Run identity — set once at construction.
    symbol: str
    timeframe: str
    total_bars: int

    # Per-bar progress (engine writes each tick).
    current_bar: int = 0
    bar_ts: datetime | None = None
    bar_close: float = 0.0

    # Equity & curves.
    trad_equity: float = 0.0
    llm_equity: float = 0.0
    trad_curve: list[float] = field(default_factory=list)
    llm_curve: list[float] = field(default_factory=list)

    # Trade stats.
    trad_trades: int = 0
    llm_trades: int = 0
    trad_win_pct: float = 0.0
    llm_win_pct: float = 0.0
    trad_mdd: float = 0.0  # negative number, e.g. -0.042 for -4.2%
    llm_mdd: float = 0.0

    # Most-recent traditional-bot output.
    last_trad_signal: str = "HOLD"
    last_trad_rationale: str = ""

    # Last 10 LLM rationale strings (bounded so memory stays flat).
    llm_reasoning: deque[str] = field(
        default_factory=lambda: deque(maxlen=10)
    )

    # Budget-guard surface.
    cache_hits: int = 0
    cache_misses: int = 0
    spend_usd: float = 0.0
    budget_usd: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow dict copy safe for the UI to read.

        Mutable collections (`trad_curve`, `llm_curve`, `llm_reasoning`)
        are copied into fresh plain `list`s so the engine can keep
        mutating the originals without tearing the UI frame.
        """
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_bars": self.total_bars,
            "current_bar": self.current_bar,
            "bar_ts": self.bar_ts,
            "bar_close": self.bar_close,
            "trad_equity": self.trad_equity,
            "llm_equity": self.llm_equity,
            "trad_curve": list(self.trad_curve),
            "llm_curve": list(self.llm_curve),
            "trad_trades": self.trad_trades,
            "llm_trades": self.llm_trades,
            "trad_win_pct": self.trad_win_pct,
            "llm_win_pct": self.llm_win_pct,
            "trad_mdd": self.trad_mdd,
            "llm_mdd": self.llm_mdd,
            "last_trad_signal": self.last_trad_signal,
            "last_trad_rationale": self.last_trad_rationale,
            "llm_reasoning": list(self.llm_reasoning),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "spend_usd": self.spend_usd,
            "budget_usd": self.budget_usd,
        }
