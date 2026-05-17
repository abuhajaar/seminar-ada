"""Loader: read OHLCV CSV + CVD CSV from disk, yield Bar objects."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from core.types import Bar
from data.loader import load_bars
from data.paths import cvd_csv_path, ohlcv_csv_path


def _seed(tmp_path: Path):
    ohlcv = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-04-01", periods=4, freq="1h", tz="UTC"),
            "open":  [100.0, 101.0, 102.0, 103.0],
            "high":  [101.5, 102.5, 103.5, 104.5],
            "low":   [99.0, 100.0, 101.0, 102.0],
            "close": [101.0, 102.0, 103.0, 104.0],
            "volume":           [10.0, 11.0, 12.0, 13.0],
            "taker_buy_volume": [ 6.0,  4.5,  7.5,  6.0],
        }
    )
    op = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(op, index=False)

    # Post-kline-CVD pipeline: `taker_buy_volume` is canonical in OHLCV; the
    # CVD CSV still emits it for backward-compat with `aggregate_cvd`
    # output, but the loader treats OHLCV as the source of truth.
    cvd = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-04-01", periods=4, freq="1h", tz="UTC"),
            "cvd_delta": [1.0, -2.0, 3.0, -1.0],
            "cvd":       [1.0, -1.0, 2.0,  1.0],
            "taker_buy_volume": [6.0, 4.5, 7.5, 6.0],
        }
    )
    cp = cvd_csv_path("BTC/USDT", "1h", root=tmp_path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cvd.to_csv(cp, index=False)


def test_load_bars_yields_bars(tmp_path: Path):
    _seed(tmp_path)
    bars = list(
        load_bars(
            symbol="BTC/USDT",
            timeframe="1h",
            start=date(2025, 4, 1),
            end=date(2025, 4, 2),
            root=tmp_path,
        )
    )
    assert len(bars) == 4
    assert all(isinstance(b, Bar) for b in bars)
    assert bars[0].timestamp == datetime(2025, 4, 1, 0, 0, tzinfo=UTC)
    assert bars[2].close == 103.0
    assert bars[2].cvd == 2.0
    assert bars[2].cvd_delta == 3.0
    assert bars[2].taker_buy_volume == 7.5


def test_load_bars_filters_window(tmp_path: Path):
    _seed(tmp_path)
    bars = list(
        load_bars(
            symbol="BTC/USDT", timeframe="1h",
            start=date(2025, 4, 1), end=date(2025, 4, 1),  # zero-width
            root=tmp_path,
        )
    )
    # `end` is exclusive at start-of-day, so an end == start gives 0 bars
    assert bars == []


def test_load_bars_misaligned_raises(tmp_path: Path):
    _seed(tmp_path)
    # Corrupt CVD: shift one timestamp
    cp = cvd_csv_path("BTC/USDT", "1h", root=tmp_path)
    cvd = pd.read_csv(cp, parse_dates=["timestamp"])
    cvd.loc[2, "timestamp"] = pd.Timestamp("2025-04-01 02:30", tz="UTC")
    cvd.to_csv(cp, index=False)
    with pytest.raises(ValueError, match="alignment"):
        list(
            load_bars(
                symbol="BTC/USDT", timeframe="1h",
                start=date(2025, 4, 1), end=date(2025, 4, 2),
                root=tmp_path,
            )
        )


def test_load_bars_works_when_ohlcv_also_has_taker_buy_volume(tmp_path: Path):
    """Post-kline-CVD pipeline: OHLCV CSV now also carries `taker_buy_volume`.

    The CVD CSV still emits it (legacy from aggregate_cvd). The loader's
    merge must not crash on the duplicate column.
    """
    ohlcv = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-04-01", periods=2, freq="1h", tz="UTC"),
            "open":  [100.0, 101.0],
            "high":  [101.0, 102.0],
            "low":   [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume":           [10.0, 20.0],
            "taker_buy_volume": [ 6.0,  8.0],
        }
    )
    op = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(op, index=False)

    cvd = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-04-01", periods=2, freq="1h", tz="UTC"),
            "cvd_delta":        [ 2.0, -4.0],
            "cvd":               [ 2.0, -2.0],
            "taker_buy_volume":  [ 6.0,  8.0],
        }
    )
    cp = cvd_csv_path("BTC/USDT", "1h", root=tmp_path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cvd.to_csv(cp, index=False)

    bars = list(
        load_bars(
            symbol="BTC/USDT", timeframe="1h",
            start=date(2025, 4, 1), end=date(2025, 4, 2),
            root=tmp_path,
        )
    )
    assert len(bars) == 2
    assert bars[0].taker_buy_volume == 6.0
    assert bars[1].taker_buy_volume == 8.0
    assert bars[1].cvd_delta == -4.0
