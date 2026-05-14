"""Multi-asset walk-forward runner: per-asset isolation, progress, persistence.

Test strategy uses two `TraditionalStrategy()` instances for both legs to keep
the harness deterministic (no LLM client needed). This is sufficient to prove
that each asset gets its own fresh strategy + portfolio state and that
results aggregate correctly across symbols.
"""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import walkforward
from core.run_state import RunState
from core.types import Bar
from llm.budget import BudgetExceededError
from strategies.base import Context
from strategies.traditional import TraditionalStrategy


def _make_bars(
    n: int = 400, start_price: float = 100.0, seed: int = 42, drift: float = 0.2,
) -> list[Bar]:
    """Deterministic synthetic bars (matches tests/test_engine.py shape)."""
    rng = random.Random(seed)
    base = datetime(2025, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = start_price
    swing_amp = 10.0
    swing_period = 30.0
    for i in range(n):
        swing = swing_amp * math.sin(i / swing_period)
        d = drift * i
        noise = rng.uniform(-0.4, 0.4)
        target = start_price + swing + d + noise
        open_ = price
        close = max(1.0, target)
        high = max(open_, close) + abs(rng.uniform(0.0, 0.5))
        low = min(open_, close) - abs(rng.uniform(0.0, 0.5))
        bars.append(Bar(
            timestamp=base + timedelta(hours=i),
            open=open_, high=high, low=low, close=close,
            volume=1000.0, taker_buy_volume=500.0,
            cvd=0.0, cvd_delta=0.0,
        ))
        price = close
    return bars


def _make_cfg(out_dir: Path | None = None) -> SimpleNamespace:
    """Build a minimal cfg with the attributes walkforward.run reads."""
    return SimpleNamespace(
        run=SimpleNamespace(
            assets=["A/USDT", "B/USDT"],
            timeframe="1h",
            out_dir=out_dir,
            initial_balance=10_000.0,
        ),
        execution=SimpleNamespace(
            taker_fee_bps=4.0,
            slippage_bps=2.0,
            risk_pct=0.02,
        ),
    )


def _bars_loader_factory():
    a_bars = _make_bars(seed=1, drift=0.2)
    b_bars = _make_bars(seed=2, drift=-0.1, start_price=200.0)

    def loader(symbol: str):
        if symbol == "A/USDT":
            return a_bars
        if symbol == "B/USDT":
            return b_bars
        raise KeyError(symbol)

    return loader


def _build_strategies(_symbol: str):
    # Two fresh TraditionalStrategy instances — deterministic, no LLM.
    return TraditionalStrategy(), TraditionalStrategy()


async def test_walkforward_isolates_assets():
    cfg = _make_cfg(out_dir=None)
    loader = _bars_loader_factory()

    results = await walkforward.run(
        cfg.run.assets, loader, _build_strategies, cfg,
    )

    assert set(results) == {"A/USDT", "B/USDT"}
    for sym in results:
        assert set(results[sym]) == {"trad", "llm"}
        assert "total_return_pct" in results[sym]["trad"]
        assert "total_return_pct" in results[sym]["llm"]

    # Different bars per asset ⇒ different outcomes (proves isolation).
    a_ret = results["A/USDT"]["trad"]["total_return_pct"]
    b_ret = results["B/USDT"]["trad"]["total_return_pct"]
    assert a_ret != b_ret


async def test_walkforward_on_progress_called():
    cfg = _make_cfg(out_dir=None)
    loader = _bars_loader_factory()
    calls: list[tuple[str, int, int]] = []

    def on_progress(symbol: str, idx: int, total: int) -> None:
        calls.append((symbol, idx, total))

    await walkforward.run(
        cfg.run.assets, loader, _build_strategies, cfg, on_progress=on_progress,
    )

    assert calls == [("A/USDT", 1, 2), ("B/USDT", 2, 2)]


async def test_walkforward_uses_run_state_factory():
    cfg = _make_cfg(out_dir=None)
    loader = _bars_loader_factory()
    captured: list[RunState] = []

    def factory(symbol: str) -> RunState:
        rs = RunState(symbol=symbol, timeframe="1h", total_bars=0)
        captured.append(rs)
        return rs

    await walkforward.run(
        cfg.run.assets, loader, _build_strategies, cfg,
        run_state_factory=factory,
    )

    assert len(captured) == 2
    # walkforward.run must set total_bars from materialized bar list.
    for rs in captured:
        assert rs.total_bars == 400
        assert rs.timeframe == "1h"
        assert rs.current_bar == 400  # engine drove every bar


async def test_walkforward_persists_when_out_dir_set(tmp_path: Path):
    cfg = _make_cfg(out_dir=tmp_path)
    loader = _bars_loader_factory()

    results = await walkforward.run(
        cfg.run.assets, loader, _build_strategies, cfg,
    )

    # `make_run_dir(out_dir)` creates `<out_dir>/runs/<ts>/`. Find it.
    runs_root = tmp_path / "runs"
    assert runs_root.exists()
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    # Each asset gets its own subdir with trades+equity CSVs.
    for sym in cfg.run.assets:
        safe = sym.replace("/", "_")
        asset_dir = run_dir / safe
        assert asset_dir.is_dir()
        assert (asset_dir / "trad_trades.csv").exists()
        assert (asset_dir / "llm_trades.csv").exists()
        assert (asset_dir / "trad_equity.csv").exists()
        assert (asset_dir / "llm_equity.csv").exists()

    # One summary.json at the run-dir level, aggregating both assets.
    summary_path = run_dir / "summary.json"
    assert summary_path.exists()
    blob = json.loads(summary_path.read_text())
    assert set(blob["per_asset"]) == set(cfg.run.assets)
    assert "aggregate" in blob

    # Sanity: returned dict matches what was persisted (trad keys at least).
    for sym in cfg.run.assets:
        assert (
            blob["per_asset"][sym]["trad"]["total_return_pct"]
            == pytest.approx(results[sym]["trad"]["total_return_pct"])
        )


class _BudgetBlowingStrategy:
    """Fake LLM strategy whose on_bar raises BudgetExceededError on first call.

    Satisfies the strategies.base.Strategy Protocol (single async on_bar).
    """

    def __init__(self) -> None:
        self.calls = 0

    async def on_bar(self, bar: Bar, ctx: Context):  # noqa: ARG002
        self.calls += 1
        raise BudgetExceededError("limit hit")


async def test_walkforward_handles_budget_exceeded():
    cfg = _make_cfg(out_dir=None)
    loader = _bars_loader_factory()

    def build(_symbol: str):
        # Real trad leg, fake LLM leg that immediately blows the budget.
        return TraditionalStrategy(), _BudgetBlowingStrategy()

    progress_calls: list[tuple[str, int, int]] = []

    def on_progress(symbol: str, idx: int, total: int) -> None:
        progress_calls.append((symbol, idx, total))

    results = await walkforward.run(
        cfg.run.assets, loader, build, cfg, on_progress=on_progress,
    )

    assert set(results) == {"A/USDT", "B/USDT"}
    for sym in ("A/USDT", "B/USDT"):
        llm = results[sym]["llm"]
        assert llm["status"] == "budget_exceeded"
        assert isinstance(llm["error"], str) and llm["error"]
        # BudgetExceededError has no spend_usd attr today; impl falls back to 0.0.
        assert llm["spend_usd"] == 0.0
        # engine.run_async raised before returning portfolios, so trad is lost.
        assert results[sym]["trad"] == {"status": "not_run"}

    # on_progress fires for every asset even when its run blew the budget.
    assert progress_calls == [("A/USDT", 1, 2), ("B/USDT", 2, 2)]


async def test_walkforward_empty_assets_creates_no_run_dir(tmp_path: Path):
    cfg = _make_cfg(out_dir=tmp_path)
    loader = _bars_loader_factory()

    results = await walkforward.run([], loader, _build_strategies, cfg)

    assert results == {}
    # No `runs/` directory should be materialised for an empty asset list.
    assert not (tmp_path / "runs").exists()
