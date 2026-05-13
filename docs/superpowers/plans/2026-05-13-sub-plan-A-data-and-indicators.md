# Sub-Plan A — Data & Indicators Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic data layer (project scaffolding, OHLCV + aggTrades download, CVD aggregation, shared dataclasses) and the vectorized technical-indicator library, fully unit-tested, so subsequent sub-plans (B: execution, C: LLM agents, D: engine/TUI) can depend on a stable, reproducible substrate.

**Architecture:** Pure-functional indicator module (pandas in → pandas out, no state, no I/O). Data layer is split into three concerns: download (CCXT for OHLCV, raw HTTP for Binance `aggTrades`), aggregation (`aggTrades` → per-bar CVD parquet), and loading (read disk + align timestamps → `Bar` iterator). All disk I/O lives behind small functions so tests can fake the filesystem. No async in this sub-plan — async only matters once the engine and LLM client land in later sub-plans.

**Tech Stack:** Python 3.10+, pandas, numpy, ccxt (sync API for downloader), httpx (for `aggTrades` REST), pyarrow (parquet), pydantic-settings (config), pytest, ruff. **No** ta-lib dependency — we vectorize indicators in pandas/numpy and verify against a reference implementation (`pandas-ta` as dev-only test dep, since ta-lib is painful to install on Windows).

**Spec reference:** `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.en.md` §4 (folders), §5 (types), §10 (config), §11 (test strategy), §13 steps 1–3.

---

## File structure (locked for this sub-plan)

| Path | Purpose |
|---|---|
| `pyproject.toml` | Project metadata, deps, ruff/pytest config |
| `.python-version` | Pin to 3.10 |
| `.env.example` | `OPENROUTER_API_KEY` placeholder |
| `config.yaml` | Full config from spec §10 (already validated; this sub-plan reads `data.*`, `indicators.*`, `run.*` sections) |
| `core/__init__.py` | Empty marker |
| `core/types.py` | `Bar`, `Action`, `Signal`, `AgentReport`, `Trade` dataclasses |
| `core/config.py` | `load_config(path) -> AppConfig` — pydantic-settings model mirroring `config.yaml` |
| `data/__init__.py` | Empty marker |
| `data/paths.py` | Centralized cache paths: `ohlcv_csv_path(symbol, tf)`, `aggtrades_parquet_path(symbol)`, `cvd_parquet_path(symbol, tf)` |
| `data/downloader.py` | `download_ohlcv(symbol, timeframe, start, end)` (ccxt) and `download_aggtrades(symbol, start, end)` (httpx) — idempotent, resumable |
| `data/cvd.py` | `aggregate_cvd(aggtrades_df, timeframe) -> DataFrame[ts, cvd, cvd_delta]` |
| `data/loader.py` | `load_bars(symbol, timeframe, start, end) -> Iterator[Bar]` — joins OHLCV + CVD, yields `Bar` |
| `indicators/__init__.py` | Empty marker |
| `indicators/ta.py` | `rsi`, `macd`, `adx`, `ema`, `supertrend` — all `pd.Series` / `pd.DataFrame` in/out |
| `tests/__init__.py` | Empty marker |
| `tests/conftest.py` | Shared pytest fixtures (synthetic OHLCV, synthetic aggTrades) |
| `tests/test_config.py` | Config loads, defaults, validation errors |
| `tests/test_types.py` | `Bar`/`Signal`/etc. construct + are immutable where required |
| `tests/test_downloader.py` | Mocked ccxt + mocked httpx, idempotency, resume logic |
| `tests/test_cvd.py` | CVD math correctness, timeframe alignment, edge cases |
| `tests/test_loader.py` | Bars produced match OHLCV; CVD attached correctly; misaligned timestamps raise |
| `tests/test_indicators.py` | Each indicator vs `pandas-ta` reference within tolerance |
| `tests/fixtures/btcusdt_1h_sample.csv` | 200 rows of real OHLCV (committed; ~30 KB) |
| `tests/fixtures/btcusdt_aggtrades_sample.parquet` | ~10k aggTrades covering same window |

After this sub-plan: `data/cache/`, `cache/llm/`, `results/`, `strategies/`, `llm/`, `main.py` are **not yet** created — they belong to sub-plans B/C/D.

---

## Task ordering rationale

1. **Project scaffolding** first (Tasks 1–3) so every later task has a working `pytest` and `ruff`.
2. **Types + Config** (Tasks 4–5) — every other task imports these.
3. **Indicators** (Tasks 6–10) — pure functions, no I/O dependencies, easiest to TDD; lets us validate the indicator math before any data plumbing exists.
4. **Downloader** (Tasks 11–12) — talks to network; we mock it in tests.
5. **CVD aggregator** (Task 13) — pure pandas transformation on the downloader's output.
6. **Loader** (Task 14) — glues OHLCV + CVD into the `Bar` stream.
7. **End-to-end smoke** (Task 15) — download a tiny real slice, build the cache, iterate bars, prove the whole pipeline works.

---

