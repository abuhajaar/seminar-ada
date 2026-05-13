"""Performance metrics over an equity curve and a trade list."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from core.metrics import compute_metrics
from core.types import Action, Trade


def _curve(*equities: float) -> list[tuple[datetime, float]]:
    base = datetime(2025, 4, 1, tzinfo=UTC)
    return [(base + timedelta(hours=i), e) for i, e in enumerate(equities)]


def _trade(pnl: float) -> Trade:
    base = datetime(2025, 4, 1, tzinfo=UTC)
    # Trade.pnl is computed from prices/qty/fees; encode the desired pnl
    # as an exit_price delta on a 1-unit long with zero fees.
    return Trade(
        entry_ts=base,
        exit_ts=base + timedelta(hours=1),
        entry_price=100.0,
        exit_price=100.0 + pnl,
        qty=1.0,
        side=Action.BUY,
        fees=0.0,
        symbol="X",
    )


def test_total_return_simple():
    m = compute_metrics(equity_curve=_curve(10_000.0, 11_000.0), trades=[])
    assert m["total_return_pct"] == pytest.approx(10.0)


def test_total_return_loss():
    m = compute_metrics(equity_curve=_curve(10_000.0, 9_000.0), trades=[])
    assert m["total_return_pct"] == pytest.approx(-10.0)


def test_max_drawdown_basic():
    m = compute_metrics(equity_curve=_curve(100, 110, 90, 105, 80), trades=[])
    assert m["max_drawdown_pct"] == pytest.approx(-100 * (110 - 80) / 110)


def test_max_drawdown_no_drawdown_returns_zero():
    m = compute_metrics(equity_curve=_curve(100, 110, 120, 130), trades=[])
    assert m["max_drawdown_pct"] == 0.0


def test_win_rate_and_counts():
    trades = [_trade(10.0), _trade(-5.0), _trade(15.0), _trade(-3.0), _trade(0.0)]
    m = compute_metrics(equity_curve=_curve(100, 100), trades=trades)
    assert m["num_trades"] == 5
    assert m["wins"] == 2
    assert m["losses"] == 2
    assert m["win_rate_pct"] == pytest.approx(2 / 4 * 100)


def test_win_rate_zero_trades():
    m = compute_metrics(equity_curve=_curve(100, 100), trades=[])
    assert m["num_trades"] == 0
    assert m["win_rate_pct"] == 0.0


def test_profit_factor_basic():
    trades = [_trade(10.0), _trade(-5.0), _trade(15.0), _trade(-3.0)]
    m = compute_metrics(equity_curve=_curve(100, 100), trades=trades)
    assert m["profit_factor"] == pytest.approx(25.0 / 8.0)


def test_profit_factor_no_losses_returns_infinity():
    trades = [_trade(10.0), _trade(5.0)]
    m = compute_metrics(equity_curve=_curve(100, 100), trades=trades)
    assert math.isinf(m["profit_factor"])
    assert m["profit_factor"] > 0


def test_profit_factor_no_trades_returns_nan():
    m = compute_metrics(equity_curve=_curve(100, 100), trades=[])
    assert math.isnan(m["profit_factor"])


def test_sharpe_constant_returns_zero():
    m = compute_metrics(equity_curve=_curve(100, 100, 100, 100), trades=[])
    assert m["sharpe"] == 0.0


def test_sharpe_positive_drift():
    m = compute_metrics(equity_curve=_curve(100, 101, 102.01, 103.03), trades=[])
    assert m["sharpe"] > 0


def test_metrics_keys_stable():
    m = compute_metrics(equity_curve=_curve(100, 110), trades=[])
    assert set(m.keys()) == {
        "total_return_pct", "max_drawdown_pct",
        "num_trades", "wins", "losses", "win_rate_pct",
        "profit_factor", "sharpe",
    }
