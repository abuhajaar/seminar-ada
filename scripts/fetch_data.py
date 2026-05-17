"""One-off orchestrator: download OHLCV (with taker_buy_volume) + CVD.

CVD is derived analytically from kline `taker_buy_volume`, so this script no
longer downloads aggTrades. Expect ~30 seconds for 3 symbols x 21 days at 1h.

Usage:
    python scripts/fetch_data.py [--config config.yaml]

Idempotent: skips any file already covering [start, end).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make project root importable when run as `python scripts/fetch_data.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse  # noqa: E402

import ccxt  # noqa: E402
import pandas as pd  # noqa: E402

from core.config import load_config  # noqa: E402
from data.cvd import cvd_from_klines  # noqa: E402
from data.downloader import download_ohlcv  # noqa: E402
from data.paths import DEFAULT_ROOT, cvd_csv_path, ohlcv_csv_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    cfg = load_config(args.config)
    symbols: list[str] = cfg.run.assets
    timeframe: str = cfg.run.timeframe
    start = cfg.run.start
    end = cfg.run.end
    root: Path = args.data_root

    print(f"Window: {start} -> {end} ({timeframe})")
    print(f"Symbols: {symbols}")
    print(f"Data root: {root}")

    exchange = ccxt.binance({"enableRateLimit": True})

    for sym in symbols:
        print(f"\n=== {sym} ===")
        print("  OHLCV (with taker_buy_volume) ...")
        ohlcv_path = download_ohlcv(sym, timeframe, start, end, exchange, root=root)
        print(f"    -> {ohlcv_path}")

        print("  CVD (derived from klines) ...")
        cvd_out = cvd_csv_path(sym, timeframe, root=root)
        cvd_out.parent.mkdir(parents=True, exist_ok=True)
        ohlcv_df = pd.read_csv(ohlcv_csv_path(sym, timeframe, root=root), parse_dates=["timestamp"])
        if ohlcv_df["timestamp"].dt.tz is None:
            ohlcv_df["timestamp"] = ohlcv_df["timestamp"].dt.tz_localize("UTC")
        cvd_df = cvd_from_klines(ohlcv_df)
        cvd_df.to_csv(cvd_out, index=False)
        print(f"    -> {cvd_out}  ({len(cvd_df)} bars)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
