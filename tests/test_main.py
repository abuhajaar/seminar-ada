"""Smoke test for the Typer CLI in main.py.

Drives `main.app` via Typer's CliRunner with `--mock --no-tui`, monkeypatching
`load_bars` so the run does not depend on real data being downloaded. Verifies
exit code 0 and that `summary.json` is produced with the expected shape.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import main
from core.types import Bar

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
