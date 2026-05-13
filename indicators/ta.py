"""Vectorized technical indicators.

All functions are pure: pandas in, pandas out. No I/O. No state.
The `length` argument follows the convention from common TA libraries:
the EMA's smoothing factor is `2 / (length + 1)`.
"""

from __future__ import annotations

import pandas as pd


def _check_length(length: int, name: str) -> None:
    if length <= 0:
        raise ValueError(f"{name} length must be positive, got {length}")


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average using pandas' adjust=False semantics.

    Matches the `pandas-ta` convention: the recursion is seeded with the
    SMA of the first `length` observations (not the very first value), so
    the first `length-1` outputs are NaN and the value at index `length-1`
    equals the SMA of the first `length` points.
    """
    _check_length(length, "ema")
    alpha = 2.0 / (length + 1.0)
    values = series.to_numpy(dtype=float, copy=True)
    out = pd.Series(float("nan"), index=series.index, dtype=float, name=series.name)
    if len(values) < length:
        return out
    seed = values[:length].mean()
    out_arr = out.to_numpy(copy=True)
    out_arr[length - 1] = seed
    prev = seed
    for i in range(length, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out_arr[i] = prev
    return pd.Series(out_arr, index=series.index, name=series.name)
