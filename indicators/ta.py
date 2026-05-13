"""Vectorized technical indicators.

All functions are pure: pandas in, pandas out. No I/O. No state.
The `length` argument follows the convention from common TA libraries:
the EMA's smoothing factor is `2 / (length + 1)`.
"""

from __future__ import annotations

import numpy as np
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


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI. Matches pandas-ta's `rsi(..., length=length)`."""
    _check_length(length, "rsi")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing = EMA with alpha=1/length
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, signal); hist = MACD - signal.

    Returns a DataFrame with columns `macd`, `signal`, `hist`.
    """
    _check_length(fast, "macd.fast")
    _check_length(slow, "macd.slow")
    _check_length(signal, "macd.signal")
    if fast >= slow:
        raise ValueError(f"macd.fast ({fast}) must be < macd.slow ({slow})")
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line.dropna(), signal).reindex(series.index)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's ADX matching `pandas-ta.adx(...)['ADX_14']`.

    pandas-ta's recipe (no TA-Lib path):
      * ATR uses TR with the first ``length-1`` values set to NaN and the
        value at ``length-1`` seeded with ``SMA(TR[:length])``, then a
        Wilder RMA (``ewm(alpha=1/length, adjust=False).mean()``).
      * +DM / -DM are smoothed by a *plain* RMA on the raw series (no
        SMA seeding, no ``min_periods``), so values exist from index 0.
      * DX = 100 * |DMP - DMN| / (DMP + DMN), then ADX = RMA(DX) again
        without seeding. This produces ADX values starting at index
        ``length-1`` (driven by ATR's NaN burn-in).
    """
    _check_length(length, "adx")
    alpha = 1.0 / length

    # +DM / -DM with pandas-ta's drift=1 sign convention. The leading NaN
    # at index 0 (from .shift(1)) is preserved so pandas' ewm starts the
    # recursion at index 1, matching pandas-ta's `rma`.
    up = high - high.shift(1)
    dn = low.shift(1) - low
    pos = (((up > dn) & (up > 0)) * up).astype(float)
    neg = (((dn > up) & (dn > 0)) * dn).astype(float)

    # ATR: SMA-seeded Wilder RMA of TR.
    tr = _true_range(high, low, close).astype(float)
    tr_seeded = tr.copy()
    if len(tr_seeded) >= length:
        seed = float(tr_seeded.iloc[:length].mean())
        tr_seeded.iloc[: length - 1] = float("nan")
        tr_seeded.iloc[length - 1] = seed
    atr_ = tr_seeded.ewm(alpha=alpha, adjust=False).mean()

    k = 100.0 / atr_
    dmp = k * pos.ewm(alpha=alpha, adjust=False).mean()
    dmn = k * neg.ewm(alpha=alpha, adjust=False).mean()

    dx = 100.0 * (dmp - dmn).abs() / (dmp + dmn)
    adx_line = dx.ewm(alpha=alpha, adjust=False).mean()
    adx_line.name = "adx"
    return adx_line


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """SuperTrend trailing stop.

    Returns DataFrame with:
        st  : the trailing stop line
        dir : +1 when in long regime (line below price), -1 when short.
    """
    _check_length(length, "supertrend")
    if multiplier <= 0:
        raise ValueError(f"supertrend multiplier must be positive, got {multiplier}")

    n = len(close)
    # Short-series guard: pandas-ta returns all-NaN when there isn't enough
    # data to seed ATR. We mirror that contract.
    if n < length:
        return pd.DataFrame(
            {"st": np.full(n, np.nan), "dir": np.full(n, np.nan)},
            index=close.index,
        )

    hl2 = (high + low) / 2.0
    tr = _true_range(high, low, close).astype(float)
    tr_seeded = tr.copy()
    seed = float(tr_seeded.iloc[:length].mean())
    tr_seeded.iloc[: length - 1] = float("nan")
    tr_seeded.iloc[length - 1] = seed
    atr = tr_seeded.ewm(alpha=1.0 / length, adjust=False).mean()

    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper = upper_basic.copy()
    lower = lower_basic.copy()
    direction = np.full(n, np.nan)
    st = np.full(n, np.nan)

    # ATR is non-NaN starting at index `length-1` by construction above.
    start = length - 1

    direction[start] = 1
    st[start] = lower.iloc[start]

    upper_arr = upper.to_numpy(copy=True)
    lower_arr = lower.to_numpy(copy=True)
    upper_basic_arr = upper_basic.to_numpy(copy=True)
    lower_basic_arr = lower_basic.to_numpy(copy=True)
    close_arr = close.to_numpy(copy=True)

    for i in range(start + 1, n):
        # Trailing-stop "carry forward" rule from Olorunnimbe / TradingView
        if upper_basic_arr[i] < upper_arr[i - 1] or close_arr[i - 1] > upper_arr[i - 1]:
            upper_arr[i] = upper_basic_arr[i]
        else:
            upper_arr[i] = upper_arr[i - 1]
        if lower_basic_arr[i] > lower_arr[i - 1] or close_arr[i - 1] < lower_arr[i - 1]:
            lower_arr[i] = lower_basic_arr[i]
        else:
            lower_arr[i] = lower_arr[i - 1]

        prev_dir = direction[i - 1]
        if prev_dir == 1:
            direction[i] = -1 if close_arr[i] < lower_arr[i] else 1
        else:
            direction[i] = 1 if close_arr[i] > upper_arr[i] else -1
        st[i] = lower_arr[i] if direction[i] == 1 else upper_arr[i]

    # pandas-ta convention: direction is NaN at the seed row (st has a value
    # there but no direction is emitted until the next bar). We mirror that
    # so test indices keyed off `st.dropna()` get a clean direction overlap.
    direction[start] = np.nan

    return pd.DataFrame({"st": st, "dir": direction.astype(float)}, index=close.index)
