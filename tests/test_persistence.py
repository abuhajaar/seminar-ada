"""Persistence: write trades/equity CSVs and aggregated summary JSON per run."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from core.metrics import MetricsDict
from core.persistence import (
    make_run_dir,
    write_equity,
    write_summary,
    write_trades,
)
from core.portfolio import Portfolio
from core.types import Action


def _ts(hour: int) -> datetime:
    return datetime(2025, 4, 1, hour, 0, tzinfo=UTC)


def _build_two_trade_portfolio() -> Portfolio:
    p = Portfolio(initial_balance=10_000.0)
    # Trade 1: long, profit
    p.open_position(
        action=Action.BUY, price=100.0, quantity=10.0,
        fee=0.40, stop_loss=90.0, timestamp=_ts(0),
    )
    p.close_position(price=110.0, fee=0.44, timestamp=_ts(3))
    # Trade 2: short, loss
    p.open_position(
        action=Action.SELL, price=110.0, quantity=5.0,
        fee=0.22, stop_loss=120.0, timestamp=_ts(4),
    )
    p.close_position(price=115.0, fee=0.23, timestamp=_ts(6))
    return p


def _metrics(
    *,
    total_return_pct: float = 0.0,
    max_drawdown_pct: float = 0.0,
    num_trades: int = 0,
    wins: int = 0,
    losses: int = 0,
    win_rate_pct: float = 0.0,
    profit_factor: float = float("nan"),
    sharpe: float = 0.0,
) -> MetricsDict:
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


# ── write_trades ──────────────────────────────────────────────────────────


def test_write_trades_round_trip(tmp_path: Path) -> None:
    p = _build_two_trade_portfolio()
    out = tmp_path / "trades.csv"
    write_trades(out, p)

    df = pd.read_csv(out)
    assert list(df.columns) == [
        "entry_ts", "exit_ts", "side", "entry_price", "exit_price",
        "qty", "pnl_usd", "pnl_pct", "bars_held",
    ]
    assert len(df) == 2

    # Row 0: long 100 → 110, qty 10, fees 0.84
    row0 = df.iloc[0]
    assert row0["side"] == "BUY"
    assert row0["entry_price"] == pytest.approx(100.0, abs=1e-8)
    assert row0["exit_price"] == pytest.approx(110.0, abs=1e-8)
    assert row0["qty"] == pytest.approx(10.0, abs=1e-8)
    # pnl = (110-100)*10*1 - 0.84 = 99.16
    assert row0["pnl_usd"] == pytest.approx(99.16, abs=1e-8)
    # pnl_pct relative to notional 100*10 = 1000 → 9.916 %
    assert row0["pnl_pct"] == pytest.approx(9.916, abs=1e-8)
    # 3 hour gap
    assert int(row0["bars_held"]) == 3

    # Row 1: short 110 → 115, qty 5, fees 0.45
    row1 = df.iloc[1]
    assert row1["side"] == "SELL"
    assert row1["entry_price"] == pytest.approx(110.0, abs=1e-8)
    assert row1["exit_price"] == pytest.approx(115.0, abs=1e-8)
    # short pnl = (115-110)*5*(-1) - 0.45 = -25.45
    assert row1["pnl_usd"] == pytest.approx(-25.45, abs=1e-8)
    assert int(row1["bars_held"]) == 2


def test_write_trades_empty_portfolio(tmp_path: Path) -> None:
    p = Portfolio(initial_balance=10_000.0)
    out = tmp_path / "trades.csv"
    write_trades(out, p)
    df = pd.read_csv(out)
    assert list(df.columns) == [
        "entry_ts", "exit_ts", "side", "entry_price", "exit_price",
        "qty", "pnl_usd", "pnl_pct", "bars_held",
    ]
    assert len(df) == 0


# ── write_equity ──────────────────────────────────────────────────────────


def test_write_equity_drawdown(tmp_path: Path) -> None:
    p = Portfolio(initial_balance=100.0)
    # Manually populate the curve by marking with no position so equity = cash
    # but we want specific equities; easier: write to private curve directly.
    # The contract: write_equity reads from equity_curve(). We'll use mark()
    # with cash-only equity won't give us our target sequence, so we hack
    # cash directly to drive the desired equities.
    equities = [100.0, 110.0, 95.0, 105.0, 90.0]
    for i, eq in enumerate(equities):
        p.cash = eq  # no position, so equity() returns cash
        p.mark(_ts(i), mark_price=0.0)  # mark_price ignored when flat

    out = tmp_path / "equity.csv"
    write_equity(out, p)
    df = pd.read_csv(out)
    assert list(df.columns) == ["ts", "equity", "drawdown"]
    assert len(df) == 5

    # Drawdowns: peak runs are 100, 110, 110, 110, 110
    # (eq - peak) / peak * 100
    expected_dd = [
        0.0,
        0.0,
        (95 - 110) / 110 * 100,
        (105 - 110) / 110 * 100,
        (90 - 110) / 110 * 100,
    ]
    for got, want in zip(df["drawdown"].tolist(), expected_dd, strict=True):
        assert got == pytest.approx(want, abs=1e-4)

    # Equity round-trips
    for got, want in zip(df["equity"].tolist(), equities, strict=True):
        assert got == pytest.approx(want, abs=1e-8)


# ── write_summary ─────────────────────────────────────────────────────────


def test_write_summary_aggregates_across_assets(tmp_path: Path) -> None:
    m1 = _metrics(total_return_pct=10.0, max_drawdown_pct=-5.0, num_trades=4,
                  wins=3, losses=1, win_rate_pct=75.0, profit_factor=3.0, sharpe=1.2)
    m2 = _metrics(total_return_pct=2.0, max_drawdown_pct=-8.0, num_trades=2,
                  wins=1, losses=1, win_rate_pct=50.0, profit_factor=1.1, sharpe=0.4)
    m3 = _metrics(total_return_pct=6.0, max_drawdown_pct=-3.0, num_trades=5,
                  wins=4, losses=1, win_rate_pct=80.0, profit_factor=4.0, sharpe=1.6)
    m4 = _metrics(total_return_pct=-1.0, max_drawdown_pct=-10.0, num_trades=3,
                  wins=1, losses=2, win_rate_pct=33.0, profit_factor=0.7, sharpe=-0.2)

    out = tmp_path / "summary.json"
    write_summary(
        out,
        {
            "BTC/USDT": {"trad": m1, "llm": m2},
            "ETH/USDT": {"trad": m3, "llm": m4},
        },
    )

    blob = json.loads(out.read_text())
    assert set(blob["per_asset"].keys()) == {"BTC/USDT", "ETH/USDT"}
    assert blob["per_asset"]["BTC/USDT"]["trad"]["total_return_pct"] == pytest.approx(10.0)

    agg = blob["aggregate"]
    assert agg["trad"]["total_return_pct"]["mean"] == pytest.approx((10.0 + 6.0) / 2, abs=1e-8)
    # population std (ddof=0) of [10, 6] = 2.0
    assert agg["trad"]["total_return_pct"]["std"] == pytest.approx(2.0, abs=1e-8)
    assert agg["llm"]["total_return_pct"]["mean"] == pytest.approx((2.0 + -1.0) / 2, abs=1e-8)

    # Expected aggregate keys
    expected_keys = {
        "total_return_pct", "max_drawdown_pct", "num_trades",
        "win_rate_pct", "profit_factor", "sharpe",
    }
    assert set(agg["trad"].keys()) == expected_keys
    assert set(agg["llm"].keys()) == expected_keys


def test_write_summary_handles_non_finite(tmp_path: Path) -> None:
    m_inf = _metrics(total_return_pct=5.0, profit_factor=float("inf"))
    m_ok = _metrics(total_return_pct=3.0, profit_factor=2.0)
    m_all_nan = _metrics(total_return_pct=1.0, profit_factor=float("nan"))

    out = tmp_path / "summary.json"
    write_summary(
        out,
        {
            "BTC/USDT": {"trad": m_inf, "llm": m_all_nan},
            "ETH/USDT": {"trad": m_ok, "llm": m_all_nan},
        },
    )

    raw = out.read_text()
    # No NaN/Infinity literals leaking into JSON (strict JSON spec).
    assert "NaN" not in raw
    assert "Infinity" not in raw

    blob = json.loads(raw)
    # The inf profit_factor in per_asset must become null
    assert blob["per_asset"]["BTC/USDT"]["trad"]["profit_factor"] is None
    # Aggregate over trad.profit_factor: inf is dropped, only 2.0 remains
    assert blob["aggregate"]["trad"]["profit_factor"]["mean"] == pytest.approx(2.0)
    # All nan on llm side → null
    assert blob["aggregate"]["llm"]["profit_factor"]["mean"] is None


# ── make_run_dir ──────────────────────────────────────────────────────────


def test_make_run_dir_creates_timestamped_dir(tmp_path: Path) -> None:
    d = make_run_dir(tmp_path)
    assert d.exists() and d.is_dir()
    # Path ends with runs/<UTC timestamp>
    rel = d.relative_to(tmp_path).as_posix()
    assert re.match(r"^runs/\d{8}T\d{6}Z$", rel) is not None


def test_make_run_dir_is_idempotent_for_same_second(tmp_path: Path) -> None:
    # Called twice in quick succession; second call should not raise.
    d1 = make_run_dir(tmp_path)
    d2 = make_run_dir(tmp_path)
    assert d1.exists()
    assert d2.exists()
    # Both run dirs land under the same `runs/` root regardless of whether
    # they fall in the same UTC second.
    assert d1.parent == d2.parent == tmp_path / "runs"


def test_pnl_pct_guards_zero_notional(tmp_path: Path) -> None:
    # Synthetic Portfolio: inject a zero-price trade directly.
    from core.types import Trade  # local import to keep top-level lean
    p = Portfolio(initial_balance=10_000.0)
    p.closed_trades.append(
        Trade(
            entry_ts=_ts(0), exit_ts=_ts(1),
            entry_price=0.0, exit_price=0.0, qty=1.0,
            side=Action.BUY, fees=0.0,
        )
    )
    out = tmp_path / "trades.csv"
    write_trades(out, p)
    df = pd.read_csv(out)
    assert math.isclose(df.iloc[0]["pnl_pct"], 0.0, abs_tol=1e-12)
