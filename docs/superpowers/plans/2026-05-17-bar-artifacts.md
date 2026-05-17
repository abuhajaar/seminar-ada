# Bar Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Post-execution divergence note (2026-05-17):** examples in this plan use a fixed 4-digit width (`0001`..`0480`) for illustration. The shipped implementation uses `len(str(total_bars))` digits (so a 480-bar run produces `001`..`480`, a 65-bar run produces `01`..`65`). See `docs/bar_artifacts.md` for the canonical user-facing spec.

**Goal:** Capture, for every single bar in a backtest, a self-contained folder holding every input the strategies saw and every output they emitted — so each candle decision can be audited, replayed, and presented as a one-page exhibit.

**Architecture:**
- Numbered per-bar folders under `results/runs/<run_id>/<symbol>/bars/<NNNN>/`. Width zero-padded to fit the run (`config.run.start`–`end` × timeframe → bar count).
- Two writer surfaces:
  - **Traditional strategy:** indicator values in + signal out — pure JSON, written by the strategy itself when an artifact path is supplied.
  - **LLM strategy:** four node inputs (rendered prompts + chart PNG) and four node outputs (parsed AgentReport JSONs) plus the final decision — written by a thin `RecordingClient` decorator around the existing `LLMClient`, plus a small hook in `LLMAgentStrategy` for the chart PNG and decision.
- Activation is a single config flag `run.dump_bar_artifacts: false` (default off). On for the seminar demo, off for tests and long runs.
- Bar index and artifact directory ride on `strategies.base.Context` so neither the engine nor strategies need new positional arguments.

**Tech Stack:** Python 3.13, pandas (already in use), stdlib `json` + `base64` + `pathlib`. No new third-party deps.

---

## File Structure

**Create:**
- `core/bar_artifacts.py` — `BarArtifactSink` (open folder, write helpers) and `bar_folder_name(index, total)` (zero-padded naming).
- `llm/recording.py` — `RecordingClient` decorator (wraps any `LLMClient`, intercepts `complete()`, writes `<agent>_input.txt` and `<agent>_output.json` into the current sink).
- `tests/test_bar_artifacts.py` — unit tests for the sink and naming.
- `tests/test_recording_client.py` — unit tests for the decorator (delegation, write side-effects, no-sink no-op).

**Modify:**
- `strategies/base.py:16-22` — extend `Context` with two optional fields: `bar_index: int | None`, `artifact_sink: BarArtifactSink | None`.
- `core/engine.py:175,186-197` — enumerate the bar stream and, when `run_dir` is provided and `dump_bar_artifacts` is on, build a sink and inject it into both per-leg Contexts.
- `core/engine_sync.py:125` — same wiring as `core/engine.py` (sync path used by some smoke tests).
- `core/walkforward.py` — read `dump_bar_artifacts` flag, propagate down to engine.
- `strategies/traditional.py` — if `ctx.artifact_sink is not None`, dump indicator features (in) and signal (out).
- `strategies/llm_agents/strategy.py` — if `ctx.artifact_sink is not None`: wrap the client in a `RecordingClient` bound to the sink for the duration of this bar, dump the chart PNG, dump the final decision.
- `config.yaml:1-6` — add `run.dump_bar_artifacts: false`.
- `core/config.py` (or wherever run-config is parsed) — surface the new flag.

**No file deleted, no public API broken.** Existing callers see `Context.bar_index = None` and `Context.artifact_sink = None`; everything short-circuits to the current behavior.

---

### Task 1: BarArtifactSink + folder naming

**Files:**
- Create: `core/bar_artifacts.py`
- Test: `tests/test_bar_artifacts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bar_artifacts.py
from pathlib import Path
import json

import pytest

from core.bar_artifacts import BarArtifactSink, bar_folder_name


def test_bar_folder_name_pads_to_total_width():
    assert bar_folder_name(1, total=480) == "0001"
    assert bar_folder_name(480, total=480) == "0480"
    assert bar_folder_name(1, total=9) == "1"
    assert bar_folder_name(1, total=10) == "01"


def test_bar_folder_name_rejects_out_of_range():
    with pytest.raises(ValueError):
        bar_folder_name(0, total=480)
    with pytest.raises(ValueError):
        bar_folder_name(481, total=480)


def test_sink_creates_folder_and_writes_text(tmp_path: Path):
    sink = BarArtifactSink(tmp_path / "bars" / "0001")
    sink.write_text("technical_input.txt", "hello prompt")
    out = tmp_path / "bars" / "0001" / "technical_input.txt"
    assert out.read_text(encoding="utf-8") == "hello prompt"


def test_sink_writes_json(tmp_path: Path):
    sink = BarArtifactSink(tmp_path / "bars" / "0001")
    sink.write_json("output.json", {"action": "BUY", "confidence": 0.7})
    payload = json.loads((tmp_path / "bars" / "0001" / "output.json").read_text(encoding="utf-8"))
    assert payload == {"action": "BUY", "confidence": 0.7}


def test_sink_writes_png_bytes(tmp_path: Path):
    sink = BarArtifactSink(tmp_path / "bars" / "0001")
    # 8-byte PNG signature is enough to verify byte-faithful write
    payload = b"\x89PNG\r\n\x1a\n"
    sink.write_bytes("chart.png", payload)
    out = tmp_path / "bars" / "0001" / "chart.png"
    assert out.read_bytes() == payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bar_artifacts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.bar_artifacts'`.

