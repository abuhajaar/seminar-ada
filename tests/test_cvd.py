"""CVD aggregation: convert per-trade aggTrades into per-bar CVD."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from data.cvd import aggregate_cvd


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _trades(rows: list[tuple[int, float, float, bool]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["agg_id", "price", "qty", "is_buyer_maker_and_ts"]
    )


def test_cvd_basic_aggregation():
    # Bar 1 (00:00–01:00): 3 buys (5,3,2 qty), 2 sells (4,1) → delta = 10 - 5 = +5
    # Bar 2 (01:00–02:00): 1 buy (8), 3 sells (2,2,2)        → delta = 8 - 6  = +2
    # Cumulative: bar1=5, bar2=7
    df = pd.DataFrame(
        {
            "agg_id": list(range(9)),
            "price": [100.0] * 9,
            "qty": [5, 3, 2, 4, 1, 8, 2, 2, 2],
            "ts": [
                _ms(datetime(2025, 4, 1, 0, 5)),
                _ms(datetime(2025, 4, 1, 0, 15)),
                _ms(datetime(2025, 4, 1, 0, 25)),
                _ms(datetime(2025, 4, 1, 0, 35)),
                _ms(datetime(2025, 4, 1, 0, 45)),
                _ms(datetime(2025, 4, 1, 1, 5)),
                _ms(datetime(2025, 4, 1, 1, 25)),
                _ms(datetime(2025, 4, 1, 1, 45)),
                _ms(datetime(2025, 4, 1, 1, 55)),
            ],
            # is_buyer_maker = True means the BUYER was the passive maker → trade was a SELL
            "is_buyer_maker": [False, False, False, True, True, False, True, True, True],
        }
    )
    out = aggregate_cvd(df, timeframe="1h")
    assert list(out.columns) == ["timestamp", "cvd_delta", "cvd", "taker_buy_volume"]
    assert len(out) == 2
    np.testing.assert_array_equal(out["cvd_delta"].values, [5.0, 2.0])
    np.testing.assert_array_equal(out["cvd"].values, [5.0, 7.0])
    np.testing.assert_array_equal(out["taker_buy_volume"].values, [10.0, 8.0])
    assert out["timestamp"].iloc[0] == pd.Timestamp("2025-04-01 00:00", tz="UTC")
    assert out["timestamp"].iloc[1] == pd.Timestamp("2025-04-01 01:00", tz="UTC")


def test_cvd_empty_input():
    df = pd.DataFrame(columns=["agg_id", "price", "qty", "ts", "is_buyer_maker"])
    out = aggregate_cvd(df, timeframe="1h")
    assert len(out) == 0
    assert list(out.columns) == ["timestamp", "cvd_delta", "cvd", "taker_buy_volume"]


def test_cvd_unsupported_timeframe():
    df = pd.DataFrame(columns=["agg_id", "price", "qty", "ts", "is_buyer_maker"])
    with pytest.raises(ValueError, match="timeframe"):
        aggregate_cvd(df, timeframe="banana")
