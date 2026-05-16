"""Stream Bar objects by joining OHLCV + CVD parquets on timestamp."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from core.types import Bar
from data.paths import DEFAULT_ROOT, cvd_parquet_path, ohlcv_csv_path


def _to_utc_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def load_bars(
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    root: Path = DEFAULT_ROOT,
) -> Iterator[Bar]:
    """Yield `Bar` for `[start, end)` (UTC, end-exclusive at start-of-day).

    Both files must exist and have matching timestamps within the window.
    Misalignment raises `ValueError` to surface bugs in the data pipeline.
    """
    ohlcv_path = ohlcv_csv_path(symbol, timeframe, root=root)
    cvd_path = cvd_parquet_path(symbol, timeframe, root=root)
    if not ohlcv_path.exists():
        raise FileNotFoundError(f"OHLCV not found at {ohlcv_path}")
    if not cvd_path.exists():
        raise FileNotFoundError(f"CVD not found at {cvd_path}")

    ohlcv = pd.read_csv(ohlcv_path, parse_dates=["timestamp"])
    if ohlcv["timestamp"].dt.tz is None:
        ohlcv["timestamp"] = ohlcv["timestamp"].dt.tz_localize("UTC")
    cvd = pd.read_parquet(cvd_path)
    if cvd["timestamp"].dt.tz is None:
        cvd["timestamp"] = cvd["timestamp"].dt.tz_localize("UTC")

    start_ts = pd.Timestamp(_to_utc_dt(start))
    end_ts = pd.Timestamp(_to_utc_dt(end))
    ohlcv = ohlcv[
        (ohlcv["timestamp"] >= start_ts) & (ohlcv["timestamp"] < end_ts)
    ].reset_index(drop=True)
    cvd = cvd[(cvd["timestamp"] >= start_ts) & (cvd["timestamp"] < end_ts)].reset_index(drop=True)

    if len(ohlcv) == 0:
        return

    if len(ohlcv) != len(cvd) or not (ohlcv["timestamp"].values == cvd["timestamp"].values).all():
        raise ValueError(
            f"OHLCV/CVD alignment failure for {symbol} {timeframe} "
            f"in [{start}, {end}): rows {len(ohlcv)} vs {len(cvd)}"
        )

    merged = ohlcv.merge(
        cvd.drop(columns=["taker_buy_volume"], errors="ignore"),
        on="timestamp",
        how="inner",
    )
    for row in merged.itertuples(index=False):
        yield Bar(
            timestamp=row.timestamp.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
            taker_buy_volume=float(row.taker_buy_volume),
            cvd=float(row.cvd),
            cvd_delta=float(row.cvd_delta),
        )