- [ ] **Step 3: Implement `core/bar_artifacts.py`**

```python
"""Per-bar artifact sink: one folder per candle, plain files inside.

Used by the engine to capture, for every bar processed, the exact inputs
each strategy saw and the exact outputs each strategy produced. Designed
for the seminar demo and post-hoc audit; not on the hot path for production
runs (gated by `run.dump_bar_artifacts`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def bar_folder_name(index: int, *, total: int) -> str:
    """Zero-pad ``index`` to the width of ``total``.

    A 480-bar run yields ``0001`` ... ``0480``. A 10-bar run yields
    ``01`` ... ``10``. A 5-bar run yields ``1`` ... ``5`` (width 1).
    """
    if total < 1:
        raise ValueError(f"total must be >= 1, got {total}")
    if index < 1 or index > total:
        raise ValueError(f"index {index} out of range [1, {total}]")
    width = len(str(total))
    return str(index).zfill(width)


class BarArtifactSink:
    """Owns one bar folder. Writers are explicit (text / json / bytes).

    Folder is created on first write to keep the no-op path (sink built
    but nothing written) cheap.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._ensured = False

    @property
    def folder(self) -> Path:
        return self._folder

    def _ensure(self) -> None:
        if not self._ensured:
            self._folder.mkdir(parents=True, exist_ok=True)
            self._ensured = True

    def write_text(self, name: str, content: str) -> None:
        self._ensure()
        (self._folder / name).write_text(content, encoding="utf-8")

    def write_json(self, name: str, payload: Any) -> None:
        self._ensure()
        (self._folder / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def write_bytes(self, name: str, payload: bytes) -> None:
        self._ensure()
        (self._folder / name).write_bytes(payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bar_artifacts.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add core/bar_artifacts.py tests/test_bar_artifacts.py
git commit -m "feat(core): BarArtifactSink + zero-padded bar folder naming"
```

---

### Task 2: Extend Context with bar_index + sink

**Files:**
- Modify: `strategies/base.py:16-22`
- Test: `tests/test_strategy_base.py` (create if absent, otherwise modify)

- [ ] **Step 1: Check whether a tests/test_strategy_base.py exists**

Run: `Test-Path tests\test_strategy_base.py`

- [ ] **Step 2: Write the failing test**

If the file does not exist, create `tests/test_strategy_base.py`:

```python
from strategies.base import Context


def test_context_optional_artifact_fields_default_none():
    ctx = Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.02, in_position=False)
    assert ctx.bar_index is None
    assert ctx.artifact_sink is None


def test_context_accepts_artifact_fields(tmp_path):
    from core.bar_artifacts import BarArtifactSink

    sink = BarArtifactSink(tmp_path / "0001")
    ctx = Context(
        symbol="BTC/USDT",
        equity=10_000.0,
        risk_pct=0.02,
        in_position=False,
        bar_index=1,
        artifact_sink=sink,
    )
    assert ctx.bar_index == 1
    assert ctx.artifact_sink is sink
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_strategy_base.py -v`
Expected: FAIL — `Context.__init__()` rejects unknown keyword arguments.

- [ ] **Step 4: Extend Context in `strategies/base.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from core.types import Bar, Signal

if TYPE_CHECKING:
    from core.bar_artifacts import BarArtifactSink


@dataclass(frozen=True)
class Context:
    """Per-bar context handed to the strategy."""
    symbol: str
    equity: float
    risk_pct: float
    in_position: bool
    bar_index: int | None = None
    artifact_sink: "BarArtifactSink | None" = None


class Strategy(Protocol):
    async def on_bar(self, bar: Bar, ctx: Context) -> Signal: ...
```

(`TYPE_CHECKING` import keeps the runtime cycle-free; `BarArtifactSink` lives in `core/` and `core/` already imports from `strategies/` via the engine.)

