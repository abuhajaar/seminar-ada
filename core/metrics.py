"""Compute headline performance metrics for a single backtest run.

Inputs:
    equity_curve: list of (timestamp, equity) samples, recorded by Portfolio.mark()
    trades:       list of closed Trades

Outputs (dict):
    total_return_pct  - (equity_end / equity_start - 1) * 100
    max_drawdown_pct  - most-negative peak-to-trough percent drop on the curve
    num_trades        - len(trades)
    wins, losses      - counts of pnl > 0 and pnl < 0 (zero-pnl excluded)
    win_rate_pct      - wins / (wins + losses) * 100; 0.0 if denominator is 0
    profit_factor     - sum(positive pnl) / abs(sum(negative pnl))
                        +inf if no losses but >=1 win; NaN if no trades
    sharpe            - bar-frequency Sharpe (mean/std * sqrt(N)). 0.0 for
                        constant curves. No annualization (relative metric).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TypedDict

import numpy as np

from core.types import Trade


class MetricsDict(TypedDict):
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    profit_factor: float
    sharpe: float


def drawdown_series(equity: np.ndarray) -> np.ndarray:
    """Drawdown series in percent (≤ 0): (equity - running_peak) / running_peak * 100.

    Positive values (numerical noise at the running peak) are clamped to 0.
    Zero or negative running peaks yield 0 to avoid divide-by-zero.
    """
    equity = np.asarray(equity, dtype=float)
    running_peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(
            running_peak > 0,
            (equity - running_peak) / running_peak,
            0.0,
        )
    dd = np.where(dd > 0, 0.0, dd)
    return dd * 100.0


def compute_metrics(
    equity_curve: list[tuple[datetime, float]],
    trades: list[Trade],
) -> MetricsDict:
    if len(equity_curve) < 2:
        raise ValueError("equity_curve needs at least 2 samples")

    equity = np.array([e for _, e in equity_curve], dtype=float)

    total_return_pct = float((equity[-1] / equity[0] - 1.0) * 100.0)

    dd_series = drawdown_series(equity)
    max_drawdown_pct = min(float(dd_series.min()), 0.0)

    pnls = np.array([t.pnl for t in trades], dtype=float)
    num_trades = len(trades)
    wins = int(np.sum(pnls > 0))
    losses = int(np.sum(pnls < 0))
    decided = wins + losses
    win_rate_pct = (wins / decided * 100.0) if decided > 0 else 0.0

    if num_trades == 0:
        profit_factor = float("nan")
    else:
        gross_profit = float(pnls[pnls > 0].sum())
        gross_loss = float(-pnls[pnls < 0].sum())
        if gross_loss == 0.0:
            profit_factor = float("inf") if gross_profit > 0 else float("nan")
        else:
            profit_factor = gross_profit / gross_loss

    rets = np.diff(equity) / equity[:-1]
    if rets.std(ddof=0) == 0.0:
        sharpe = 0.0
    else:
        sharpe = float(rets.mean() / rets.std(ddof=0) * math.sqrt(len(rets)))

    return MetricsDict(
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        num_trades=num_trades,
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        sharpe=sharpe,
    )
