"""Render a candlestick chart from Bars to a base64-encoded PNG.

Consumed by the Visual agent. The Agg backend produces PNGs that are
**byte-stable within a single process and matplotlib/mplfinance version**,
which is what makes the bar-keyed LLM cache key (which hashes ``image_b64``)
work across replays *in the same environment*. PNG bytes may differ across
matplotlib/freetype versions; pin those if cross-machine cache sharing is
required.
"""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")  # must come before pyplot/mplfinance imports for headless determinism

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from core.types import Bar


def render_chart(
    bars: list[Bar],
    *,
    width_px: int = 800,
    height_px: int = 480,
    dpi: int = 100,
) -> str:
    """Render ``bars`` as a candlestick + volume chart and return base64 PNG bytes.

    ``Bar.timestamp`` is a tz-aware ``datetime``; it is passed through to the
    DatetimeIndex unchanged.

    Raises:
        ValueError: if ``bars`` is empty.
    """
    if not bars:
        raise ValueError("render_chart requires at least one bar")

    df = pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
            "Volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex([b.timestamp for b in bars], name="Date"),
    )

    buf = io.BytesIO()
    try:
        mpf.plot(
            df,
            type="candle",
            volume=True,
            style="charles",
            figsize=(width_px / dpi, height_px / dpi),
            savefig={"fname": buf, "dpi": dpi, "format": "png", "bbox_inches": "tight"},
        )
    finally:
        # mplfinance < 0.12.11 occasionally leaves the Figure open when using
        # the savefig kwarg. Close all to prevent a per-bar memory creep when
        # render_chart is invoked thousands of times in a backtest.
        plt.close("all")
    return base64.b64encode(buf.getvalue()).decode("ascii")
