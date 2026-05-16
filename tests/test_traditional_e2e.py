"""End-to-end: Traditional bot through the sync engine on synthetic + real data."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine_sync import run_sync
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
    volume = rng.uniform(500, 1500, n)
    taker_buy = rng.uniform(200, 800, n)
    ohlcv = pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volume, "taker_buy_volume": taker_buy,
    })
    op = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(op, index=False)

    cvd_delta = rng.normal(0, 5, n)
    cvd = np.cumsum(cvd_delta)
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
