"""Indicator math validated against `pandas-ta` reference (dev dep)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as pta
import pytest

from indicators.ta import ema, macd, rsi


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