- [ ] **Step 5: Run tests to verify they pass + full suite stays green**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_strategy_base.py -v
.\.venv\Scripts\python.exe -m pytest -q
```
Expected: new tests PASS; full suite still PASS (existing call sites construct `Context` without the new fields, which default to `None`).

- [ ] **Step 6: Commit**

```bash
git add strategies/base.py tests/test_strategy_base.py
git commit -m "feat(strategies): Context carries optional bar_index + artifact_sink"
```

---

### Task 3: RecordingClient decorator

**Files:**
- Create: `llm/recording.py`
- Test: `tests/test_recording_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recording_client.py
import json
from pathlib import Path

import pytest

from core.bar_artifacts import BarArtifactSink
from llm.client import LLMClient, LLMResponse
from llm.recording import RecordingClient


class _StubClient:
    """Minimal stand-in for any LLMClient: returns a canned LLMResponse."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, *, agent: str, prompt: str, image_b64, model, **kwargs):
        self.calls.append({"agent": agent, "prompt": prompt, "image_b64": image_b64, "model": model, **kwargs})
        return LLMResponse(content='{"action": "BUY", "confidence": 0.7, "rationale": "ok"}')


@pytest.mark.asyncio
async def test_recording_client_writes_prompt_and_response(tmp_path: Path):
    inner = _StubClient()
    sink = BarArtifactSink(tmp_path / "0001")
    rec = RecordingClient(inner=inner, sink=sink)
    resp = await rec.complete(
        agent="technical", prompt="HELLO PROMPT", image_b64=None, model="x", bar_ts=1
    )
    assert resp.content.startswith("{")
    assert (tmp_path / "0001" / "technical_input.txt").read_text(encoding="utf-8") == "HELLO PROMPT"
    out = json.loads((tmp_path / "0001" / "technical_output.json").read_text(encoding="utf-8"))
    assert out["raw"].startswith("{")


@pytest.mark.asyncio
async def test_recording_client_writes_image_when_present(tmp_path: Path):
    import base64
    png_bytes = b"\x89PNG\r\n\x1a\nFAKE"
    image_b64 = base64.b64encode(png_bytes).decode("ascii")
    inner = _StubClient()
    sink = BarArtifactSink(tmp_path / "0001")
    rec = RecordingClient(inner=inner, sink=sink)
    await rec.complete(agent="visual", prompt="P", image_b64=image_b64, model="x", bar_ts=1)
    assert (tmp_path / "0001" / "visual_input.png").read_bytes() == png_bytes


@pytest.mark.asyncio
async def test_recording_client_forwards_all_kwargs(tmp_path: Path):
    """bar_ts must be forwarded to inner (CachedClient / BudgetGuardedClient need it)."""
    inner = _StubClient()
    sink = BarArtifactSink(tmp_path / "0001")
    rec = RecordingClient(inner=inner, sink=sink)
    await rec.complete(agent="qabba", prompt="P", image_b64=None, model="m", bar_ts=12345)
    assert inner.calls[0]["bar_ts"] == 12345
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recording_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.recording'`.

- [ ] **Step 3: Implement `llm/recording.py`**

```python
"""Per-bar recording wrapper around any LLMClient.

Decorates `complete()` to dump the rendered prompt (and image, if any) and the
raw response into a `BarArtifactSink`. Intended to wrap the *outermost*
client so every other layer (cache, budget guard, http) still runs unchanged.

Tradeoff: writing on every cache hit too. That is intentional — the seminar
goal is a per-bar exhibit, not a transport log. ~10 small files per bar
across 480 bars is well under any practical filesystem ceiling.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from core.bar_artifacts import BarArtifactSink
from llm.client import LLMClient, LLMResponse


@dataclass
class RecordingClient:
    inner: LLMClient
    sink: BarArtifactSink

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
        **kwargs: Any,
    ) -> LLMResponse:
        # Dump inputs BEFORE the call so a downstream failure still leaves a
        # forensic trace of what the LLM was about to see.
        self.sink.write_text(f"{agent}_input.txt", prompt)
        if image_b64 is not None:
            self.sink.write_bytes(f"{agent}_input.png", base64.b64decode(image_b64))

        resp = await self.inner.complete(
            agent=agent,
            prompt=prompt,
            image_b64=image_b64,
            model=model,
            **kwargs,
        )
        self.sink.write_json(f"{agent}_output.json", {"raw": resp.content})
        return resp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recording_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add llm/recording.py tests/test_recording_client.py
