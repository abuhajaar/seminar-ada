"""Centralized layout for the data cache directory.

All on-disk locations live here so other modules don't hard-code paths.
Default root is `data/cache/` relative to the repo. Tests pass a tmp root.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ROOT = Path("data") / "cache"


def _norm(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def ohlcv_csv_path(symbol: str, timeframe: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / "ohlcv" / f"{_norm(symbol)}_{timeframe}.csv"


def aggtrades_parquet_path(symbol: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / "aggtrades" / f"{_norm(symbol)}.parquet"


def cvd_csv_path(symbol: str, timeframe: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / "cvd" / f"{_norm(symbol)}_{timeframe}.csv"
