"""End-to-end strategy: features + chart → LangGraph → Signal.

`LLMAgentStrategy` conforms to `strategies.base.Strategy` so the existing sync
and (sub-plan D's) async engines can drive it identically to `TraditionalStrategy`.

The strategy maintains its own rolling OHLCV buffer (matching the
`TraditionalStrategy` pattern) because `Context` deliberately does not carry
history — bars are pushed once per `on_bar` call. A `WARMUP_BARS` guard short-
circuits to HOLD without invoking the graph (no LLM cost) during warmup.

`render_image=False` skips the (relatively slow) mplfinance render — useful for
unit tests that only want to verify the strategy wires up and returns a Signal.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from core.types import Action, Bar, Signal
from indicators.ta import ema, macd, rsi
from llm.client import LLMClient
from strategies.base import Context
from strategies.llm_agents.chart import render_chart
from strategies.llm_agents.graph import build_graph

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

# Enough bars for EMA26 + MACD-slow warmup; matches TraditionalStrategy's
# minimum-confidence floor at 30 (we don't need the SuperTrend depth here).
WARMUP_BARS: int = 30


@dataclass
class LLMAgentStrategy:
    """Bridges the `Strategy` protocol to the 4-agent LangGraph.

    Args:
        client: Any `LLMClient` (typically wrapped in `CachedClient`).
        model: Model id passed to the client (e.g. ``"mock"`` or an OpenRouter
            slug). Cached results key on this; changing the model invalidates
            the cache.
        image_window_bars: How many most-recent bars to render for the Visual
            agent (spec §10 ``llm.image_window_bars``).
        render_image: Set ``False`` to skip mplfinance render (tests / CI).
        ema_fast_n / ema_slow_n / rsi_n: Indicator lengths fed into the
            Technical agent's prompt features.
    """

    client: LLMClient
    model: str
    image_window_bars: int = 60
    render_image: bool = True
    ema_fast_n: int = 12
    ema_slow_n: int = 26
    rsi_n: int = 14

    _bars: deque[Bar] = field(default_factory=deque, init=False, repr=False)
    _graph: CompiledStateGraph | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Build the compiled graph once. `client` is captured per-node via
        # `functools.partial` inside `build_graph`, so subsequent invocations
        # are I/O-free at graph-build time.
        self._graph = build_graph(client=self.client)

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:  # noqa: ARG002 (ctx reserved for future use)
        self._bars.append(bar)
        if len(self._bars) < WARMUP_BARS:
            return Signal(
                action=Action.HOLD,
                confidence=0.0,
                reasoning=f"warmup {len(self._bars)}/{WARMUP_BARS}",
                stop_loss=None,
            )

        # Indicator features (latest values only — analyst prompts read scalars).
        closes = pd.Series([b.close for b in self._bars], dtype=float)
        ema_fast_v = float(ema(closes, length=self.ema_fast_n).iloc[-1])
        ema_slow_v = float(ema(closes, length=self.ema_slow_n).iloc[-1])
        rsi_v = float(rsi(closes, length=self.rsi_n).iloc[-1])
        # MACD parameters are the canonical 12/26/9 regardless of the analyst's
        # EMA pair (which feeds prompt features, not MACD). Keeping these literal
        # prevents a future refactor from accidentally wiring `ema_fast_n` /
        # `ema_slow_n` into MACD and breaking spec-equivalence with TraditionalStrategy.
        macd_df = macd(closes, fast=12, slow=26, signal=9)
        macd_h = float(macd_df["hist"].iloc[-1])

        features: dict[str, float] = {
            "ema_fast": ema_fast_v,
            "ema_slow": ema_slow_v,
            "rsi": rsi_v,
            "macd_hist": macd_h,
            "cvd": float(bar.cvd),
            "cvd_delta": float(bar.cvd_delta),
        }

        image_b64: str | None = None
        if self.render_image:
            window = list(self._bars)[-self.image_window_bars :]
            image_b64 = render_chart(window)

        # `bar_ts` is ms-since-epoch (cache key, spec Q2). `Bar.timestamp` is
        # tz-aware `datetime`; convert at the boundary so downstream nodes see
        # a plain int.
        bar_ts_ms = int(bar.timestamp.timestamp() * 1000)

        initial = {
            "bar_ts": bar_ts_ms,
            "features": features,
            "image_b64": image_b64,
            "model": self.model,
            "technical": None,
            "visual": None,
            "qabba": None,
            "decision": None,
        }
        # `_graph` is always set by `__post_init__`; the Optional annotation is
        # only to satisfy the dataclass field default. Hence the union-attr ignore.
        final = await self._graph.ainvoke(initial)  # type: ignore[union-attr]
        d = final["decision"]
        return Signal(
            action=d.action,
            confidence=d.confidence,
            reasoning=d.rationale,
            stop_loss=None,
        )
