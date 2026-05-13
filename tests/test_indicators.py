"""Indicator math validated against `pandas-ta` reference (dev dep)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as pta
import pytest

from indicators.ta import ema


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
