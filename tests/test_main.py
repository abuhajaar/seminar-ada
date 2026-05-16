"""Smoke test for the Typer CLI in main.py.

Drives `main.app` via Typer's CliRunner with `--mock --no-tui`, monkeypatching
`load_bars` so the run does not depend on real data being downloaded. Verifies
exit code 0 and that `summary.json` is produced with the expected shape.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

import main
from core.run_state import RunState
from core.types import Bar
from llm.budget import BudgetGuard
from llm.client import LLMResponse

FIXTURE = Path(__file__).parent / "fixtures" / "bars_btc_5bars.csv"


def _load_fixture_bars() -> list[Bar]:
    bars: list[Bar] = []
    with FIXTURE.open() as fh:
        for row in csv.DictReader(fh):
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            bars.append(
                Bar(
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    taker_buy_volume=float(row["taker_buy_volume"]),
                    cvd=0.0,
                    cvd_delta=0.0,
                )
            )
    return bars


def test_cli_mock_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_bars = _load_fixture_bars()

    def fake_load_bars(symbol, timeframe, start, end, root=None):
        # Match the generator contract of data.loader.load_bars.
        yield from fixture_bars

    # main.py imports load_bars from data.loader at module import time; patch
    # the name as resolved inside main so the closure picks up the fake.
    monkeypatch.setattr(main, "load_bars", fake_load_bars)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used-in-mock")

    out_dir = tmp_path / "results"

    runner = CliRunner()
    result = runner.invoke(
        main.app,
        [
            "--mock",
            "--no-tui",
            "--assets", "BTC/USDT",
            "--start", "2025-04-01",
            "--end", "2025-04-02",
            "--out-dir", str(out_dir),
            "--config", "config.yaml",
        ],
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
    assert "BTC/USDT" in result.output

    summary_candidates = list(out_dir.glob("runs/*/summary.json"))
    assert summary_candidates, (
        f"summary.json not found under {out_dir}. Output:\n{result.output}"
    )
    summary = json.loads(summary_candidates[0].read_text())

    assert "per_asset" in summary
    assert "aggregate" in summary
    assert "BTC/USDT" in summary["per_asset"]
    assert "trad" in summary["per_asset"]["BTC/USDT"]
    assert "llm" in summary["per_asset"]["BTC/USDT"]


class _FakeOpenRouter:
    """Stand-in for OpenRouterClient that returns deterministic responses."""

    async def complete(self, **kwargs):
        return LLMResponse(
            content="HOLD 0.50 fake",
            model=kwargs["model"],
            input_tokens=50,
            output_tokens=80,
        )


def test_main_non_mock_wires_budget_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patch OpenRouterClient at the main import site so the non-mock branch
    runs without network. Assert the run completes and budget tracking
    actually happened (i.e. BudgetGuardedClient is wired in and charging)."""
    # The LLM strategy short-circuits to HOLD during a 60-bar warmup, so the
    # 5-bar fixture would never trigger a guard charge. Synthesize 65 bars.
    base_ts = datetime(2025, 4, 1, tzinfo=UTC)
    synth_bars: list[Bar] = []
    for i in range(65):
        price = 100.0 + 0.5 * i
        synth_bars.append(
            Bar(
                timestamp=base_ts + timedelta(hours=i),
                open=price,
                high=price + 1.0,
                low=price - 0.5,
                close=price + 0.3,
                volume=1000.0 + i,
                taker_buy_volume=500.0 + i / 2,
                cvd=0.0,
                cvd_delta=0.0,
            )
        )

    def fake_load_bars(symbol, timeframe, start, end, root=None):
        yield from synth_bars

    monkeypatch.setattr(main, "load_bars", fake_load_bars)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    monkeypatch.setattr(main, "OpenRouterClient", lambda **_: _FakeOpenRouter())

    # Redirect llm cache to an isolated tmp dir so a stale cache from a
    # previous run doesn't short-circuit the guard and leave spend at 0.
    cache_dir = tmp_path / "llm-cache"
    cache_dir.mkdir()

    real_load_config = main.load_config

    def patched_load_config(path):
        cfg = real_load_config(path)
        cfg.llm.cache_dir = str(cache_dir)
        return cfg

    monkeypatch.setattr(main, "load_config", patched_load_config)

    captured: dict[str, BudgetGuard] = {}
    real_guarded_cls = main.BudgetGuardedClient

    def _capturing(inner, guard, pricing, expected_output_tokens):
        captured["guard"] = guard
        return real_guarded_cls(
            inner=inner,
            guard=guard,
            pricing=pricing,
            expected_output_tokens=expected_output_tokens,
        )

    monkeypatch.setattr(main, "BudgetGuardedClient", _capturing)

    # Wrap walkforward.run to capture the per-asset RunState objects produced
    # by run_state_factory. This lets us assert that _on_progress actually
    # writes to the *current* RunState rather than a discarded placeholder —
    # i.e. that main.run installs the factory in the --no-tui path too.
    original_wf_run = main.walkforward.run
    factory_runstates: list[RunState] = []

    async def _wrapping_wf_run(*args, run_state_factory=None, on_progress=None, **kwargs):
        # If main.run passed rsf=None (the bug), preserve that — let the
        # dedicated `factory_runstates` assertion below produce a clear
        # failure message rather than masking it as an inner AssertionError.
        wrapped_factory = run_state_factory
        if run_state_factory is not None:
            def _capturing_factory(symbol: str) -> RunState:
                rs = run_state_factory(symbol)
                factory_runstates.append(rs)
                return rs
            wrapped_factory = _capturing_factory

        return await original_wf_run(
            *args,
            run_state_factory=wrapped_factory,
            on_progress=on_progress,
            **kwargs,
        )

    monkeypatch.setattr(main.walkforward, "run", _wrapping_wf_run)

    out_dir = tmp_path / "results"

    runner = CliRunner()
    result = runner.invoke(
        main.app,
        [
            "--no-tui",
            "--assets", "BTC/USDT",
            "--start", "2025-04-01",
            "--end", "2025-04-02",
            "--out-dir", str(out_dir),
            "--config", "config.yaml",
        ],
    )

    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
    assert "guard" in captured, "BudgetGuardedClient was not constructed"
    assert captured["guard"].spent_usd > 0.0, (
        f"BudgetGuard never charged; spent_usd={captured['guard'].spent_usd}"
    )
    assert factory_runstates, (
        "run_state_factory was never called — main.run failed to install it "
        "(likely the --no-tui path passed rsf=None)."
    )
    final_rs = factory_runstates[-1]
    assert final_rs.spend_usd == pytest.approx(captured["guard"].spent_usd), (
        f"_on_progress did not propagate spend to the active RunState: "
        f"final_rs.spend_usd={final_rs.spend_usd} vs "
        f"guard.spent_usd={captured['guard'].spent_usd}"
    )
