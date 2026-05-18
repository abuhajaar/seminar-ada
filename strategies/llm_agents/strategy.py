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

import math
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from core.types import Action, Bar, Signal
from indicators.ta import adx, ema, macd, rsi, supertrend
from llm.client import LLMClient
from strategies.base import Context
from strategies.llm_agents.chart import render_chart
from strategies.llm_agents.graph import build_graph

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

# Enough bars to guarantee every indicator value is finite before invoking
# the graph. MACD(12,26,9).hist first non-NaN at original index 25+8=33
# (1-indexed bar 34), and SuperTrend(10,3) needs ~10 bars of ATR seasoning.
# 60 picks a comfortable ceiling that also matches TraditionalStrategy's
# warmup floor (audit H2). Pre-fix value was 30, which produced
# ``macd_hist=nan`` in the technical analyst prompt.
WARMUP_BARS: int = 60


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
    consensus_weights: dict[str, float] | None = None
    consensus_threshold: float | None = None

    _bars: deque[Bar] = field(default_factory=deque, init=False, repr=False)
    _graph: CompiledStateGraph | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Build the compiled graph once. `client` is captured per-node via
        # `functools.partial` inside `build_graph`, so subsequent invocations
        # are I/O-free at graph-build time.
        self._graph = build_graph(
            client=self.client,
            consensus_weights=self.consensus_weights,
            consensus_threshold=self.consensus_threshold,
        )

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
        highs = pd.Series([b.high for b in self._bars], dtype=float)
        lows = pd.Series([b.low for b in self._bars], dtype=float)
        ema_fast_v = float(ema(closes, length=self.ema_fast_n).iloc[-1])
        ema_slow_v = float(ema(closes, length=self.ema_slow_n).iloc[-1])
        rsi_v = float(rsi(closes, length=self.rsi_n).iloc[-1])
        # MACD parameters are the canonical 12/26/9 regardless of the analyst's
        # EMA pair (which feeds prompt features, not MACD). Keeping these literal
        # prevents a future refactor from accidentally wiring `ema_fast_n` /
        # `ema_slow_n` into MACD and breaking spec-equivalence with TraditionalStrategy.
        macd_df = macd(closes, fast=12, slow=26, signal=9)
        macd_h = float(macd_df["hist"].iloc[-1])
        # ADX(14) — the regime filter. ``TraditionalStrategy`` uses it to skip
        # chop (ADX <= 20); the LLM technical prompt advertises this key (see
        # `prompts.py:36`) so we must actually supply it (audit H1).
        adx_v = float(adx(highs, lows, closes, length=14).iloc[-1])

        # SuperTrend(10, 3) — same parameters as `TraditionalStrategy` so the
        # LLM bot's stop placement and risk-sized position notional are directly
        # comparable in the seminar demo. The line itself is the stop level;
        # `dir` is the regime sign (+1 long-friendly, -1 short-friendly) and
        # acts as a side-aware gate (re-audit C3): the consensus may vote
        # SELL during an up-regime (or BUY during a down-regime), in which
        # case `st_line` sits on the wrong side of price and the engine's
        # H4 stop-direction gate (`core/engine.py:115`) silently drops the
        # order. We reject those conflicting signals at source by emitting
        # HOLD instead of leaking a mis-sided stop downstream.
        st_df = supertrend(highs, lows, closes, length=10, multiplier=3.0)
        st_line_raw = st_df["st"].iloc[-1]
        st_dir_raw = st_df["dir"].iloc[-1]
        st_line: float | None = (
            float(st_line_raw) if not pd.isna(st_line_raw) else None
        )
        st_dir: int | None = (
            int(st_dir_raw) if not pd.isna(st_dir_raw) else None
        )

        features: dict[str, float] = {
            "ema_fast": ema_fast_v,
            "ema_slow": ema_slow_v,
            "rsi": rsi_v,
            "macd_hist": macd_h,
            "adx": adx_v,
            "cvd": float(bar.cvd),
            "cvd_delta": float(bar.cvd_delta),
        }

        # Defensive NaN guard: a pathological bar sequence (e.g. perfectly flat
        # closes ⇒ RSI 0/0) can still yield NaN even past warmup. ``_fmt`` in
        # prompts.py renders NaN as the literal string ``"nan"``, which then
        # leaks into the technical analyst prompt and degrades model output.
        # Short-circuit to HOLD instead of invoking the graph (audit H3).
        nan_keys = [k for k, v in features.items() if not math.isfinite(v)]
        if nan_keys:
            return Signal(
                action=Action.HOLD,
                confidence=0.0,
                reasoning=f"indicator nan: {','.join(nan_keys)}",
                stop_loss=None,
            )

        image_b64: str | None = None
        if self.render_image:
            window = list(self._bars)[-self.image_window_bars :]
            image_b64 = render_chart(window)

        # The chart bytes are persisted as `visual_input.png` by
        # `RecordingClient` (next to `visual_input.txt`) — that filename is the
        # single source of truth for "the exact image the visual agent saw".
        # No separate `chart.png` is written: it would only ever be a duplicate
        # and risks silently diverging from the agent's actual input later.

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
        # Rebuild the graph when a sink is active so each analyst node's
        # `LLMClient.complete` call lands in the sink via the `RecordingClient`
        # wrapper. The compiled graph captures the client via `functools.partial`
        # at build time, so we cannot rewire the existing `_graph`. This rebuild
        # is microsecond-scale pure Python and only fires when artifacts are
        # being dumped (seminar demo); production runs are unaffected.
        graph = self._graph
        if ctx.artifact_sink is not None:
            from llm.recording import RecordingClient

            recording_client = RecordingClient(inner=self.client, sink=ctx.artifact_sink)
            graph = build_graph(
                client=recording_client,
                consensus_weights=self.consensus_weights,
                consensus_threshold=self.consensus_threshold,
            )

        # `_graph` is always set by `__post_init__`; the Optional annotation is
        # only to satisfy the dataclass field default. Hence the union-attr ignore.
        final = await graph.ainvoke(initial)  # type: ignore[union-attr]
        d = final["decision"]
        # Side-aware regime gate (re-audit C3): reject BUY in a down-regime
        # and SELL in an up-regime. Without this, `st_line` would be a
        # wrong-sided stop (long stop for a short trade or vice versa) and
        # the engine would silently drop the order at the H4 stop-direction
        # gate — the same symptom that produced "zero LLM short trades" in
        # historical runs. Explicit HOLD at source surfaces the rejection
        # in the signal reasoning instead of swallowing it downstream.
        if (
            (d.action is Action.BUY and st_dir == -1)
            or (d.action is Action.SELL and st_dir == 1)
        ):
            regime = "up" if st_dir == 1 else "down"
            if ctx.artifact_sink is not None:
                ctx.artifact_sink.write_json(
                    "decision_output.json",
                    {
                        "action": d.action.value,
                        "confidence": d.confidence,
                        "rationale": d.rationale,
                        "regime_gate_st_dir": st_dir,
                        "regime_gate_overridden": True,
                    },
                )
            return Signal(
                action=Action.HOLD,
                confidence=d.confidence,
                reasoning=(
                    f"regime-conflict: consensus={d.action.value} "
                    f"st_dir={st_dir} ({regime}-regime); {d.rationale}"
                ),
                stop_loss=None,
            )
        # Only emit a stop on directional signals — HOLD does not open a
        # position, so `stop_loss` is meaningless there. `core/engine.py`
        # gates `_open_long/_open_short` on `signal.stop_loss is not None`,
        # so without this the bot can never enter (historical bug: zero LLM
        # trades across every run prior to this fix).
        stop_loss = st_line if d.action in (Action.BUY, Action.SELL) else None
        if ctx.artifact_sink is not None:
            ctx.artifact_sink.write_json(
                "decision_output.json",
                {
                    "action": d.action.value,
                    "confidence": d.confidence,
                    "rationale": d.rationale,
                    "regime_gate_st_dir": st_dir,
                    "regime_gate_overridden": False,
                },
            )
        return Signal(
            action=d.action,
            confidence=d.confidence,
            reasoning=d.rationale,
            stop_loss=stop_loss,
        )
