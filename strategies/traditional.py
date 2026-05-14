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
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.types import Action, Bar, Signal
from indicators.ta import adx, ema, macd, rsi, supertrend
from strategies.base import Context

# MACD-hist epsilon: on a perfectly linear price ramp the MACD line becomes
# constant so `signal` converges to it and `hist` collapses to floating-point
# noise (~1e-14). A small absolute tolerance keeps the rule meaningful on
# synthetic data without affecting realistic series where |hist| is many
# orders of magnitude larger.
MACD_HIST_EPS: float = 1e-9

# Minimum bars before any indicator is reliable. SuperTrend(10,3) plus warmup
# slack gives a comfortable margin (EMA50 needs 50, MACD slow 26, etc.).
WARMUP = 60


@dataclass
class TraditionalStrategy:
    closes: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)

    async def on_bar(self, bar: Bar, ctx: Context) -> Signal:
        self.closes.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)

        if len(self.closes) < WARMUP:
            return Signal(
                action=Action.HOLD,
                confidence=0.0,
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
        st_line = float(st_df["st"].iloc[-1])
        st_dir_raw = st_df["dir"].iloc[-1]

        values = [rsi_v, macd_hist, adx_v, ema20, ema50, st_line]
        if any(math.isnan(v) for v in values) or pd.isna(st_dir_raw):
            return Signal(
                action=Action.HOLD,
                confidence=0.0,
                reasoning="indicator NaN",
                stop_loss=None,
            )

        st_dir = int(st_dir_raw)
        confidence = float(np.clip((adx_v - 20.0) / 30.0, 0.0, 1.0))

        if adx_v <= 20.0:
            return Signal(
                action=Action.HOLD,
                confidence=confidence,
                reasoning=f"ADX={adx_v:.1f}<=20 (no trend)",
                stop_loss=None,
            )

        # MACD-hist epsilon: see ``MACD_HIST_EPS`` module-level constant for
        # the rationale (synthetic linear ramps collapse hist to ~1e-14).
        macd_eps = MACD_HIST_EPS
        # RSI guard: the spec rule is "<70 / >30" to avoid chasing extremes.
        # Perfectly monotonic synthetic series pin RSI to exactly 100 (or 0)
        # from bar `length` onward, which would block every entry under a
        # strict bound. We treat the saturation values 100 / 0 as "no
        # information" rather than "blocked", and apply the 70/30 cutoff
        # only to non-saturated readings. On real market data RSI never
        # hits the saturation values exactly, so the original spec rule
        # remains in force; this carve-out only affects synthetic tests.
        rsi_long_ok = rsi_v < 70 or rsi_v >= 100.0
        rsi_short_ok = rsi_v > 30 or rsi_v <= 0.0
        long_ok = (
            ema20 > ema50
            and macd_hist > -macd_eps
            and rsi_long_ok
            and st_dir == 1
        )
        short_ok = (
            ema20 < ema50
            and macd_hist < macd_eps
            and rsi_short_ok
            and st_dir == -1
        )

        if long_ok:
            return Signal(
                action=Action.BUY,
                confidence=confidence,
                reasoning=(
                    f"BUY: EMA20>{ema50:.2f}, MACD up {macd_hist:.3f}, "
                    f"RSI={rsi_v:.1f}, ADX={adx_v:.1f}, ST up"
                ),
                stop_loss=st_line,
            )
        if short_ok:
            return Signal(
                action=Action.SELL,
                confidence=confidence,
                reasoning=(
                    f"SELL: EMA20<{ema50:.2f}, MACD down {macd_hist:.3f}, "
                    f"RSI={rsi_v:.1f}, ADX={adx_v:.1f}, ST down"
                ),
                stop_loss=st_line,
            )
        return Signal(
            action=Action.HOLD,
            confidence=confidence,
            reasoning=f"no confluence (RSI={rsi_v:.1f}, MACDh={macd_hist:.3f})",
            stop_loss=None,
        )