## Task 1: Project scaffolding — `pyproject.toml`, `.gitignore` already exists

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.env.example`
- Modify: `.gitignore` (add `tests/fixtures/*.parquet` exception so committed fixture is tracked)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "seminar-ada"
version = "0.1.0"
description = "Comparative analysis of heuristic vs cognitive multi-agent crypto trading systems"
requires-python = ">=3.10,<3.13"
dependencies = [
    "pandas>=2.2",
    "numpy>=1.26",
    "ccxt>=4.3",
    "httpx>=0.27",
    "pyarrow>=16",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "pandas-ta>=0.3.14b",
    "ruff>=0.5",
    "respx>=0.21",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "data*", "indicators*", "strategies*", "llm*"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra --strict-markers"
```

- [ ] **Step 2: Write `.python-version`**

```
3.10
```

- [ ] **Step 3: Write `.env.example`**

```
# OpenRouter API key — used in sub-plan C (LLM agents). Not required for sub-plan A.
OPENROUTER_API_KEY=sk-or-v1-replace-me
```

- [ ] **Step 4: Update `.gitignore`** — add the line `!tests/fixtures/*.parquet` after the existing `data/cache/` line so the committed test fixture isn't ignored (parquet may match a generic pattern later).

Apply this edit:

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/

# Env
.env

# Data & cache
data/cache/
cache/llm/
results/runs/
results/plots/

# Allow committed test fixtures
!tests/fixtures/
!tests/fixtures/**

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 5: Create venv and install**

Run:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```
Expected: installs without errors. `pip list` shows `pandas`, `pytest`, `pandas-ta`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .python-version .env.example .gitignore
git commit -m "chore: bootstrap pyproject, deps, env example"
```

---

## Task 2: Verify pytest runs (empty test)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Create `tests/__init__.py`** — empty file.

- [ ] **Step 2: Write `tests/test_smoke.py`**

```python
def test_python_works():
    assert 1 + 1 == 2
```

- [ ] **Step 3: Run pytest**

Run: `pytest -v`
Expected: `1 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: smoke test verifies pytest works"
```

---

## Task 3: Copy `config.yaml` from the spec verbatim

**Files:**
- Create: `config.yaml`

- [ ] **Step 1: Write `config.yaml`** — exact copy of spec §10:

```yaml
run:
  assets: [BTC/USDT, ETH/USDT, SOL/USDT]
  timeframe: 1h
  start: 2025-04-01
  end:   2025-04-21
  initial_balance: 10000

execution:
  fill: next_bar_open
  taker_fee_bps: 4
  slippage_bps: 2
  risk_pct: 0.02

indicators:
  rsi: 14
  macd: [12, 26, 9]
  adx: 14
  ema_fast: 20
  ema_slow: 50
  supertrend: [10, 3]

llm:
  cache_dir: cache/llm
  max_usd: 10.00
  agents:
    technical: { model: anthropic/claude-3.5-sonnet, temperature: 0 }
    visual:    { model: anthropic/claude-3.5-sonnet, temperature: 0, chart_window: 100 }
    qabba:     { model: anthropic/claude-3.5-sonnet, temperature: 0, lookback: 50 }
    decision:  { model: anthropic/claude-3.5-sonnet, temperature: 0 }
  consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
  consensus_threshold: 0.50

data:
  source: binance
  qabba_mode: aggtrades
```

- [ ] **Step 2: Commit**

```bash
git add config.yaml
git commit -m "chore: add config.yaml from spec"
```

---

## Task 4: `core/types.py` — dataclasses

**Files:**
- Create: `core/__init__.py`
- Create: `core/types.py`
- Create: `tests/test_types.py`

- [ ] **Step 1: Create `core/__init__.py`** — empty file.

- [ ] **Step 2: Write the failing test `tests/test_types.py`**

```python
from datetime import datetime, timezone

import pytest

from core.types import Action, AgentReport, Bar, Signal, Trade


def _bar(**overrides):
    base = dict(
        timestamp=datetime(2025, 4, 1, 0, 0, tzinfo=timezone.utc),
        open=100.0, high=101.0, low=99.5, close=100.5,
        volume=1000.0, taker_buy_volume=550.0,
        cvd=120.0, cvd_delta=20.0,
    )
    base.update(overrides)
    return Bar(**base)


def test_bar_is_immutable():
    bar = _bar()
    with pytest.raises(Exception):  # FrozenInstanceError
        bar.close = 200.0  # type: ignore[misc]


def test_bar_round_trip_fields():
    bar = _bar(close=101.25)
    assert bar.close == 101.25
    assert bar.timestamp.tzinfo is timezone.utc


def test_action_enum_values():
    assert Action.BUY.value == "BUY"
    assert Action.SELL.value == "SELL"
    assert Action.HOLD.value == "HOLD"


def test_signal_construct():
    s = Signal(action=Action.BUY, confidence=0.8, reasoning="EMA cross", stop_loss=98.0)
    assert s.action is Action.BUY
    assert s.stop_loss == 98.0


def test_signal_hold_has_no_stop():
    s = Signal(action=Action.HOLD, confidence=0.0, reasoning="no setup", stop_loss=None)
    assert s.stop_loss is None


def test_agent_report_construct():
    r = AgentReport(action=Action.SELL, confidence=0.7, rationale="bearish")
    assert r.action is Action.SELL


def test_trade_pnl_property():
    t = Trade(
        entry_ts=datetime(2025, 4, 1, tzinfo=timezone.utc),
        exit_ts=datetime(2025, 4, 1, 1, tzinfo=timezone.utc),
        entry_price=100.0, exit_price=110.0, qty=2.0,
        side=Action.BUY, fees=0.5,
    )
    # gross = (110 - 100) * 2 = 20; net = 20 - 0.5 = 19.5
    assert t.pnl == pytest.approx(19.5)
```

- [ ] **Step 3: Run test, expect failure**

Run: `pytest tests/test_types.py -v`
Expected: `ImportError: cannot import name 'Action' from 'core.types'`.

- [ ] **Step 4: Implement `core/types.py`**

```python
"""Shared dataclasses used across engine, strategies, broker, and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar with attached cumulative-volume-delta fields.

    `cvd` is cumulative across the entire backtest window; `cvd_delta` is
    this bar's contribution. Both are computed up-front by `data/cvd.py`
    so the engine can read them in O(1) per bar.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    taker_buy_volume: float
    cvd: float
    cvd_delta: float


@dataclass
class Signal:
    """A strategy's decision for a given bar.

    `confidence` is informational only — position sizing uses the
    fixed-fractional rule from `config.execution.risk_pct`.
    `stop_loss` is the SuperTrend stop for the traditional bot;
    LLM-bot signals may set it to None, in which case the broker uses
    a default ATR-based stop (see sub-plan B).
    """

    action: Action
    confidence: float
    reasoning: str
    stop_loss: float | None


@dataclass
class AgentReport:
    """Output of one LLM analyst node (Technical, Visual, QABBA)."""

    action: Action
    confidence: float
    rationale: str


@dataclass
class Trade:
    """A completed round-trip trade. Used by metrics + persistence."""

    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    qty: float
    side: Action  # Action.BUY for long, Action.SELL for short
    fees: float

    @property
    def pnl(self) -> float:
        direction = 1.0 if self.side is Action.BUY else -1.0
        gross = (self.exit_price - self.entry_price) * self.qty * direction
        return gross - self.fees
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/test_types.py -v`
Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add core/ tests/test_types.py
git commit -m "feat(core): shared dataclasses (Bar, Signal, AgentReport, Trade)"
```

---

## Task 5: `core/config.py` — pydantic config loader

**Files:**
- Create: `core/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test `tests/test_config.py`**

```python
from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest

from core.config import AppConfig, load_config


def test_load_config_from_repo_root(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(dedent("""
        run:
          assets: [BTC/USDT]
          timeframe: 1h
          start: 2025-04-01
          end:   2025-04-21
          initial_balance: 10000
        execution:
          fill: next_bar_open
          taker_fee_bps: 4
          slippage_bps: 2
          risk_pct: 0.02
        indicators:
          rsi: 14
          macd: [12, 26, 9]
          adx: 14
          ema_fast: 20
          ema_slow: 50
          supertrend: [10, 3]
        llm:
          cache_dir: cache/llm
          max_usd: 10.00
          agents:
            technical: { model: x/y, temperature: 0 }
            visual:    { model: x/y, temperature: 0, chart_window: 100 }
            qabba:     { model: x/y, temperature: 0, lookback: 50 }
            decision:  { model: x/y, temperature: 0 }
          consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
          consensus_threshold: 0.50
        data:
          source: binance
          qabba_mode: aggtrades
    """))
    cfg = load_config(cfg_path)
    assert isinstance(cfg, AppConfig)
    assert cfg.run.assets == ["BTC/USDT"]
    assert cfg.run.timeframe == "1h"
    assert cfg.run.start == date(2025, 4, 1)
    assert cfg.execution.taker_fee_bps == 4
    assert cfg.indicators.macd == (12, 26, 9)
    assert cfg.indicators.supertrend == (10, 3)
    assert cfg.llm.consensus_weights["qabba"] == 0.40
    assert cfg.data.qabba_mode == "aggtrades"


def test_consensus_weights_must_sum_to_one(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(dedent("""
        run: { assets: [BTC/USDT], timeframe: 1h, start: 2025-04-01, end: 2025-04-21, initial_balance: 10000 }
        execution: { fill: next_bar_open, taker_fee_bps: 4, slippage_bps: 2, risk_pct: 0.02 }
        indicators: { rsi: 14, macd: [12,26,9], adx: 14, ema_fast: 20, ema_slow: 50, supertrend: [10,3] }
        llm:
          cache_dir: cache/llm
          max_usd: 10
          agents:
            technical: { model: x, temperature: 0 }
            visual:    { model: x, temperature: 0, chart_window: 100 }
            qabba:     { model: x, temperature: 0, lookback: 50 }
            decision:  { model: x, temperature: 0 }
          consensus_weights: { qabba: 0.50, visual: 0.50, technical: 0.50 }
          consensus_threshold: 0.50
        data: { source: binance, qabba_mode: aggtrades }
    """))
    with pytest.raises(ValueError, match="consensus_weights"):
        load_config(cfg_path)


def test_qabba_mode_only_aggtrades(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(dedent("""
        run: { assets: [BTC/USDT], timeframe: 1h, start: 2025-04-01, end: 2025-04-21, initial_balance: 10000 }
        execution: { fill: next_bar_open, taker_fee_bps: 4, slippage_bps: 2, risk_pct: 0.02 }
        indicators: { rsi: 14, macd: [12,26,9], adx: 14, ema_fast: 20, ema_slow: 50, supertrend: [10,3] }
        llm:
          cache_dir: cache/llm
          max_usd: 10
          agents:
            technical: { model: x, temperature: 0 }
            visual:    { model: x, temperature: 0, chart_window: 100 }
            qabba:     { model: x, temperature: 0, lookback: 50 }
            decision:  { model: x, temperature: 0 }
          consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
          consensus_threshold: 0.50
        data: { source: binance, qabba_mode: kline }
    """))
    with pytest.raises(ValueError, match="qabba_mode"):
        load_config(cfg_path)
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/test_config.py -v`
Expected: `ImportError: cannot import name 'AppConfig'`.

- [ ] **Step 3: Implement `core/config.py`**

```python
"""Pydantic config model + loader for `config.yaml`."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class RunCfg(BaseModel):
    assets: list[str]
    timeframe: str
    start: date
    end: date
    initial_balance: float


class ExecutionCfg(BaseModel):
    fill: Literal["next_bar_open"]
    taker_fee_bps: float
    slippage_bps: float
    risk_pct: float = Field(gt=0, lt=1)


class IndicatorsCfg(BaseModel):
    rsi: int
    macd: tuple[int, int, int]
    adx: int
    ema_fast: int
    ema_slow: int
    supertrend: tuple[int, float]

    @field_validator("macd", mode="before")
    @classmethod
    def _macd_tuple(cls, v):
        return tuple(v)

    @field_validator("supertrend", mode="before")
    @classmethod
    def _st_tuple(cls, v):
        return tuple(v)


class AgentCfg(BaseModel):
    model: str
    temperature: float = 0.0
    chart_window: int | None = None
    lookback: int | None = None


class LlmCfg(BaseModel):
    cache_dir: str
    max_usd: float
    agents: dict[str, AgentCfg]
    consensus_weights: dict[str, float]
    consensus_threshold: float

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = sum(self.consensus_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"consensus_weights must sum to 1.0, got {total}"
            )
        return self


class DataCfg(BaseModel):
    source: Literal["binance"]
    qabba_mode: Literal["aggtrades"]


class AppConfig(BaseModel):
    run: RunCfg
    execution: ExecutionCfg
    indicators: IndicatorsCfg
    llm: LlmCfg
    data: DataCfg


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())
    return AppConfig.model_validate(raw)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_config.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat(core): pydantic config loader with validators"
```

---

## Task 6: Indicator — `ema`

**Files:**
- Create: `indicators/__init__.py`
- Create: `indicators/ta.py`
- Create: `tests/test_indicators.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `indicators/__init__.py`** — empty file.

- [ ] **Step 2: Create `tests/conftest.py` with a synthetic OHLCV fixture**

```python
"""Shared pytest fixtures.

`synth_ohlcv` returns a deterministic 500-bar 1h OHLCV DataFrame with mild
trend and noise — enough for indicator math to be meaningful.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="session")
def synth_ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    n = 500
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    drift = np.linspace(0, 20, n)
    noise = rng.normal(0, 1.0, n).cumsum()
    close = 100 + drift + noise
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.uniform(100, 1000, n)
    taker_buy = volume * rng.uniform(0.4, 0.6, n)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "taker_buy_volume": taker_buy,
        },
        index=idx,
    )
```

- [ ] **Step 3: Write the failing EMA test in `tests/test_indicators.py`**

```python
"""Indicator math validated against `pandas-ta` reference (dev dep)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as pta
import pytest

from indicators.ta import ema


def test_ema_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    close = synth_ohlcv["close"]
    ours = ema(close, length=20).dropna()
    ref = pta.ema(close, length=20).dropna()
    # Align on the intersection of indices
    idx = ours.index.intersection(ref.index)
    np.testing.assert_allclose(ours.loc[idx].values, ref.loc[idx].values, rtol=1e-10)


def test_ema_length_must_be_positive(synth_ohlcv: pd.DataFrame):
    with pytest.raises(ValueError):
        ema(synth_ohlcv["close"], length=0)
```

- [ ] **Step 4: Run tests, expect failure**

Run: `pytest tests/test_indicators.py -v`
Expected: `ImportError: cannot import name 'ema' from 'indicators.ta'`.

- [ ] **Step 5: Implement `indicators/ta.py` with `ema` only**

```python
"""Vectorized technical indicators.

All functions are pure: pandas in, pandas out. No I/O. No state.
The `length` argument follows the convention from common TA libraries:
the EMA's smoothing factor is `2 / (length + 1)`.
"""

from __future__ import annotations

import pandas as pd


def _check_length(length: int, name: str) -> None:
    if length <= 0:
        raise ValueError(f"{name} length must be positive, got {length}")


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average using pandas' adjust=False semantics."""
    _check_length(length, "ema")
    return series.ewm(span=length, adjust=False, min_periods=length).mean()
```

- [ ] **Step 6: Run tests, expect pass**

Run: `pytest tests/test_indicators.py -v`
Expected: `2 passed`.

- [ ] **Step 7: Commit**

```bash
git add indicators/ tests/conftest.py tests/test_indicators.py
git commit -m "feat(indicators): EMA + synthetic OHLCV fixture"
```

---

## Task 7: Indicator — `rsi`

**Files:**
- Modify: `indicators/ta.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Append failing RSI tests**

Append to `tests/test_indicators.py`:

```python
from indicators.ta import rsi


def test_rsi_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    close = synth_ohlcv["close"]
    ours = rsi(close, length=14).dropna()
    ref = pta.rsi(close, length=14).dropna()
    idx = ours.index.intersection(ref.index)
    np.testing.assert_allclose(ours.loc[idx].values, ref.loc[idx].values, rtol=1e-3)


def test_rsi_bounds(synth_ohlcv: pd.DataFrame):
    r = rsi(synth_ohlcv["close"], length=14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
```

(Note: RSI tolerance is `1e-3` because Wilder's smoothing seed convention varies slightly between implementations.)

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_indicators.py -v -k rsi`
Expected: `ImportError`.

- [ ] **Step 3: Append `rsi` to `indicators/ta.py`**

```python
def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI. Matches pandas-ta's `rsi(..., length=length)`."""
    _check_length(length, "rsi")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing = EMA with alpha=1/length
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_indicators.py -v -k rsi`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add indicators/ta.py tests/test_indicators.py
git commit -m "feat(indicators): RSI (Wilder)"
```

---

## Task 8: Indicator — `macd`

**Files:**
- Modify: `indicators/ta.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Append failing MACD test**

```python
from indicators.ta import macd


def test_macd_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    close = synth_ohlcv["close"]
    ours = macd(close, fast=12, slow=26, signal=9).dropna()
    ref = pta.macd(close, fast=12, slow=26, signal=9).dropna()
    # pandas-ta names: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    np.testing.assert_allclose(
        ours["macd"].values, ref["MACD_12_26_9"].loc[ours.index].values, rtol=1e-10
    )
    np.testing.assert_allclose(
        ours["signal"].values, ref["MACDs_12_26_9"].loc[ours.index].values, rtol=1e-10
    )
    np.testing.assert_allclose(
        ours["hist"].values, ref["MACDh_12_26_9"].loc[ours.index].values, rtol=1e-10
    )
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_indicators.py -v -k macd`
Expected: `ImportError`.

- [ ] **Step 3: Append `macd` to `indicators/ta.py`**

```python
def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, signal); hist = MACD - signal.

    Returns a DataFrame with columns `macd`, `signal`, `hist`.
    """
    _check_length(fast, "macd.fast")
    _check_length(slow, "macd.slow")
    _check_length(signal, "macd.signal")
    if fast >= slow:
        raise ValueError(f"macd.fast ({fast}) must be < macd.slow ({slow})")
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line.dropna(), signal).reindex(series.index)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_indicators.py -v -k macd`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add indicators/ta.py tests/test_indicators.py
git commit -m "feat(indicators): MACD"
```

---

## Task 9: Indicator — `adx`

**Files:**
- Modify: `indicators/ta.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Append failing ADX test**

```python
from indicators.ta import adx


def test_adx_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    df = synth_ohlcv
    ours = adx(df["high"], df["low"], df["close"], length=14).dropna()
    ref = pta.adx(df["high"], df["low"], df["close"], length=14).dropna()
    # pandas-ta column: ADX_14
    idx = ours.index.intersection(ref.index)
    np.testing.assert_allclose(
        ours.loc[idx].values, ref["ADX_14"].loc[idx].values, rtol=5e-3
    )
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_indicators.py -v -k adx`
Expected: `ImportError`.

- [ ] **Step 3: Append `adx` to `indicators/ta.py`**

```python
def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's ADX. Returns the ADX line only (DI+ / DI- not exposed)."""
    _check_length(length, "adx")
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down

    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    plus_di = 100 * (
        plus_dm.ewm(alpha=1 / length, adjust=False, min_periods=length).mean() / atr
    )
    minus_di = 100 * (
        minus_dm.ewm(alpha=1 / length, adjust=False, min_periods=length).mean() / atr
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_indicators.py -v -k adx`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add indicators/ta.py tests/test_indicators.py
git commit -m "feat(indicators): ADX (Wilder)"
```

---

## Task 10: Indicator — `supertrend`

**Files:**
- Modify: `indicators/ta.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Append failing SuperTrend test**

```python
from indicators.ta import supertrend


def test_supertrend_shape_and_signal(synth_ohlcv: pd.DataFrame):
    df = synth_ohlcv
    st = supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    # Returns columns 'st' (line) and 'dir' (+1 long, -1 short)
    assert set(st.columns) == {"st", "dir"}
    assert st["dir"].dropna().isin([1, -1]).all()
    # Line should sit below close during long regimes, above during short
    longs = st[st["dir"] == 1].dropna()
    shorts = st[st["dir"] == -1].dropna()
    if len(longs) > 0:
        assert (longs["st"] <= df.loc[longs.index, "close"]).all()
    if len(shorts) > 0:
        assert (shorts["st"] >= df.loc[shorts.index, "close"]).all()


def test_supertrend_matches_pandas_ta(synth_ohlcv: pd.DataFrame):
    df = synth_ohlcv
    ours = supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    ref = pta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    # pandas-ta columns: SUPERT_10_3.0, SUPERTd_10_3.0
    idx = ours["st"].dropna().index.intersection(ref["SUPERT_10_3.0"].dropna().index)
    # Allow small numerical drift, esp. at regime flips
    np.testing.assert_allclose(
        ours["st"].loc[idx].values, ref["SUPERT_10_3.0"].loc[idx].values, rtol=1e-2
    )
    # Direction should match exactly on the overlap
    np.testing.assert_array_equal(
        ours["dir"].loc[idx].values.astype(int),
        ref["SUPERTd_10_3.0"].loc[idx].values.astype(int),
    )
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_indicators.py -v -k supertrend`
Expected: `ImportError`.

- [ ] **Step 3: Append `supertrend` to `indicators/ta.py`**

```python
import numpy as np


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """SuperTrend trailing stop.

    Returns DataFrame with:
        st  : the trailing stop line
        dir : +1 when in long regime (line below price), -1 when short.
    """
    _check_length(length, "supertrend")
    if multiplier <= 0:
        raise ValueError(f"supertrend multiplier must be positive, got {multiplier}")

    hl2 = (high + low) / 2.0
    tr = _true_range(high, low, close)
    atr = tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    n = len(close)
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    direction = np.full(n, np.nan)
    st = np.full(n, np.nan)

    # First valid index = first non-NaN ATR
    first_valid = atr.first_valid_index()
    if first_valid is None:
        return pd.DataFrame({"st": st, "dir": direction}, index=close.index)
    start = close.index.get_loc(first_valid)

    direction[start] = 1
    st[start] = lower.iloc[start]

    upper_arr = upper.values
    lower_arr = lower.values
    upper_basic_arr = upper_basic.values
    lower_basic_arr = lower_basic.values
    close_arr = close.values

    for i in range(start + 1, n):
        # Trailing-stop "carry forward" rule from Olorunnimbe / TradingView
        if upper_basic_arr[i] < upper_arr[i - 1] or close_arr[i - 1] > upper_arr[i - 1]:
            upper_arr[i] = upper_basic_arr[i]
        else:
            upper_arr[i] = upper_arr[i - 1]
        if lower_basic_arr[i] > lower_arr[i - 1] or close_arr[i - 1] < lower_arr[i - 1]:
            lower_arr[i] = lower_basic_arr[i]
        else:
            lower_arr[i] = lower_arr[i - 1]

        prev_dir = direction[i - 1]
        if prev_dir == 1:
            direction[i] = -1 if close_arr[i] < lower_arr[i] else 1
        else:
            direction[i] = 1 if close_arr[i] > upper_arr[i] else -1
        st[i] = lower_arr[i] if direction[i] == 1 else upper_arr[i]

    return pd.DataFrame({"st": st, "dir": direction.astype(float)}, index=close.index)
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_indicators.py -v -k supertrend`
Expected: `2 passed`.

- [ ] **Step 5: Run full indicator suite to make sure nothing broke**

Run: `pytest tests/test_indicators.py -v`
Expected: all green (~8 tests).

- [ ] **Step 6: Commit**

```bash
git add indicators/ta.py tests/test_indicators.py
git commit -m "feat(indicators): SuperTrend trailing stop"
```

---

## Task 11: `data/paths.py` — centralized cache paths

**Files:**
- Create: `data/__init__.py`
- Create: `data/paths.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1: Create `data/__init__.py`** — empty.

- [ ] **Step 2: Write the failing test `tests/test_paths.py`**

```python
from pathlib import Path

from data.paths import aggtrades_parquet_path, cvd_parquet_path, ohlcv_csv_path


def test_ohlcv_path_normalizes_symbol(tmp_path: Path):
    p = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    assert p == tmp_path / "ohlcv" / "BTCUSDT_1h.csv"


def test_aggtrades_path(tmp_path: Path):
    p = aggtrades_parquet_path("BTC/USDT", root=tmp_path)
    assert p == tmp_path / "aggtrades" / "BTCUSDT.parquet"


def test_cvd_path_includes_timeframe(tmp_path: Path):
    p = cvd_parquet_path("ETH/USDT", "4h", root=tmp_path)
    assert p == tmp_path / "cvd" / "ETHUSDT_4h.parquet"
```

- [ ] **Step 3: Run, expect failure**

Run: `pytest tests/test_paths.py -v`
Expected: `ImportError`.

- [ ] **Step 4: Implement `data/paths.py`**

```python
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


def cvd_parquet_path(symbol: str, timeframe: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / "cvd" / f"{_norm(symbol)}_{timeframe}.parquet"
```

- [ ] **Step 5: Run, expect pass**

Run: `pytest tests/test_paths.py -v`
Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add data/ tests/test_paths.py
git commit -m "feat(data): centralized cache path helpers"
```

---

## Task 12: `data/downloader.py` — OHLCV (mocked) + aggTrades (mocked)

**Files:**
- Create: `data/downloader.py`
- Create: `tests/test_downloader.py`

This is the most "real-world" module. We TDD it with mocked CCXT and `respx`-mocked HTTP. A live integration test happens in Task 15.

- [ ] **Step 1: Write the failing test `tests/test_downloader.py`**

```python
"""Downloader tests use a mocked ccxt exchange and respx-mocked Binance REST."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest
import respx

from data.downloader import download_aggtrades, download_ohlcv
from data.paths import aggtrades_parquet_path, ohlcv_csv_path


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_download_ohlcv_writes_csv_and_is_idempotent(tmp_path: Path):
    fake_exchange = MagicMock()
    # ccxt returns: [[ts_ms, open, high, low, close, volume], ...]
    rows = [
        [_ms(datetime(2025, 4, 1, h)), 100 + h, 101 + h, 99 + h, 100.5 + h, 10.0 + h]
        for h in range(24)
    ]
    fake_exchange.parse_timeframe.return_value = 3600  # seconds in 1h
    fake_exchange.fetch_ohlcv.return_value = rows

    out = download_ohlcv(
        symbol="BTC/USDT",
        timeframe="1h",
        start=date(2025, 4, 1),
        end=date(2025, 4, 2),
        exchange=fake_exchange,
        root=tmp_path,
    )
    assert out == ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    assert out.exists()
    df = pd.read_csv(out, parse_dates=["timestamp"])
    assert len(df) == 24
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    # Re-running with same args should NOT re-fetch (idempotent).
    fake_exchange.fetch_ohlcv.reset_mock()
    download_ohlcv(
        symbol="BTC/USDT", timeframe="1h",
        start=date(2025, 4, 1), end=date(2025, 4, 2),
        exchange=fake_exchange, root=tmp_path,
    )
    fake_exchange.fetch_ohlcv.assert_not_called()


@respx.mock
def test_download_aggtrades_writes_parquet_and_resumes(tmp_path: Path):
    # Binance returns up to 1000 trades per page, paginate by `fromId`.
    page1 = [
        {"a": i, "p": "100.0", "q": "0.5", "T": _ms(datetime(2025, 4, 1, 0, i // 60, i % 60)),
         "m": (i % 2 == 0)}
        for i in range(1000)
    ]
    page2 = [
        {"a": 1000 + i, "p": "100.0", "q": "0.5",
         "T": _ms(datetime(2025, 4, 1, 1, i // 60, i % 60)), "m": False}
        for i in range(50)
    ]
    page3: list = []  # empty → done

    route = respx.get("https://api.binance.com/api/v3/aggTrades").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
            httpx.Response(200, json=page3),
        ]
    )

    out = download_aggtrades(
        symbol="BTC/USDT",
        start=date(2025, 4, 1),
        end=date(2025, 4, 2),
        root=tmp_path,
    )
    assert out == aggtrades_parquet_path("BTC/USDT", root=tmp_path)
    df = pd.read_parquet(out)
    assert len(df) == 1050
    assert set(df.columns) == {"agg_id", "price", "qty", "ts", "is_buyer_maker"}
    assert df["agg_id"].is_monotonic_increasing
    assert route.call_count == 3


@respx.mock
def test_download_aggtrades_resumes_from_existing(tmp_path: Path):
    # Pre-seed an existing parquet so the downloader resumes from agg_id=500.
    seed = pd.DataFrame(
        {
            "agg_id": list(range(500)),
            "price": [100.0] * 500,
            "qty": [0.5] * 500,
            "ts": [_ms(datetime(2025, 4, 1)) + i * 1000 for i in range(500)],
            "is_buyer_maker": [False] * 500,
        }
    )
    path = aggtrades_parquet_path("BTC/USDT", root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seed.to_parquet(path)

    page = [
        {"a": 500 + i, "p": "100.0", "q": "0.5",
         "T": _ms(datetime(2025, 4, 1, 0, 30)) + i, "m": False}
        for i in range(100)
    ]
    respx.get("https://api.binance.com/api/v3/aggTrades").mock(
        side_effect=[httpx.Response(200, json=page), httpx.Response(200, json=[])]
    )

    download_aggtrades(
        symbol="BTC/USDT", start=date(2025, 4, 1), end=date(2025, 4, 2), root=tmp_path
    )
    df = pd.read_parquet(path)
    assert len(df) == 600
    assert df["agg_id"].max() == 599
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_downloader.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Implement `data/downloader.py`**

```python
"""Download OHLCV (via ccxt) and aggTrades (via Binance REST).

Both functions are idempotent and resumable:
- OHLCV: if the target CSV already exists with full coverage, skip.
- aggTrades: if a parquet exists, resume from `max(agg_id) + 1`.

Network errors are surfaced (no retry) — let the caller decide policy.
Sub-plan B/C/D may wrap with tenacity later.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from data.paths import DEFAULT_ROOT, aggtrades_parquet_path, ohlcv_csv_path

BINANCE_AGGTRADES_URL = "https://api.binance.com/api/v3/aggTrades"
AGGTRADES_PAGE_LIMIT = 1000


def _date_to_ms(d: date, *, end: bool = False) -> int:
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if end:
        # End-of-day exclusive: caller passes `end` meaning "stop AT start of this date".
        pass
    return int(dt.timestamp() * 1000)


def download_ohlcv(
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    exchange: Any,
    root: Path = DEFAULT_ROOT,
) -> Path:
    """Download OHLCV using a ccxt exchange instance.

    Idempotent: if the target CSV already exists and covers [start, end), skip.
    """
    out = ohlcv_csv_path(symbol, timeframe, root=root)
    out.parent.mkdir(parents=True, exist_ok=True)

    start_ms = _date_to_ms(start)
    end_ms = _date_to_ms(end)
    tf_seconds = exchange.parse_timeframe(timeframe)
    tf_ms = tf_seconds * 1000

    if out.exists():
        existing = pd.read_csv(out, parse_dates=["timestamp"])
        if len(existing) > 0:
            cov_start = int(existing["timestamp"].iloc[0].timestamp() * 1000)
            cov_end = int(existing["timestamp"].iloc[-1].timestamp() * 1000) + tf_ms
            if cov_start <= start_ms and cov_end >= end_ms:
                return out  # already fully covered

    rows: list[list[float]] = []
    cursor = start_ms
    while cursor < end_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + tf_ms
        if len(batch) < 1000:
            break

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df[df["timestamp"] < end_ms]
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
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
                params["endTime"] = min(start_ms + 60 * 60 * 1000, end_ms)  # 1h window seed

            resp = client.get(BINANCE_AGGTRADES_URL, params=params)
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            for t in page:
                if t["T"] >= end_ms:
                    page = [x for x in page if x["T"] < end_ms]
                    new_rows.extend(_row(x) for x in page)
                    next_id = None  # signal stop
                    break
                new_rows.append(_row(t))
            if next_id is None and not new_rows:
                break
            if next_id is None:
                break
            next_id = page[-1]["a"] + 1
            time.sleep(sleep_s)
            if page[-1]["T"] >= end_ms:
                break
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
        merged = merged.drop_duplicates(subset=["agg_id"]).sort_values("agg_id").reset_index(drop=True)
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
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_downloader.py -v`
Expected: `3 passed`. If the resume-mode test fails because the implementation calls the URL once with `startTime` even though `next_id` is set, fix the conditional in `download_aggtrades` to skip the seed branch when resuming, then re-run.

- [ ] **Step 5: Commit**

```bash
git add data/downloader.py tests/test_downloader.py
git commit -m "feat(data): OHLCV (ccxt) + aggTrades (httpx) downloaders, idempotent"
```

---

## Task 13: `data/cvd.py` — aggTrades → per-bar CVD

**Files:**
- Create: `data/cvd.py`
- Create: `tests/test_cvd.py`

- [ ] **Step 1: Write the failing test `tests/test_cvd.py`**

```python
"""CVD aggregation: convert per-trade aggTrades into per-bar CVD."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from data.cvd import aggregate_cvd


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _trades(rows: list[tuple[int, float, float, bool]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["agg_id", "price", "qty", "is_buyer_maker_and_ts"]
    )


def test_cvd_basic_aggregation():
    # Bar 1 (00:00–01:00): 3 buys (5,3,2 qty), 2 sells (4,1) → delta = 10 - 5 = +5
    # Bar 2 (01:00–02:00): 1 buy (8), 3 sells (2,2,2)        → delta = 8 - 6  = +2
    # Cumulative: bar1=5, bar2=7
    df = pd.DataFrame(
        {
            "agg_id": list(range(8)),
            "price": [100.0] * 8,
            "qty": [5, 3, 2, 4, 1, 8, 2, 2],
            "ts": [
                _ms(datetime(2025, 4, 1, 0, 5)),
                _ms(datetime(2025, 4, 1, 0, 15)),
                _ms(datetime(2025, 4, 1, 0, 25)),
                _ms(datetime(2025, 4, 1, 0, 35)),
                _ms(datetime(2025, 4, 1, 0, 45)),
                _ms(datetime(2025, 4, 1, 1, 5)),
                _ms(datetime(2025, 4, 1, 1, 25)),
                _ms(datetime(2025, 4, 1, 1, 45)),
            ],
            # is_buyer_maker = True means the BUYER was the passive maker → trade was a SELL
            "is_buyer_maker": [False, False, False, True, True, False, True, True],
        }
    )
    out = aggregate_cvd(df, timeframe="1h")
    assert list(out.columns) == ["timestamp", "cvd_delta", "cvd"]
    assert len(out) == 2
    np.testing.assert_array_equal(out["cvd_delta"].values, [5.0, 2.0])
    np.testing.assert_array_equal(out["cvd"].values, [5.0, 7.0])
    assert out["timestamp"].iloc[0] == pd.Timestamp("2025-04-01 00:00", tz="UTC")
    assert out["timestamp"].iloc[1] == pd.Timestamp("2025-04-01 01:00", tz="UTC")


def test_cvd_empty_input():
    df = pd.DataFrame(columns=["agg_id", "price", "qty", "ts", "is_buyer_maker"])
    out = aggregate_cvd(df, timeframe="1h")
    assert len(out) == 0
    assert list(out.columns) == ["timestamp", "cvd_delta", "cvd"]


def test_cvd_unsupported_timeframe():
    df = pd.DataFrame(columns=["agg_id", "price", "qty", "ts", "is_buyer_maker"])
    with pytest.raises(ValueError, match="timeframe"):
        aggregate_cvd(df, timeframe="banana")
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_cvd.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Implement `data/cvd.py`**

```python
"""Aggregate Binance aggTrades into per-bar CVD.

Convention:
    is_buyer_maker == True  → the buyer was the resting maker, so the
                              trade is a SELL (taker hit the bid).
    is_buyer_maker == False → the trade is a BUY (taker lifted the ask).

cvd_delta = sum(buy_qty) - sum(sell_qty) within the bar.
cvd       = cumulative sum of cvd_delta over the entire window.
"""

from __future__ import annotations

import pandas as pd

_TF_TO_PANDAS = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}


def aggregate_cvd(trades: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Return DataFrame with columns `timestamp` (UTC, bar-open), `cvd_delta`, `cvd`."""
    if timeframe not in _TF_TO_PANDAS:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. Supported: {sorted(_TF_TO_PANDAS)}"
        )
    if len(trades) == 0:
        return pd.DataFrame(columns=["timestamp", "cvd_delta", "cvd"])

    df = trades.copy()
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    # signed_qty: +qty for buy (is_buyer_maker=False), -qty for sell
    df["signed_qty"] = df["qty"].where(~df["is_buyer_maker"], -df["qty"])

    grouped = (
        df.set_index("timestamp")["signed_qty"]
        .resample(_TF_TO_PANDAS[timeframe], label="left", closed="left")
        .sum()
        .rename("cvd_delta")
        .to_frame()
    )
    grouped["cvd"] = grouped["cvd_delta"].cumsum()
    return grouped.reset_index()
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_cvd.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add data/cvd.py tests/test_cvd.py
git commit -m "feat(data): aggregate aggTrades into per-bar CVD"
```

---

## Task 14: `data/loader.py` — `Bar` iterator joining OHLCV + CVD

**Files:**
- Create: `data/loader.py`
- Create: `tests/test_loader.py`

- [ ] **Step 1: Write the failing test `tests/test_loader.py`**

```python
"""Loader: read OHLCV CSV + CVD parquet from disk, yield Bar objects."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from core.types import Bar
from data.loader import load_bars
from data.paths import cvd_parquet_path, ohlcv_csv_path


def _seed(tmp_path: Path):
    ohlcv = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-04-01", periods=4, freq="1h", tz="UTC"),
            "open":  [100.0, 101.0, 102.0, 103.0],
            "high":  [101.5, 102.5, 103.5, 104.5],
            "low":   [99.0, 100.0, 101.0, 102.0],
            "close": [101.0, 102.0, 103.0, 104.0],
            "volume": [10.0, 11.0, 12.0, 13.0],
        }
    )
    op = ohlcv_csv_path("BTC/USDT", "1h", root=tmp_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(op, index=False)

    # Note: loader must derive taker_buy_volume; for the aggtrades pipeline
    # we approximate it by counting buy qty in the same bar window.
    # For loader unit tests we ship a synthetic CVD that already includes it.
    cvd = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-04-01", periods=4, freq="1h", tz="UTC"),
            "cvd_delta": [1.0, -2.0, 3.0, -1.0],
            "cvd":       [1.0, -1.0, 2.0,  1.0],
            "taker_buy_volume": [6.0, 4.5, 7.5, 6.0],
        }
    )
    cp = cvd_parquet_path("BTC/USDT", "1h", root=tmp_path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cvd.to_parquet(cp, index=False)


def test_load_bars_yields_bars(tmp_path: Path):
    _seed(tmp_path)
    bars = list(
        load_bars(
            symbol="BTC/USDT",
            timeframe="1h",
            start=date(2025, 4, 1),
            end=date(2025, 4, 2),
            root=tmp_path,
        )
    )
    assert len(bars) == 4
    assert all(isinstance(b, Bar) for b in bars)
    assert bars[0].timestamp == datetime(2025, 4, 1, 0, 0, tzinfo=timezone.utc)
    assert bars[2].close == 103.0
    assert bars[2].cvd == 2.0
    assert bars[2].cvd_delta == 3.0
    assert bars[2].taker_buy_volume == 7.5


def test_load_bars_filters_window(tmp_path: Path):
    _seed(tmp_path)
    bars = list(
        load_bars(
            symbol="BTC/USDT", timeframe="1h",
            start=date(2025, 4, 1), end=date(2025, 4, 1),  # zero-width
            root=tmp_path,
        )
    )
    # `end` is exclusive at start-of-day, so an end == start gives 0 bars
    assert bars == []


def test_load_bars_misaligned_raises(tmp_path: Path):
    _seed(tmp_path)
    # Corrupt CVD: shift one timestamp
    cp = cvd_parquet_path("BTC/USDT", "1h", root=tmp_path)
    cvd = pd.read_parquet(cp)
    cvd.loc[2, "timestamp"] = pd.Timestamp("2025-04-01 02:30", tz="UTC")
    cvd.to_parquet(cp, index=False)
    with pytest.raises(ValueError, match="alignment"):
        list(
            load_bars(
                symbol="BTC/USDT", timeframe="1h",
                start=date(2025, 4, 1), end=date(2025, 4, 2),
                root=tmp_path,
            )
        )
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/test_loader.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Implement `data/loader.py`**

```python
"""Stream Bar objects by joining OHLCV + CVD parquets on timestamp."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from core.types import Bar
from data.paths import DEFAULT_ROOT, cvd_parquet_path, ohlcv_csv_path


def _to_utc_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def load_bars(
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    root: Path = DEFAULT_ROOT,
) -> Iterator[Bar]:
    """Yield `Bar` for `[start, end)` (UTC, end-exclusive at start-of-day).

    Both files must exist and have matching timestamps within the window.
    Misalignment raises `ValueError` to surface bugs in the data pipeline.
    """
    ohlcv_path = ohlcv_csv_path(symbol, timeframe, root=root)
    cvd_path = cvd_parquet_path(symbol, timeframe, root=root)
    if not ohlcv_path.exists():
        raise FileNotFoundError(f"OHLCV not found at {ohlcv_path}")
    if not cvd_path.exists():
        raise FileNotFoundError(f"CVD not found at {cvd_path}")

    ohlcv = pd.read_csv(ohlcv_path, parse_dates=["timestamp"])
    if ohlcv["timestamp"].dt.tz is None:
        ohlcv["timestamp"] = ohlcv["timestamp"].dt.tz_localize("UTC")
    cvd = pd.read_parquet(cvd_path)
    if cvd["timestamp"].dt.tz is None:
        cvd["timestamp"] = cvd["timestamp"].dt.tz_localize("UTC")

    start_ts = pd.Timestamp(_to_utc_dt(start))
    end_ts = pd.Timestamp(_to_utc_dt(end))
    ohlcv = ohlcv[(ohlcv["timestamp"] >= start_ts) & (ohlcv["timestamp"] < end_ts)].reset_index(drop=True)
    cvd = cvd[(cvd["timestamp"] >= start_ts) & (cvd["timestamp"] < end_ts)].reset_index(drop=True)

    if len(ohlcv) == 0:
        return

    if len(ohlcv) != len(cvd) or not (ohlcv["timestamp"].values == cvd["timestamp"].values).all():
        raise ValueError(
            f"OHLCV/CVD alignment failure for {symbol} {timeframe} "
            f"in [{start}, {end}): rows {len(ohlcv)} vs {len(cvd)}"
        )

    merged = ohlcv.merge(cvd, on="timestamp", how="inner")
    for row in merged.itertuples(index=False):
        yield Bar(
            timestamp=row.timestamp.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
            taker_buy_volume=float(row.taker_buy_volume),
            cvd=float(row.cvd),
            cvd_delta=float(row.cvd_delta),
        )
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest tests/test_loader.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Update `data/cvd.py` to also emit `taker_buy_volume`** so the loader's expectation holds end-to-end.

Edit `data/cvd.py`'s `aggregate_cvd` to add a `taker_buy_volume` column. Replace the function body's last block:

```python
    df["buy_qty"] = df["qty"].where(~df["is_buyer_maker"], 0.0)
    grouped_signed = (
        df.set_index("timestamp")["signed_qty"]
        .resample(_TF_TO_PANDAS[timeframe], label="left", closed="left")
        .sum()
        .rename("cvd_delta")
    )
    grouped_buy = (
        df.set_index("timestamp")["buy_qty"]
        .resample(_TF_TO_PANDAS[timeframe], label="left", closed="left")
        .sum()
        .rename("taker_buy_volume")
    )
    out = pd.concat([grouped_signed, grouped_buy], axis=1)
    out["cvd"] = out["cvd_delta"].cumsum()
    return out.reset_index()[["timestamp", "cvd_delta", "cvd", "taker_buy_volume"]]
```

Then update `tests/test_cvd.py` `test_cvd_basic_aggregation` to assert the new column:

```python
    assert list(out.columns) == ["timestamp", "cvd_delta", "cvd", "taker_buy_volume"]
    np.testing.assert_array_equal(out["taker_buy_volume"].values, [10.0, 8.0])
```

And update `test_cvd_empty_input`:

```python
    assert list(out.columns) == ["timestamp", "cvd_delta", "cvd", "taker_buy_volume"]
```

Apply the matching change in `data/cvd.py`'s empty-DataFrame return:

```python
        return pd.DataFrame(columns=["timestamp", "cvd_delta", "cvd", "taker_buy_volume"])
```

- [ ] **Step 6: Run all data + indicator tests**

Run: `pytest tests/test_cvd.py tests/test_loader.py tests/test_indicators.py -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add data/loader.py data/cvd.py tests/test_loader.py tests/test_cvd.py
git commit -m "feat(data): bar loader + extend CVD with taker_buy_volume"
```

---

## Task 15: End-to-end smoke test against live Binance (small slice)

This is the only test that hits the network. It is `pytest`-skipped by default and only runs when `RUN_LIVE_TESTS=1` is set. It serves as the final verification that the whole pipeline (download → aggregate → load) works on real data.

**Files:**
- Create: `tests/test_live_smoke.py`

- [ ] **Step 1: Write the test**

```python
"""Live network smoke test. Skipped unless RUN_LIVE_TESTS=1.

Downloads ~6 hours of BTC/USDT 1h OHLCV + aggTrades, aggregates CVD,
and iterates the resulting bars. ~few MB of network, ~30 s runtime.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import ccxt
import pytest

from data.cvd import aggregate_cvd
from data.downloader import download_aggtrades, download_ohlcv
from data.loader import load_bars
from data.paths import aggtrades_parquet_path, cvd_parquet_path

import pandas as pd

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="set RUN_LIVE_TESTS=1 to enable",
)


def test_pipeline_end_to_end(tmp_path: Path):
    symbol, tf = "BTC/USDT", "1h"
    start, end = date(2025, 1, 1), date(2025, 1, 2)
    ex = ccxt.binance()

    download_ohlcv(symbol, tf, start, end, exchange=ex, root=tmp_path)
    download_aggtrades(symbol, start, end, root=tmp_path)

    trades = pd.read_parquet(aggtrades_parquet_path(symbol, root=tmp_path))
    cvd_df = aggregate_cvd(trades, timeframe=tf)
    cvd_df.to_parquet(cvd_parquet_path(symbol, tf, root=tmp_path), index=False)

    bars = list(load_bars(symbol, tf, start, end, root=tmp_path))
    assert len(bars) == 24
    assert bars[0].close > 0
    assert bars[-1].cvd != 0  # at least some flow
```

- [ ] **Step 2: Run mocked tests; live test should be skipped**

Run: `pytest -v`
Expected: all unit tests pass; `test_pipeline_end_to_end` shows as `SKIPPED`.

- [ ] **Step 3: (Optional, manual) Run the live test once to verify**

Run (PowerShell):
```powershell
$env:RUN_LIVE_TESTS = "1"
pytest tests/test_live_smoke.py -v
$env:RUN_LIVE_TESTS = $null
```
Expected: `1 passed` after ~30 s. If Binance rate-limits or you're behind a strict firewall, the test will fail with an HTTP error — that's a network/environment issue, not a code defect.

- [ ] **Step 4: Commit**

```bash
git add tests/test_live_smoke.py
git commit -m "test: end-to-end pipeline smoke (live, opt-in via RUN_LIVE_TESTS)"
```

---

## Task 16: Final coverage check + doc sync

**Files:**
- Modify: `README.md` (create if missing) — list what sub-plan A delivers and what the next step is.

- [ ] **Step 1: Run full test suite with coverage**

Run: `pytest --cov=core --cov=data --cov=indicators --cov-report=term-missing`
Expected: ≥70% line coverage on `core/`, `data/`, `indicators/`.

- [ ] **Step 2: Write `README.md`**

```markdown
# seminar-ada

Comparative analysis of heuristic vs cognitive multi-agent crypto trading systems.

## Status

**Sub-plan A complete:** data layer, indicators, config, types.
- Download Binance OHLCV (via ccxt) and aggTrades (via REST), aggregate CVD per bar, stream bars as `core.types.Bar`.
- Vectorized RSI, MACD, ADX, EMA, SuperTrend in `indicators/ta.py`, validated against `pandas-ta`.

**Next:** sub-plan B — execution layer (portfolio, broker, metrics) + traditional bot + minimal sync engine.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -v
```

## Spec

- English: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.en.md`
- Indonesian: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.id.md`

## Plans

- Sub-plan A: `docs/superpowers/plans/2026-05-13-sub-plan-A-data-and-indicators.md` (this)
- Sub-plans B/C/D: TBD after A merges.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README reflecting sub-plan A completion"
```

---

## Self-review (writing-plans skill checklist)

**1. Spec coverage (sub-plan A scope only — §13 steps 1–3):**
- ✅ Project scaffolding → Tasks 1–3
- ✅ `core/types.py` → Task 4
- ✅ `core/config.py` → Task 5 (spec doesn't list this explicitly but every later task needs it — added inside scope)
- ✅ `data/loader.py`, `data/downloader.py`, `data/cvd.py` → Tasks 11–14
- ✅ `indicators/ta.py` (RSI, MACD, ADX, EMA, SuperTrend) → Tasks 6–10
- ✅ Tests for indicators + data layer → §11 satisfied for this scope
- 🅾️ Sub-plans B/C/D — explicitly out of scope, will be written separately.

**2. Placeholder scan:** No "TBD"/"implement later"/"add appropriate handling" — every step has runnable code or an exact command.

**3. Type consistency:**
- `Bar` field names match across Tasks 4, 13, 14 (cvd, cvd_delta, taker_buy_volume).
- `aggregate_cvd` return columns match between Tasks 13 (initial) and 14 step 5 (extended) — explicit migration step included.
- `load_bars` signature matches usage in Task 15.
- `download_aggtrades` `agg_id` schema consistent across Tasks 12, 13, 15.

Plan is self-consistent.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-sub-plan-A-data-and-indicators.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with isolated context per task. Best for a 16-task plan: avoids context bloat.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batched checkpoints for review.

After sub-plan A is merged and you're happy, I'll write sub-plan B (execution + traditional bot), then C (LLM agents + cache), then D (async engine + TUI + walk-forward).

**Which execution approach do you want for sub-plan A?**
