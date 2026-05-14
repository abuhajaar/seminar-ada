"""Artifact writers for one backtest run: trades CSV, equity CSV, summary JSON.

These functions are pure I/O: they consume already-computed objects
(`Portfolio`, `MetricsDict`) and emit human- and pandas-friendly files.

File layout for a single run (created by `make_run_dir`):

    <out_root>/runs/<UTC timestamp>/
        trades_BTC-USDT.csv
        equity_BTC-USDT.csv
        ...
        summary.json

The engine + walk-forward driver are responsible for choosing filenames
under the directory; this module just writes whatever path it's given.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from core.metrics import MetricsDict, drawdown_series
from core.portfolio import Portfolio
from core.types import Trade

_TRADE_HEADER = [
    "entry_ts", "exit_ts", "side", "entry_price", "exit_price",
    "qty", "pnl_usd", "pnl_pct", "bars_held",
]

_EQUITY_HEADER = ["ts", "equity", "drawdown"]

# Metrics fields aggregated across assets. `wins` and `losses` are omitted
# (redundant with `num_trades` and `win_rate_pct`).
_AGG_KEYS: tuple[str, ...] = (
    "total_return_pct",
    "max_drawdown_pct",
    "num_trades",
    "win_rate_pct",
    "profit_factor",
    "sharpe",
)


# ── trades CSV ────────────────────────────────────────────────────────────


def _trade_row(t: Trade) -> dict[str, Any]:
    notional = t.entry_price * t.qty
    pnl_pct = (t.pnl / notional) * 100.0 if notional != 0.0 else 0.0
    # bars_held assumes a 1h timeframe; emitted as whole hours between entry
    # and exit. Downstream callers with a different timeframe can rewrite
    # this column.
    bars_held = int((t.exit_ts - t.entry_ts).total_seconds() // 3600)
    return {
        "entry_ts": t.entry_ts.isoformat(),
        "exit_ts": t.exit_ts.isoformat(),
        "side": t.side.value,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "qty": t.qty,
        "pnl_usd": t.pnl,
        "pnl_pct": pnl_pct,
        "bars_held": bars_held,
    }


def write_trades(path: Path, portfolio: Portfolio) -> None:
    """Write `portfolio.closed_trades` to CSV at `path`.

    Columns: entry_ts, exit_ts, side, entry_price, exit_price, qty,
    pnl_usd, pnl_pct, bars_held. Always writes the header, even when the
    trade list is empty. `bars_held` assumes a 1h timeframe.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_TRADE_HEADER)
        writer.writeheader()
        for t in portfolio.closed_trades:
            writer.writerow(_trade_row(t))


# ── equity CSV ────────────────────────────────────────────────────────────


def write_equity(path: Path, portfolio: Portfolio) -> None:
    """Write the equity curve to CSV at `path`.

    Columns: ts (ISO 8601), equity (float), drawdown (percent, ≤ 0).
    Drawdown is computed as (equity - running_peak) / running_peak * 100;
    0.0 whenever equity is at or above the running peak.
    """
    curve = portfolio.equity_curve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_EQUITY_HEADER)
        writer.writeheader()
        if not curve:
            return
        equities = np.array([e for _, e in curve], dtype=float)
        dd = drawdown_series(equities)
        for (ts, eq), d in zip(curve, dd, strict=True):
            writer.writerow({"ts": ts.isoformat(), "equity": float(eq),
                             "drawdown": float(d)})


# ── summary JSON ──────────────────────────────────────────────────────────


def _finite_or_none(x: Any) -> Any:
    """Replace non-finite floats with None; recurse into dicts/lists."""
    if isinstance(x, dict):
        return {k: _finite_or_none(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite_or_none(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _aggregate_one(values: list[float]) -> dict[str, float | None]:
    """Mean and population std over finite values. None if none remain."""
    arr = np.array(values, dtype=float)
    # Replace +/-inf with nan so nanmean/nanstd both skip them.
    arr = np.where(np.isfinite(arr), arr, np.nan)
    if np.all(np.isnan(arr)):
        return {"mean": None, "std": None}
    with np.errstate(invalid="ignore"):
        mean = float(np.nanmean(arr))
        std = float(np.nanstd(arr, ddof=0))
    return {
        "mean": mean if math.isfinite(mean) else None,
        "std": std if math.isfinite(std) else None,
    }


def _aggregate_strategy(
    metrics_by_asset: dict[str, dict[str, MetricsDict]],
    strategy: str,
) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for key in _AGG_KEYS:
        values = [
            float(metrics_by_asset[asset][strategy][key])  # type: ignore[literal-required]
            for asset in metrics_by_asset
        ]
        out[key] = _aggregate_one(values)
    return out


def write_summary(
    path: Path,
    metrics_by_asset: dict[str, dict[str, MetricsDict]],
) -> None:
    """Write per-asset metrics plus aggregate (mean/std) across assets to JSON.

    Schema::

        {
          "per_asset": {<symbol>: {"trad": MetricsDict, "llm": MetricsDict}},
          "aggregate": {
            "trad": {<key>: {"mean": float|None, "std": float|None}},
            "llm":  {<key>: {"mean": float|None, "std": float|None}}
          }
        }

    Non-finite floats (`nan`, `inf`, `-inf`) are serialized as JSON `null`
    so the output is strictly valid JSON. Aggregates drop non-finite
    values before computing mean/std (population, ddof=0).
    """
    blob: dict[str, Any] = {
        "per_asset": {
            asset: {
                strategy: dict(metrics)  # copy MetricsDict → plain dict
                for strategy, metrics in by_strategy.items()
            }
            for asset, by_strategy in metrics_by_asset.items()
        },
        "aggregate": {
            "trad": _aggregate_strategy(metrics_by_asset, "trad"),
            "llm": _aggregate_strategy(metrics_by_asset, "llm"),
        },
    }
    cleaned = _finite_or_none(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cleaned, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


# ── run directory ─────────────────────────────────────────────────────────


def make_run_dir(out_root: Path) -> Path:
    """Create and return `<out_root>/runs/<UTC timestamp>/`.

    Timestamp format: ``YYYYMMDDThhmmssZ`` (UTC). Safe to call multiple
    times in the same second — the directory is created with
    ``exist_ok=True``.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_root / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
