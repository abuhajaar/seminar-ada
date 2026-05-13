"""Live network smoke test. Skipped unless RUN_LIVE_TESTS=1.

Downloads ~6 hours of BTC/USDT 1h OHLCV + aggTrades, aggregates CVD,
and iterates the resulting bars. ~few MB of network, ~30 s runtime.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import ccxt
import pandas as pd
import pytest

from data.cvd import aggregate_cvd
from data.downloader import download_aggtrades, download_ohlcv
from data.loader import load_bars
from data.paths import aggtrades_parquet_path, cvd_parquet_path

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="set RUN_LIVE_TESTS=1 to enable",
)


def test_pipeline_end_to_end(tmp_path: Path):
    symbol, tf = "BTC/USDT", "1h"
    start, end = date(2025, 1, 1), date(2025, 1, 2)
    ex = ccxt.binance()

    download_ohlcv(symbol, tf, start, end, exchange=ex, root=tmp_path)
    download_aggtrades(symbol, start, end, root=tmp_path)

    trades = pd.read_parquet(aggtrades_parquet_path(symbol, root=tmp_path))
    cvd_df = aggregate_cvd(trades, timeframe=tf)
    cvd_path = cvd_parquet_path(symbol, tf, root=tmp_path)
    cvd_path.parent.mkdir(parents=True, exist_ok=True)
    cvd_df.to_parquet(cvd_path, index=False)

    bars = list(load_bars(symbol, tf, start, end, root=tmp_path))
    assert len(bars) == 24
    assert bars[0].close > 0
    assert bars[-1].cvd != 0  # at least some flow
