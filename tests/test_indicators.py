"""Indicator math validated against `pandas-ta` reference (dev dep)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as pta
import pytest

from indicators.ta import adx, ema, macd, rsi, supertrend


def test_ema_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    close = synth_ohlcv["close"]
    ours = ema(close, length=20).dropna()
    ref = pta.ema(close, length=20).dropna()
    # Align on the intersection of indices
    idx = ours.index.intersection(ref.index)
    np.testing.assert_allclose(ours.loc[idx].values, ref.loc[idx].values, rtol=1e-10)


def test_ema_length_must_be_positive(synth_ohlcv: pd.DataFrame):
    with pytest.raises(ValueError):
        ema(synth_ohlcv["close"], length=0)


def test_rsi_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    close = synth_ohlcv["close"]
    ours = rsi(close, length=14).dropna()
    ref = pta.rsi(close, length=14).dropna()
    idx = ours.index.intersection(ref.index)
    np.testing.assert_allclose(ours.loc[idx].values, ref.loc[idx].values, rtol=1e-3)


def test_rsi_bounds(synth_ohlcv: pd.DataFrame):
    r = rsi(synth_ohlcv["close"], length=14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_macd_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    close = synth_ohlcv["close"]
    ours = macd(close, fast=12, slow=26, signal=9).dropna()
    ref = pta.macd(close, fast=12, slow=26, signal=9).dropna()
    # pandas-ta names: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    np.testing.assert_allclose(
        ours["macd"].values, ref["MACD_12_26_9"].loc[ours.index].values, rtol=1e-10
    )
    np.testing.assert_allclose(
        ours["signal"].values, ref["MACDs_12_26_9"].loc[ours.index].values, rtol=1e-10
    )
    np.testing.assert_allclose(
        ours["hist"].values, ref["MACDh_12_26_9"].loc[ours.index].values, rtol=1e-10
    )


def test_adx_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    df = synth_ohlcv
    ours = adx(df["high"], df["low"], df["close"], length=14).dropna()
    ref = pta.adx(df["high"], df["low"], df["close"], length=14).dropna()
    # pandas-ta column: ADX_14
    idx = ours.index.intersection(ref.index)
    np.testing.assert_allclose(
        ours.loc[idx].values, ref["ADX_14"].loc[idx].values, rtol=5e-3
    )


def test_supertrend_shape_and_signal(synth_ohlcv: pd.DataFrame):
    df = synth_ohlcv
    st = supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    # Returns columns 'st' (line) and 'dir' (+1 long, -1 short)
    assert set(st.columns) == {"st", "dir"}
    assert st["dir"].dropna().isin([1, -1]).all()
    # Line should sit below close during long regimes, above during short
    longs = st[st["dir"] == 1].dropna()
    shorts = st[st["dir"] == -1].dropna()
    if len(longs) > 0:
        assert (longs["st"] <= df.loc[longs.index, "close"]).all()
    if len(shorts) > 0:
        assert (shorts["st"] >= df.loc[shorts.index, "close"]).all()


def test_supertrend_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    df = synth_ohlcv
    ours = supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    ref = pta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    # pandas-ta columns: SUPERT_10_3.0, SUPERTd_10_3.0
    idx = ours["st"].dropna().index.intersection(ref["SUPERT_10_3.0"].dropna().index)
    # Allow small numerical drift, esp. at regime flips
    np.testing.assert_allclose(
        ours["st"].loc[idx].values, ref["SUPERT_10_3.0"].loc[idx].values, rtol=1e-2
    )
    # Direction should match exactly on the overlap
    np.testing.assert_array_equal(
        ours["dir"].loc[idx].values.astype(int),
        ref["SUPERTd_10_3.0"].loc[idx].values.astype(int),
    )
