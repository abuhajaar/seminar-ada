"""Aggregate Binance aggTrades into per-bar CVD.

Convention:
    is_buyer_maker == True  → the buyer was the resting maker, so the
                              trade is a SELL (taker hit the bid).
    is_buyer_maker == False → the trade is a BUY (taker lifted the ask).

cvd_delta = sum(buy_qty) - sum(sell_qty) within the bar.
cvd       = cumulative sum of cvd_delta over the entire window.
"""

from __future__ import annotations

import pandas as pd

_TF_TO_PANDAS = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}


def aggregate_cvd(trades: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Return DataFrame with columns `timestamp` (UTC, bar-open), `cvd_delta`, `cvd`."""
    if timeframe not in _TF_TO_PANDAS:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. Supported: {sorted(_TF_TO_PANDAS)}"
        )
    if len(trades) == 0:
        return pd.DataFrame(columns=["timestamp", "cvd_delta", "cvd"])

    df = trades.copy()
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    # signed_qty: +qty for buy (is_buyer_maker=False), -qty for sell
    df["signed_qty"] = df["qty"].where(~df["is_buyer_maker"], -df["qty"])

    grouped = (
        df.set_index("timestamp")["signed_qty"]
        .resample(_TF_TO_PANDAS[timeframe], label="left", closed="left")
        .sum()
        .rename("cvd_delta")
        .to_frame()
    )
    grouped["cvd"] = grouped["cvd_delta"].cumsum()
    return grouped.reset_index()
