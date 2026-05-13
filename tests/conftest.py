"""Shared pytest fixtures.

`synth_ohlcv` returns a deterministic 500-bar 1h OHLCV DataFrame with mild
trend and noise — enough for indicator math to be meaningful.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="session")
def synth_ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    n = 500
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    drift = np.linspace(0, 20, n)
    noise = rng.normal(0, 1.0, n).cumsum()
    close = 100 + drift + noise
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.uniform(100, 1000, n)
    taker_buy = volume * rng.uniform(0.4, 0.6, n)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "taker_buy_volume": taker_buy,
        },
        index=idx,
    )