git commit -m "feat(llm): RecordingClient decorator dumps per-bar prompt/response/png"
```

---

### Task 4: Traditional strategy writes its own artifacts

**Files:**
- Modify: `strategies/traditional.py`
- Modify: `tests/test_traditional.py` (extend; do not replace existing tests)

- [ ] **Step 1: Locate the indicator-computation block**

Run: `rg -n "def on_bar" strategies/traditional.py`

Read enough of the surrounding method to find the spot where the indicator dict (the same scalars the LLM strategy passes to the technical agent — `ema_fast`, `ema_slow`, `rsi`, `macd_hist`, `adx`, `cvd`, `cvd_delta`) is assembled and where the final `Signal` is built.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_traditional.py`:

```python
@pytest.mark.asyncio
async def test_traditional_dumps_artifacts_when_sink_provided(tmp_path):
    import json

    from core.bar_artifacts import BarArtifactSink
    from strategies.base import Context
    # ... existing imports for TraditionalStrategy + a synthesized warmup-complete bar series ...

    strat = TraditionalStrategy()  # use defaults
    # feed >= WARMUP_BARS bars first to clear warmup
    # ... build `bars: list[Bar]` of length 60 with rising closes ...
    for b in bars[:-1]:
        await strat.on_bar(b, Context(symbol="BTC/USDT", equity=10000.0, risk_pct=0.02, in_position=False))

    sink = BarArtifactSink(tmp_path / "0060")
    final_bar = bars[-1]
    sig = await strat.on_bar(
        final_bar,
        Context(
            symbol="BTC/USDT",
            equity=10000.0,
            risk_pct=0.02,
            in_position=False,
            bar_index=60,
            artifact_sink=sink,
        ),
    )

    indicators = json.loads((tmp_path / "0060" / "input_indicators.json").read_text(encoding="utf-8"))
    signal = json.loads((tmp_path / "0060" / "output_signal.json").read_text(encoding="utf-8"))
    assert set(indicators.keys()) >= {"ema_fast", "ema_slow", "rsi", "macd_hist", "adx"}
    assert signal["action"] in {"BUY", "SELL", "HOLD"}
    assert signal["action"] == sig.action.value
```

