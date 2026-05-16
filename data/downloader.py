"""Download OHLCV (via ccxt) and aggTrades (via Binance REST).

Both functions are idempotent and resumable:
- OHLCV: if the target CSV already exists with full coverage, skip.
- aggTrades: if a parquet exists, resume from `max(agg_id) + 1`.

Network errors are surfaced (no retry) — let the caller decide policy.
Sub-plan B/C/D may wrap with tenacity later.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from data.paths import DEFAULT_ROOT, aggtrades_parquet_path, ohlcv_csv_path

BINANCE_AGGTRADES_URL = "https://api.binance.com/api/v3/aggTrades"
AGGTRADES_PAGE_LIMIT = 1000


def _date_to_ms(d: date, *, end: bool = False) -> int:
    dt = datetime(d.year, d.month, d.day, tzinfo=UTC)
    if end:
        # End-of-day exclusive: caller passes `end` meaning "stop AT start of this date".
        pass
    return int(dt.timestamp() * 1000)


_TF_TO_BINANCE_INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d": "1d",
}
KLINES_PAGE_LIMIT = 1000


def download_ohlcv(
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    exchange: Any,
    root: Path = DEFAULT_ROOT,
) -> Path:
    """Download OHLCV (with `taker_buy_volume`) using a ccxt exchange instance.

    Uses Binance's raw `publicGetKlines` endpoint so we can keep the 10th column
    (`taker_buy_base_volume`). That column lets `data.cvd.cvd_from_klines` derive
    per-bar CVD without touching `aggTrades` — a 60-200x speedup vs the
    tick-by-tick REST path.

    Idempotent: if the target CSV already exists and covers [start, end), skip.
    """
    if timeframe not in _TF_TO_BINANCE_INTERVAL:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. "
            f"Supported: {sorted(_TF_TO_BINANCE_INTERVAL)}"
        )
    out = ohlcv_csv_path(symbol, timeframe, root=root)
    out.parent.mkdir(parents=True, exist_ok=True)

    start_ms = _date_to_ms(start)
    end_ms = _date_to_ms(end)
    tf_seconds = exchange.parse_timeframe(timeframe)
    tf_ms = tf_seconds * 1000

    if out.exists():
        existing = pd.read_csv(out, parse_dates=["timestamp"])
        if len(existing) > 0 and "taker_buy_volume" in existing.columns:
            cov_start = int(existing["timestamp"].iloc[0].timestamp() * 1000)
            cov_end = int(existing["timestamp"].iloc[-1].timestamp() * 1000) + tf_ms
            if cov_start <= start_ms and cov_end >= end_ms:
                return out  # already fully covered with the new schema

    market_symbol = symbol.replace("/", "")
    rows: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        batch = exchange.publicGetKlines(
            {
                "symbol": market_symbol,
                "interval": _TF_TO_BINANCE_INTERVAL[timeframe],
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": KLINES_PAGE_LIMIT,
            }
        )
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + tf_ms
        if len(batch) < KLINES_PAGE_LIMIT:
            break

    # Raw kline cols: [open_time, o, h, l, c, volume, close_time, quote_vol,
    #                  n_trades, taker_buy_base_vol, taker_buy_quote_vol, ignore]
    df = pd.DataFrame(
        rows,
        columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "_close_time", "_quote_vol", "_n_trades",
            "taker_buy_volume", "_taker_buy_quote_vol", "_ignore",
        ],
    )
    df = df[df["timestamp"] < end_ms]
    # Binance returns numerics as strings; coerce.
    for col in ("open", "high", "low", "close", "volume", "taker_buy_volume"):
        df[col] = pd.to_numeric(df[col])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume", "taker_buy_volume"]]
    df.to_csv(out, index=False)
    return out


def download_aggtrades(
    symbol: str,
    start: date,
    end: date,
    root: Path = DEFAULT_ROOT,
    client: httpx.Client | None = None,
    sleep_s: float = 0.05,
) -> Path:
    """Download Binance aggTrades into a parquet, resuming if file exists.

    Storage schema: `agg_id (int64), price (float64), qty (float64),
    ts (int64 ms), is_buyer_maker (bool)`.
    """
    out = aggtrades_parquet_path(symbol, root=root)
    out.parent.mkdir(parents=True, exist_ok=True)
    market_symbol = symbol.replace("/", "")
    start_ms = _date_to_ms(start)
    end_ms = _date_to_ms(end)

    existing: pd.DataFrame | None = None
    next_id: int | None = None
    if out.exists():
        existing = pd.read_parquet(out)
        if len(existing) > 0:
            next_id = int(existing["agg_id"].max()) + 1

    own_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        new_rows: list[dict] = []
        while True:
            params: dict[str, Any] = {
                "symbol": market_symbol,
                "limit": AGGTRADES_PAGE_LIMIT,
            }
            if next_id is not None:
                params["fromId"] = next_id
            else:
                params["startTime"] = start_ms
                # 1h window seed
                params["endTime"] = min(start_ms + 60 * 60 * 1000, end_ms)

            resp = client.get(BINANCE_AGGTRADES_URL, params=params)
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            done = False
            kept: list[dict] = []
            for t in page:
                if t["T"] >= end_ms:
                    done = True
                    break
                kept.append(t)
            new_rows.extend(_row(x) for x in kept)
            if done:
                break
            # Advance to next page using last id seen.
            next_id = page[-1]["a"] + 1
            time.sleep(sleep_s)
    finally:
        if own_client:
            client.close()

    new_df = pd.DataFrame(new_rows)
    if existing is not None and len(new_df) > 0:
        merged = pd.concat([existing, new_df], ignore_index=True)
    elif existing is not None:
        merged = existing
    else:
        merged = new_df
    if len(merged) > 0:
        merged = (
            merged.drop_duplicates(subset=["agg_id"])
            .sort_values("agg_id")
            .reset_index(drop=True)
        )
    merged.to_parquet(out, index=False)
    return out


def _row(t: dict) -> dict:
    return {
        "agg_id": int(t["a"]),
        "price": float(t["p"]),
        "qty": float(t["q"]),
        "ts": int(t["T"]),
        "is_buyer_maker": bool(t["m"]),
    }