(Replace the `...`-marked placeholder with the same warmup-bar fixture pattern used elsewhere in `tests/test_traditional.py`; do not invent a new fixture style. If you cannot find one, model it on `tests/test_traditional_e2e.py`'s setup.)

- [ ] **Step 3: Run the new test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_traditional.py -v -k artifacts`
Expected: FAIL — files not written.

- [ ] **Step 4: Implement the sink writes in `strategies/traditional.py`**

Inside `on_bar`, **after** the indicator dict is fully populated and **after** the final `Signal` is built, but **before** the `return`, add:

```python
if ctx.artifact_sink is not None:
    ctx.artifact_sink.write_json("input_indicators.json", features)
    ctx.artifact_sink.write_json(
        "output_signal.json",
        {
            "action": signal.action.value,
            "confidence": signal.confidence,
            "reasoning": signal.reasoning,
            "stop_loss": signal.stop_loss,
        },
    )
```

Substitute `features` and `signal` for whatever the real local variable names are in `strategies/traditional.py`. Do not invent fields the existing `Signal` does not have.

- [ ] **Step 5: Run the new test + the full traditional suite**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_traditional.py -v
```
Expected: new test PASS; all existing traditional tests still PASS (sink path is gated on `ctx.artifact_sink is not None`).

- [ ] **Step 6: Commit**

```bash
git add strategies/traditional.py tests/test_traditional.py
git commit -m "feat(strategies): traditional dumps indicators + signal per-bar when sink set"
```

---

### Task 5: LLM strategy writes chart PNG + decision; wraps client per bar

**Files:**
- Modify: `strategies/llm_agents/strategy.py:71-79,153-208`
- Test: `tests/test_llm_strategy.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_strategy.py`:

```python
@pytest.mark.asyncio
async def test_llm_strategy_dumps_artifacts_when_sink_provided(tmp_path):
    import base64
    import json
    from core.bar_artifacts import BarArtifactSink
    from strategies.base import Context

    # Reuse the existing fixture that builds a MockClient + LLMAgentStrategy
    # warmed past WARMUP_BARS with render_image=True. If a helper exists, call
    # it; otherwise replicate the pattern from neighbouring tests verbatim.
    strat, mock_client, bars = _build_warmed_llm_strategy(render_image=True)
    final_bar = bars[-1]
    sink = BarArtifactSink(tmp_path / "0060")

    sig = await strat.on_bar(
        final_bar,
        Context(
            symbol="BTC/USDT",
            equity=10000.0,
            risk_pct=0.02,
            in_position=False,
            bar_index=60,
            artifact_sink=sink,
        ),
    )

    folder = tmp_path / "0060"
    # Three analyst nodes each wrote input/output via RecordingClient:
    for agent in ("technical", "visual", "qabba"):
        assert (folder / f"{agent}_input.txt").exists()
        assert (folder / f"{agent}_output.json").exists()
    # Decision node does no LLM call (pure consensus math), so we write its
    # final decision separately:
    decision = json.loads((folder / "decision_output.json").read_text(encoding="utf-8"))
    assert decision["action"] == sig.action.value
    # Chart PNG written by the strategy (not by RecordingClient — strategy
    # owns the render output):
    chart = folder / "chart.png"
    assert chart.exists() and chart.stat().st_size > 0
```

If `_build_warmed_llm_strategy` does not already exist, create it next to the other helpers in `tests/test_llm_strategy.py`. Do not stub `render_chart`; let it produce real bytes — `mplfinance` is already a hard test dep.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_llm_strategy.py -v -k artifacts`
Expected: FAIL — files not written.

- [ ] **Step 3: Modify `strategies/llm_agents/strategy.py`**

Two changes inside `on_bar`. First, **after** `image_b64` is assigned (around the current line 156) and **before** the graph invocation, write the chart PNG if both a sink and a render exist:

```python
if ctx.artifact_sink is not None and image_b64 is not None:
    import base64 as _b64
    ctx.artifact_sink.write_bytes("chart.png", _b64.b64decode(image_b64))
```

Second, **before** building `initial` and calling `self._graph.ainvoke`, swap the client for a `RecordingClient` for the duration of this bar so each analyst node's prompt + response lands in the sink. The graph is built once in `__post_init__` with the raw client baked in via `functools.partial`, so we cannot rewire the compiled graph at this point. Instead, rebuild the graph per-bar **only when** a sink is active. Performance is acceptable: `build_graph` is pure-python and microsecond-scale; we only do it when artifacts are being dumped.

```python
graph = self._graph
if ctx.artifact_sink is not None:
    from llm.recording import RecordingClient

    recording_client = RecordingClient(inner=self.client, sink=ctx.artifact_sink)
    graph = build_graph(
        client=recording_client,
        consensus_weights=self.consensus_weights,
        consensus_threshold=self.consensus_threshold,
    )

final = await graph.ainvoke(initial)
```

(Replace the existing `final = await self._graph.ainvoke(initial)` call site at line 175.)

Third, **after** `d = final["decision"]` and after the regime-gate / stop-loss block, but **before** the function returns, dump the decision:

```python
if ctx.artifact_sink is not None:
    ctx.artifact_sink.write_json(
        "decision_output.json",
        {
            "action": d.action.value,
            "confidence": d.confidence,
            "rationale": d.rationale,
            "regime_gate_st_dir": st_dir,
        },
    )
```

- [ ] **Step 4: Add `from strategies.llm_agents.graph import build_graph` at the top of the file**

It is already imported at line 28 — confirm with `rg -n "build_graph" strategies/llm_agents/strategy.py`. If missing, add it.

- [ ] **Step 5: Run the test to verify it passes + full llm suite stays green**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_llm_strategy.py -v
```
Expected: new test PASS; existing tests PASS (gated on `ctx.artifact_sink is not None`, so `None`-path is unchanged).

- [ ] **Step 6: Commit**

```bash
git add strategies/llm_agents/strategy.py tests/test_llm_strategy.py
git commit -m "feat(llm): per-bar chart.png + recording client + decision dump"
```

---

### Task 6: Engine wires bar index + sink into Context

**Files:**
- Modify: `core/engine.py:175,186-197`
- Modify: `core/engine_sync.py:125`
- Test: `tests/test_engine.py` (extend)

- [ ] **Step 1: Read the current engine bar loop**

Run: `rg -n "for bar in bars" core/`. Open each match and identify (a) the bar enumeration site, (b) where `Context` is constructed per leg.

- [ ] **Step 2: Write the failing test (async engine)**

Append to `tests/test_engine.py`:

```python
@pytest.mark.asyncio
async def test_engine_wires_artifact_sink_when_run_dir_set(tmp_path):
    # Build a tiny synthetic bar stream of length 65 (just past WARMUP_BARS=60)
    # plus a MockClient-backed LLMAgentStrategy. Reuse helpers from
    # tests/test_engine.py — do not redefine fixtures.

    bars = _synthetic_bars(n=65)
    trad = TraditionalStrategy()
    llm = _build_llm_strategy_with_mock_client(render_image=True)

    run_dir = tmp_path / "run"
    await engine.run_async(
        bars=iter(bars),
        trad_strategy=trad,
        llm_strategy=llm,
        symbol="BTC/USDT",
        initial_balance=10000.0,
        taker_fee_bps=4.0,
        slippage_bps=2.0,
        risk_pct=0.02,
        run_state=None,
        artifact_root=run_dir / "BTCUSDT" / "bars",
        total_bars=65,
    )

    # Spot-check: bar 0001 exists with the traditional indicator dump
    assert (run_dir / "BTCUSDT" / "bars" / "01" / "input_indicators.json").exists()
    # Bar 65 exists with the LLM decision dump
    assert (run_dir / "BTCUSDT" / "bars" / "65" / "decision_output.json").exists()
```

(Pad width = `len(str(65))` = 2 in this fixture.)

- [ ] **Step 3: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_engine.py -v -k artifact_sink`
Expected: FAIL — `engine.run_async` rejects the new `artifact_root` / `total_bars` keyword arguments.

- [ ] **Step 4: Modify `core/engine.py` to accept `artifact_root` + `total_bars`**

Add two optional parameters to `run_async`:

```python
async def run_async(
    *,
    bars,
    trad_strategy,
    llm_strategy,
    symbol,
    initial_balance,
    taker_fee_bps,
    slippage_bps,
    risk_pct,
    run_state=None,
    artifact_root: Path | None = None,
    total_bars: int | None = None,
):
```

Replace the bar loop header at line 175:

```python
for bar_idx, bar in enumerate(bars, start=1):
```

When constructing the two per-leg Contexts (around lines 186-197), build the two sinks if `artifact_root` is set and `total_bars` is set, and inject them:

```python
trad_sink = None
llm_sink = None
if artifact_root is not None and total_bars is not None:
    from core.bar_artifacts import BarArtifactSink, bar_folder_name

    folder = artifact_root / bar_folder_name(bar_idx, total=total_bars)
    # Both legs share the same bar folder. Traditional writes
    # input_indicators.json / output_signal.json; LLM writes chart.png /
    # <agent>_input/output / decision_output.json. Names don't collide.
    trad_sink = BarArtifactSink(folder)
    llm_sink = BarArtifactSink(folder)

ctx_trad = Context(
    symbol=symbol,
    equity=portfolio_trad.equity(mark_price=bar.close),
    risk_pct=risk_pct,
    in_position=portfolio_trad.position is not None,
    bar_index=bar_idx,
    artifact_sink=trad_sink,
)
ctx_llm = Context(
    symbol=symbol,
    equity=portfolio_llm.equity(mark_price=bar.close),
    risk_pct=risk_pct,
    in_position=portfolio_llm.position is not None,
    bar_index=bar_idx,
    artifact_sink=llm_sink,
)
```

- [ ] **Step 5: Mirror the change in `core/engine_sync.py`**

The sync engine has the same `for bar in bars:` shape (around line 125). Apply the same two optional kwargs, the same enumeration, the same sink construction and Context injection. The signature change is identical.

- [ ] **Step 6: Run engine tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_engine.py tests/test_engine_sync.py -v`
Expected: new artifact-sink test PASS; existing tests still PASS (new kwargs default to `None`).

- [ ] **Step 7: Commit**

```bash
git add core/engine.py core/engine_sync.py tests/test_engine.py
git commit -m "feat(engine): per-bar artifact sink wired through Context"
```

---

### Task 7: Config flag + walkforward propagation

**Files:**
- Modify: `config.yaml:1-6`
- Modify: `core/config.py` (or wherever `run.*` is parsed; locate with `rg -n "initial_balance" core/config.py`)
- Modify: `core/walkforward.py:106-116,152-158`
- Test: `tests/test_walkforward.py`

- [ ] **Step 1: Add the flag with default off**

Edit `config.yaml`:

```yaml
run:
  assets: [BTC/USDT]
  timeframe: 15m
  start: 2025-04-10
  end:   2025-04-15
  initial_balance: 10000
  dump_bar_artifacts: false
```

- [ ] **Step 2: Locate the run-config parser**

Run: `rg -n "initial_balance" core/config.py`. Add a parallel `dump_bar_artifacts: bool` field defaulting to `False`. If the parser uses pydantic / dataclass / TypedDict, follow the existing style — do not invent a new one.

- [ ] **Step 3: Write the failing test**

Append to `tests/test_walkforward.py`:

```python
@pytest.mark.asyncio
async def test_walkforward_writes_bar_artifacts_when_flag_on(tmp_path):
    # Reuse the existing walkforward fixture that builds a MockClient run
    # with a synthetic 65-bar OHLCV+CVD pair. Pass dump_bar_artifacts=True
    # through whatever the walkforward signature exposes (likely a kwarg
    # added in this task).
    results = await walkforward.run(
        ...,  # match the existing test_walkforward signature
        out_dir=tmp_path,
        dump_bar_artifacts=True,
    )
    asset_dir = tmp_path / next(iter(results)) / "bars"
    # Width = len(str(total_bars)). For the fixture's 65-bar run, width = 2.
    assert (asset_dir / "01" / "input_indicators.json").exists()
    assert (asset_dir / "65" / "decision_output.json").exists()
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_walkforward.py -v -k artifacts`
Expected: FAIL — `walkforward.run` does not accept `dump_bar_artifacts`.

- [ ] **Step 5: Thread the flag through walkforward**

In `core/walkforward.py`, add a kwarg `dump_bar_artifacts: bool = False` to the public `run` function. Where it currently calls `engine.run_async(...)` (line 106), build `artifact_root` and `total_bars` only if the flag is on:

```python
artifact_root = None
total_bars = None
if dump_bar_artifacts and run_dir is not None:
    artifact_root = run_dir / _safe_symbol(symbol) / "bars"
    total_bars = len(bars)  # bars is already materialised as a list above
trad_port, llm_port, trad_metrics, llm_metrics = await engine.run_async(
    bars=iter(bars),
    ...,
    artifact_root=artifact_root,
    total_bars=total_bars,
)
```

(`len(bars)` works only if `bars` is materialised before the call. If it is currently a generator, materialise it: `bars = list(bars)`. The walkforward already has the full bar list in memory in practice — verify.)

- [ ] **Step 6: Wire the config flag at the call site**

Find where `walkforward.run` is invoked (`rg -n "walkforward.run" .` — likely in `main.py` or `scripts/`). Read `cfg.run.dump_bar_artifacts` and forward it as the kwarg.

- [ ] **Step 7: Run the test to verify it passes + full suite**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add config.yaml core/config.py core/walkforward.py tests/test_walkforward.py main.py
git commit -m "feat(walkforward): dump_bar_artifacts flag threads sinks per bar"
```

(Drop any of the listed files from `git add` that you didn't actually need to modify.)

---

### Task 8: Documentation + seminar wiring

**Files:**
- Create: `docs/bar_artifacts.md`
- Modify: `presentation/demo_cheatsheet.md`
- Modify: `presentation/script_en.md` (Section 6 — demo) and `presentation/script_id.md` (Bagian 6)

- [ ] **Step 1: Write `docs/bar_artifacts.md`**

Content (no placeholders):

```markdown
# Per-Bar Artifacts

Set `run.dump_bar_artifacts: true` in `config.yaml`. After a run, every
candle that the engine processed has its own folder under
`results/runs/<RUN_ID>/<SAFE_SYMBOL>/bars/<NNNN>/` containing:

| File                       | Source              | What it is                                     |
|----------------------------|---------------------|------------------------------------------------|
| `input_indicators.json`    | Traditional bot     | Indicator scalars fed into the SuperTrend rule |
| `output_signal.json`       | Traditional bot     | Final Action / confidence / reasoning / stop   |
| `chart.png`                | LLM bot (Visual)    | The exact candlestick image the Visual agent saw |
| `technical_input.txt`      | LLM bot (Technical) | Rendered prompt sent to the technical analyst  |
| `technical_output.json`    | LLM bot (Technical) | Raw response text from the analyst             |
| `visual_input.txt`         | LLM bot (Visual)    | Rendered prompt sent to the visual analyst     |
| `visual_input.png`         | LLM bot (Visual)    | Same as `chart.png` (kept beside its prompt)   |
| `visual_output.json`       | LLM bot (Visual)    | Raw response text                              |
| `qabba_input.txt`          | LLM bot (QABBA)     | Rendered prompt for the QABBA analyst          |
| `qabba_output.json`        | LLM bot (QABBA)     | Raw response text                              |
| `decision_output.json`     | LLM bot (Decision)  | Final action + confidence + regime-gate state  |

Folder numbering is 1-based and zero-padded to the width of the total bar
count for the run (a 480-bar run uses `0001` ... `0480`). Bars dropped during
warmup or by the NaN guard still get a folder — the indicator file contains
the partial scalars, and the LLM files are absent because the graph was not
invoked.
```

- [ ] **Step 2: Add the toggle to `presentation/demo_cheatsheet.md`**

Append a "Bar artifacts" bullet describing the flag, where the files land, and one suggested command to open a specific bar (e.g. `explorer.exe results\runs\<id>\BTCUSDT\bars\0123`).

- [ ] **Step 3: Mention the artifact folder in the seminar demo section**

In `presentation/script_en.md` Section 6 (demo), add one sentence near the candlestick rendering moment: "Every candle leaves a folder behind — prompt, chart, response, decision — so anyone can audit one decision end to end."

Mirror in `presentation/script_id.md` Bagian 6 in conversational-akademik tone.

- [ ] **Step 4: Commit**

```bash
git add docs/bar_artifacts.md presentation/demo_cheatsheet.md presentation/script_en.md presentation/script_id.md
git commit -m "docs(seminar): document per-bar artifact folders + demo callout"
```

---

### Task 9: End-to-end smoke

**Files:** none new — just exercising the flag against the real cached run.

- [ ] **Step 1: Enable the flag**

Edit `config.yaml`: set `run.dump_bar_artifacts: true`.

- [ ] **Step 2: Run the cached demo**

Run:
```powershell
.\.venv\Scripts\python.exe main.py
```

Expected: the run completes against cached LLM responses (no OpenRouter calls) and a `results/runs/<ID>/BTCUSDT/bars/` folder appears with `<total_bars>` numbered subfolders.

- [ ] **Step 3: Inspect one folder**

Run:
```powershell
Get-ChildItem "results\runs\<ID>\BTCUSDT\bars\0123\"
```

Expected: at least `input_indicators.json`, `output_signal.json`, `decision_output.json`, `chart.png`, and the three `<agent>_input.txt` + `<agent>_output.json` pairs.

- [ ] **Step 4: Revert the flag (or leave it on for the seminar)**

If the seminar run is the next intended invocation, leave `dump_bar_artifacts: true`. Otherwise revert and commit the toggle separately.

- [ ] **Step 5: Final commit if the artifact folder is to be checked in**

The per-bar folders are large; check the existing `.gitignore` for `results/`. If `results/` is gitignored, nothing to commit. If it is tracked, decide per-run whether the artifacts are committed alongside `summary.json` or stripped.

---

## Self-Review

**Spec coverage:**
- "Folder per bar, numbered 1..N" → Task 1 (`bar_folder_name`), Task 6 (engine wires per-bar sinks).
- "Input data the LLM received" → Task 3 (RecordingClient writes `<agent>_input.txt`/`.png`), Task 5 (chart.png).
- "Output data the LLM returned" → Task 3 (`<agent>_output.json`), Task 5 (`decision_output.json`).
- "If input is a PNG, the folder must contain the PNG" → Task 3 writes `visual_input.png`; Task 5 writes `chart.png` from the strategy side as well.
- "Tied to config (480 bars in the BTC/USDT 15m 5-day case)" → Task 7 (`run.dump_bar_artifacts`), Task 1 (folder width derives from `total_bars`).
- Traditional strategy parity (so the audit covers both bots, not just the LLM) → Task 4.

**Placeholders:** Two intentional `...` placeholders remain in tests for fixture reuse (Task 4 Step 2, Task 5 Step 1, Task 6 Step 2, Task 7 Step 3). Each is paired with an explicit instruction to reuse existing fixture helpers rather than invent new ones — that is the design intent, not a TBD.

**Type consistency:**
- `BarArtifactSink` constructor takes `Path`; same type used everywhere it is constructed.
- `Context.artifact_sink: BarArtifactSink | None` matches Task 1's class name.
- `Context.bar_index: int | None` matches the engine's `enumerate(..., start=1)` output type.
- `engine.run_async` new kwargs (`artifact_root: Path | None`, `total_bars: int | None`) match `BarArtifactSink` + `bar_folder_name` signatures.
- `RecordingClient.complete` signature matches `LLMClient.complete` (kwargs-only, forwards `**kwargs` for `bar_ts`).

**Risk notes:**
- Per-bar `build_graph` rebuild (Task 5) only fires when a sink is active — production runs are unaffected. Cost: microseconds per bar.
- Sink files for warmup bars: `input_indicators.json` may contain NaN scalars. JSON encoder may need `default=str` (already in `BarArtifactSink.write_json`).
- `BTCUSDT_15m` for 5 days = 480 bars × ~10 small files = ~4,800 files. `mkdir` × 480 is cheap; total disk ~50 MB dominated by 480 chart PNGs (~100 KB each).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-bar-artifacts.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review. Recommended because Tasks 4-7 each touch existing test fixtures and benefit from a clean-context reviewer.
2. **Inline Execution** — batch tasks 1-9 with checkpoints in this session.
