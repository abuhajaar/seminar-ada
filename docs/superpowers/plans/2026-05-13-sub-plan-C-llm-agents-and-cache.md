# Sub-Plan C: LLM Agents, Caching, Budget Guard + LangGraph Wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LLM-driven half of the comparative backtest: an `LLMClient` protocol with two implementations (`OpenRouterClient`, `MockClient`), a bar-keyed JSON cache decorator (`CachedClient`), a budget guard with per-run USD cap, mplfinance chart rendering, four agent nodes (Technical, Visual, QABBA, Decision), a fully-wired LangGraph `StateGraph`, and an `LLMAgentStrategy` that conforms to the existing `Strategy` protocol from sub-plan B. The graph is tested standalone with synthetic bars and `MockClient` so sub-plan D only has to plug it into the async engine.

**Architecture:**
- Per bar, the strategy builds a small feature dict (latest EMA/RSI/MACD/CVD values + recent OHLCV window) and a base64-encoded PNG candlestick chart, then invokes the LangGraph.
- The graph fans out to three analyst nodes in parallel (Technical / Visual / QABBA), each calling `LLMClient.complete(...)` with a temperature-0 model. Each returns an `AgentReport(action, confidence, rationale)`.
- The Decision node first applies the **deterministic weighted-consensus guardrail** (spec §7.2: `0.40·QABBA + 0.35·Visual + 0.25·Technical`); if `buy_score > 0.50` and `> sell_score` → BUY, mirror for SELL, else HOLD. The LLM Decision call is optional and only logs disagreement — math always wins.
- Every LLM call goes through `CachedClient`, which keys on `(model, agent, prompt_hash, image_hash, bar_ts)` per spec Q2. Cached runs make **zero** API calls and are deterministic + free for the seminar replay.
- `BudgetGuard` tracks cumulative USD spend; pre-call estimate refuses calls that would breach the per-run cap (default $1.00). `MockClient` bypasses the budget entirely (it has no cost).

**Tech Stack:**
- New runtime deps (added to `pyproject.toml`): `langgraph>=0.2`, `langchain-core>=0.3`, `httpx>=0.27`, `mplfinance>=0.12`, `pillow>=10`.
- Already present: `pandas`, `numpy`, `pydantic`, `pytest`, `pytest-asyncio`.
- All LLM calls are async (`async def complete(...)`), even in `MockClient` (returns immediately) — this keeps the strategy interface uniform and ready for sub-plan D's async engine.

**Status of prerequisites:**
- Sub-plan A complete: data loader, CVD, indicators (EMA/RSI/MACD/ADX/SuperTrend), 32 tests.
- Sub-plan B complete: `Strategy` protocol, `Context`, `Signal`, `Order`, `Portfolio`, `Broker`, `Metrics`, `engine_sync`, `TraditionalStrategy`. 80 passed + 1 skipped, 97% coverage.
- `core/types.py` already defines `AgentReport(action, confidence, rationale)` — reused as-is.

---

## Scope checklist (spec sections this plan implements)

- §6: cache directory layout `cache/llm/<model>/<agent>/<bar_ts>.json`.
- §7: LangGraph topology START → {Technical, Visual, QABBA} → Decision → END, with deterministic weighted-consensus guardrail in Decision node.
- §7.2: weighted consensus formula and HOLD fallback.
- §9: per-run budget cap (USD) with pre-call estimate + `BudgetExceededError`.
- §10: `llm.*` config keys (`model`, `temperature=0`, `cache_dir`, `budget_usd`, `mock`, `image_window_bars`).
- §11 test rows: cache hit returns identical payload; budget cap raises before HTTP call; Decision guardrail overrides LLM disagreement; graph wiring round-trip with `MockClient`.
- Q2: bar-keyed cache, image hash included in key.

Out of scope (deferred to sub-plan D):
- Async engine integration / `asyncio.gather` over bars.
- Rich TUI per-agent panel.
- Walk-forward over multiple assets.

---

## File structure produced by this plan

```
llm/
├── __init__.py           # NEW (empty)
├── client.py             # NEW: LLMClient Protocol, OpenRouterClient, MockClient, LLMResponse
├── cache.py              # NEW: CachedClient decorator + key hashing
└── budget.py             # NEW: BudgetGuard, BudgetExceededError, cost estimator
strategies/
└── llm_agents/
    ├── __init__.py       # NEW (empty)
    ├── state.py          # NEW: GraphState TypedDict
    ├── prompts.py        # NEW: prompt templates for the 4 agents
    ├── chart.py          # NEW: render_chart(bars) -> base64 PNG via mplfinance
    ├── nodes/
    │   ├── __init__.py   # NEW (empty)
    │   ├── technical.py  # NEW: technical_node(state, client) -> state
    │   ├── visual.py     # NEW: visual_node(state, client) -> state
    │   ├── qabba.py      # NEW: qabba_node(state, client) -> state
    │   └── decision.py   # NEW: decision_node(state) -> state (deterministic guardrail)
    ├── graph.py          # NEW: build_graph(client) -> compiled LangGraph
    └── strategy.py       # NEW: LLMAgentStrategy implementing Strategy protocol
cache/
└── llm/                  # NEW directory, .gitkeep committed
tests/
├── test_llm_client.py        # NEW: MockClient deterministic output, OpenRouterClient HTTP mocked
├── test_llm_cache.py         # NEW: cache hit/miss, key stability, image hash
├── test_llm_budget.py        # NEW: pre-call estimate, BudgetExceededError, MockClient bypass
├── test_llm_chart.py         # NEW: render_chart returns valid base64 PNG header
├── test_llm_nodes.py         # NEW: each node round-trips state with MockClient
├── test_llm_decision.py      # NEW: guardrail formula edge cases (HOLD ties, LLM override ignored)
├── test_llm_graph.py         # NEW: build_graph(MockClient) end-to-end on a synthetic bar
└── test_llm_strategy.py      # NEW: LLMAgentStrategy.generate_signal returns Signal
```

Also modified:
- `pyproject.toml`: add `langgraph`, `langchain-core`, `httpx`, `mplfinance`, `pillow`.
- `core/config.py`: add `LLMConfig` section (`model`, `temperature`, `cache_dir`, `budget_usd`, `mock`, `image_window_bars`).
- `config.yaml`: add `llm:` block with seminar defaults.
- `.gitignore`: ensure `cache/llm/*.json` is **NOT** ignored (must commit for replay); ignore `cache/llm/__pycache__` only.
- `README.md`: bilingual section explaining cache replay + budget guard.

---

## Task 1: Add `temperature=0` invariant to existing `AgentCfg`

> **Plan note:** `core/config.py` already defines `LlmCfg` and `AgentCfg` matching the spec (cache_dir, max_usd, per-agent model+temperature, consensus_weights summing to 1.0, consensus_threshold). `config.yaml` already has the full `llm:` block with the spec §7.2 weights (qabba 0.40 / visual 0.35 / technical 0.25) and threshold 0.50. **Task 1 is therefore much smaller than originally drafted**: add a `temperature == 0` validator to `AgentCfg` so the determinism invariant from spec Q2 is enforced. Also add `mock: bool = False` and `image_window_bars: int = 60` fields to `LlmCfg` for runtime use by sub-plan D, since they have no current home.

**Files:**
- Modify: `core/config.py`
- Modify: `config.yaml` (add `mock: false` and `image_window_bars: 60`)
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add failing tests in `tests/test_config.py`**

```python
def test_agent_cfg_rejects_nonzero_temperature():
    """Spec Q2 mandates temperature=0 for deterministic backtests."""
    import pytest
    from pydantic import ValidationError
    from core.config import AgentCfg

    with pytest.raises(ValidationError):
        AgentCfg(model="anthropic/claude-3.5-sonnet", temperature=0.7)


def test_agent_cfg_accepts_zero_temperature():
    from core.config import AgentCfg
    a = AgentCfg(model="anthropic/claude-3.5-sonnet", temperature=0.0)
    assert a.temperature == 0.0


def test_llm_cfg_has_mock_and_image_window_defaults(tmp_path):
    from core.config import load_config
    cfg = load_config("config.yaml")
    assert cfg.llm.mock is False
    assert cfg.llm.image_window_bars == 60
```

Run: `.\.venv\Scripts\pytest tests\test_config.py -x` — must FAIL.

- [ ] **Step 2: Modify `AgentCfg` in `core/config.py`**

Add a `field_validator` on `temperature`:

```python
@field_validator("temperature")
@classmethod
def _temperature_must_be_zero(cls, v: float) -> float:
    if v != 0:
        raise ValueError("LLM temperature must be 0 for deterministic backtests (spec Q2).")
    return v
```

- [ ] **Step 3: Add `mock` and `image_window_bars` to `LlmCfg`**

```python
class LlmCfg(BaseModel):
    cache_dir: str
    max_usd: float
    mock: bool = False
    image_window_bars: int = 60
    agents: dict[str, AgentCfg]
    consensus_weights: dict[str, float]
    consensus_threshold: float
    # ... existing model_validator unchanged
```

- [ ] **Step 4: Update `config.yaml`** — add `mock: false` and `image_window_bars: 60` under the `llm:` block.

- [ ] **Step 5: Run `.\.venv\Scripts\pytest tests\test_config.py -x`** — must PASS, and the full suite (`.\.venv\Scripts\pytest -q`) must still pass.

- [ ] **Commit:** `feat(config): enforce LLM temperature=0 invariant, add mock+image_window_bars`

### Two-stage review

- [ ] Self-review checklist:
  - [ ] `temperature=0.7` raises `ValidationError`.
  - [ ] All other fields have sensible defaults.
  - [ ] No other tests broken: `.\.venv\Scripts\pytest -q`.
- [ ] Dispatch `code-reviewer` subagent (or skill `requesting-code-review`) on the diff for Task 1.

---

## Task 2: `llm/client.py` — `LLMClient` Protocol + `LLMResponse` + `MockClient`

**Files:**
- Create: `llm/__init__.py` (empty)
- Create: `llm/client.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing test `tests/test_llm_client.py`**

```python
import pytest
from core.types import Action
from llm.client import LLMClient, LLMResponse, MockClient


def test_llm_response_is_a_dataclass_with_required_fields():
    r = LLMResponse(content="HOLD 0.5 reason", model="mock", input_tokens=10, output_tokens=5)
    assert r.content == "HOLD 0.5 reason"
    assert r.model == "mock"
    assert r.input_tokens == 10
    assert r.output_tokens == 5


@pytest.mark.asyncio
async def test_mock_client_implements_protocol():
    client: LLMClient = MockClient()
    r = await client.complete(
        agent="technical",
        prompt="features: ema_fast=100 ema_slow=95 rsi=55",
        image_b64=None,
        model="mock",
    )
    assert isinstance(r, LLMResponse)
    assert r.model == "mock"


@pytest.mark.asyncio
async def test_mock_client_technical_buy_on_bullish_ema_cross():
    client = MockClient()
    r = await client.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 rsi=60 macd_hist=0.5",
        image_b64=None,
        model="mock",
    )
    # MockClient is deterministic: bullish features -> BUY
    assert "BUY" in r.content.upper()


@pytest.mark.asyncio
async def test_mock_client_qabba_buy_on_positive_cvd():
    client = MockClient()
    r = await client.complete(
        agent="qabba",
        prompt="cvd_delta=12345.6",
        image_b64=None,
        model="mock",
    )
    assert "BUY" in r.content.upper()


@pytest.mark.asyncio
async def test_mock_client_qabba_sell_on_negative_cvd():
    client = MockClient()
    r = await client.complete(
        agent="qabba",
        prompt="cvd_delta=-9999.0",
        image_b64=None,
        model="mock",
    )
    assert "SELL" in r.content.upper()


@pytest.mark.asyncio
async def test_mock_client_visual_returns_hold_without_image():
    client = MockClient()
    r = await client.complete(
        agent="visual",
        prompt="(no image)",
        image_b64=None,
        model="mock",
    )
    assert "HOLD" in r.content.upper()


@pytest.mark.asyncio
async def test_mock_client_decision_echoes_consensus_from_prompt():
    client = MockClient()
    r = await client.complete(
        agent="decision",
        prompt="tech=BUY:0.7 visual=BUY:0.6 qabba=BUY:0.8",
        image_b64=None,
        model="mock",
    )
    assert "BUY" in r.content.upper()
```

Run: `.\.venv\Scripts\pytest tests\test_llm_client.py -x` — must FAIL (module missing).

- [ ] **Step 2: Implement `llm/client.py`**

```python
"""LLM client protocol and implementations.

`OpenRouterClient` is the real backend (httpx + OpenRouter API).
`MockClient` is a deterministic stand-in derived from prompt features, used for
tests and for seminar replay without spending money. All calls are async.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
    ) -> LLMResponse: ...


_NUM_RE = re.compile(r"(-?\d+\.?\d*)")


def _extract_floats(text: str, key: str) -> float | None:
    """Find `key=<number>` in text; return float or None."""
    pat = re.compile(rf"{re.escape(key)}\s*=\s*(-?\d+\.?\d*)")
    m = pat.search(text)
    return float(m.group(1)) if m else None


class MockClient:
    """Deterministic LLM stand-in keyed off prompt features.

    Technical: BUY if ema_fast>ema_slow AND macd_hist>0, SELL if both reversed, else HOLD.
    QABBA: BUY if cvd_delta>0, SELL if <0, else HOLD.
    Visual: HOLD always (image analysis stubbed; real path needs OpenRouterClient).
    Decision: parse `tech=X:c visual=X:c qabba=X:c` from prompt and majority-vote.
    """

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
    ) -> LLMResponse:
        agent_l = agent.lower()
        action = "HOLD"
        confidence = 0.5

        if agent_l == "technical":
            ema_fast = _extract_floats(prompt, "ema_fast")
            ema_slow = _extract_floats(prompt, "ema_slow")
            macd_hist = _extract_floats(prompt, "macd_hist")
            if ema_fast is not None and ema_slow is not None and macd_hist is not None:
                if ema_fast > ema_slow and macd_hist > 0:
                    action, confidence = "BUY", 0.7
                elif ema_fast < ema_slow and macd_hist < 0:
                    action, confidence = "SELL", 0.7
        elif agent_l == "qabba":
            cvd = _extract_floats(prompt, "cvd_delta")
            if cvd is not None:
                if cvd > 0:
                    action, confidence = "BUY", 0.65
                elif cvd < 0:
                    action, confidence = "SELL", 0.65
        elif agent_l == "visual":
            action, confidence = "HOLD", 0.5  # stub; real model needs an image
        elif agent_l == "decision":
            # Count BUY/SELL/HOLD votes in the prompt
            ups = prompt.upper().count("BUY")
            downs = prompt.upper().count("SELL")
            if ups > downs:
                action, confidence = "BUY", 0.6
            elif downs > ups:
                action, confidence = "SELL", 0.6

        content = f"{action} {confidence:.2f} mock-{agent_l}"
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=len(prompt) // 4,
            output_tokens=len(content) // 4,
        )


class OpenRouterClient:
    """Async OpenRouter chat-completions client.

    Reads `OPENROUTER_API_KEY` from environment. Vision-capable models accept
    a single base64 PNG in `image_b64`; non-vision agents pass None.
    """

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str | None = None, timeout_s: float = 60.0) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._timeout = timeout_s

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set; use MockClient for offline runs.")

        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                }
            )
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=self._timeout) as cli:
            resp = await cli.post(self.BASE_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        msg = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            content=msg if isinstance(msg, str) else str(msg),
            model=model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )
```

- [ ] **Step 3:** `.\.venv\Scripts\pytest tests\test_llm_client.py -x` must PASS.

- [ ] **Commit:** `feat(llm): LLMClient protocol with deterministic MockClient and OpenRouterClient`

### Two-stage review

- [ ] Self-review: protocol is Awaitable, MockClient is pure-deterministic (no randomness), OpenRouterClient never called in tests.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 3: `llm/cache.py` — bar-keyed JSON cache decorator

**Files:**
- Create: `llm/cache.py`
- Create: `tests/test_llm_cache.py`

- [ ] **Step 1: Write the failing test `tests/test_llm_cache.py`**

```python
import json
from pathlib import Path

import pytest

from llm.cache import CachedClient, cache_key
from llm.client import LLMResponse, MockClient


def test_cache_key_stable_for_same_inputs():
    k1 = cache_key(model="m", agent="technical", prompt="abc", image_b64=None, bar_ts=123)
    k2 = cache_key(model="m", agent="technical", prompt="abc", image_b64=None, bar_ts=123)
    assert k1 == k2


def test_cache_key_changes_with_image():
    k1 = cache_key(model="m", agent="visual", prompt="x", image_b64=None, bar_ts=1)
    k2 = cache_key(model="m", agent="visual", prompt="x", image_b64="AAAA", bar_ts=1)
    assert k1 != k2


def test_cache_key_changes_with_bar_ts():
    k1 = cache_key(model="m", agent="technical", prompt="x", image_b64=None, bar_ts=1)
    k2 = cache_key(model="m", agent="technical", prompt="x", image_b64=None, bar_ts=2)
    assert k1 != k2


@pytest.mark.asyncio
async def test_cached_client_miss_then_hit(tmp_path: Path):
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    r1 = await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1_700_000_000_000,
    )
    # File should now exist
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1

    # Second call returns identical content WITHOUT invoking inner
    sentinel = object()
    class BoomClient:
        async def complete(self, **kwargs):  # noqa: D401
            raise AssertionError("inner client must not be called on cache hit")

    cached2 = CachedClient(inner=BoomClient(), cache_dir=tmp_path)
    r2 = await cached2.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1_700_000_000_000,
    )
    assert r2.content == r1.content
    assert r2.model == r1.model


@pytest.mark.asyncio
async def test_cached_client_writes_valid_json(tmp_path: Path):
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    await cached.complete(
        agent="qabba",
        prompt="cvd_delta=1000.0",
        image_b64=None,
        model="mock",
        bar_ts=1,
    )
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    obj = json.loads(files[0].read_text(encoding="utf-8"))
    assert "content" in obj
    assert "model" in obj
    assert "input_tokens" in obj
    assert "output_tokens" in obj
```

- [ ] **Step 2: Implement `llm/cache.py`**

```python
"""Bar-keyed JSON cache for LLM responses.

Key = sha256(model || agent || sha256(prompt) || sha256(image_b64) || bar_ts).
File layout: <cache_dir>/<model_safe>/<agent>/<key>.json.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from llm.client import LLMClient, LLMResponse


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def cache_key(
    *,
    model: str,
    agent: str,
    prompt: str,
    image_b64: str | None,
    bar_ts: int,
) -> str:
    prompt_h = _sha(prompt)
    image_h = _sha(image_b64) if image_b64 else "noimg"
    payload = f"{model}|{agent}|{prompt_h}|{image_h}|{bar_ts}"
    return _sha(payload)


def _safe_model(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


class CachedClient:
    """Decorator over any LLMClient that persists responses to disk.

    The wrapped `complete()` signature gains a required `bar_ts` kwarg used in
    the key per spec Q2 (deterministic-by-bar caching for replayable backtests).
    """

    def __init__(self, inner: LLMClient, cache_dir: Path | str) -> None:
        self._inner = inner
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _path_for(self, *, model: str, agent: str, key: str) -> Path:
        sub = self._dir / _safe_model(model) / agent.lower()
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{key}.json"

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
        bar_ts: int,
    ) -> LLMResponse:
        key = cache_key(
            model=model, agent=agent, prompt=prompt, image_b64=image_b64, bar_ts=bar_ts
        )
        path = self._path_for(model=model, agent=agent, key=key)

        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse(**obj)

        async with self._lock:
            # Double-check under the lock
            if path.exists():
                obj = json.loads(path.read_text(encoding="utf-8"))
                return LLMResponse(**obj)
            resp = await self._inner.complete(
                agent=agent, prompt=prompt, image_b64=image_b64, model=model
            )
            path.write_text(json.dumps(asdict(resp), indent=2), encoding="utf-8")
            return resp
```

- [ ] **Step 3:** `.\.venv\Scripts\pytest tests\test_llm_cache.py -x` must PASS.

- [ ] **Commit:** `feat(llm): bar-keyed JSON cache decorator (spec Q2)`

### Two-stage review

- [ ] Self-review: hashing covers all 5 dimensions; concurrent writes safe via lock; key length bounded.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 4: `llm/budget.py` — `BudgetGuard` with pre-call estimate

**Files:**
- Create: `llm/budget.py`
- Create: `tests/test_llm_budget.py`

- [ ] **Step 1: Write the failing test `tests/test_llm_budget.py`**

```python
import pytest

from llm.budget import BudgetExceededError, BudgetGuard, estimate_cost_usd


def test_estimate_cost_usd_basic():
    # 1000 input + 500 output tokens at $3/1M in, $15/1M out
    c = estimate_cost_usd(input_tokens=1000, output_tokens=500, in_per_1m=3.0, out_per_1m=15.0)
    assert c == pytest.approx(0.003 + 0.0075)


def test_budget_guard_allows_under_cap():
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.10)
    g.charge(0.20)
    assert g.spent_usd == pytest.approx(0.30)
    assert g.remaining_usd == pytest.approx(0.70)


def test_budget_guard_check_before_charge_raises_when_over():
    g = BudgetGuard(cap_usd=0.50)
    g.charge(0.40)
    with pytest.raises(BudgetExceededError):
        g.check_can_afford(0.20)


def test_budget_guard_check_allows_exact_cap():
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.50)
    g.check_can_afford(0.50)  # should not raise


def test_budget_guard_zero_cap_blocks_everything():
    g = BudgetGuard(cap_usd=0.0)
    with pytest.raises(BudgetExceededError):
        g.check_can_afford(0.001)
```

- [ ] **Step 2: Implement `llm/budget.py`**

```python
"""Per-run USD budget guard for LLM calls (spec §9)."""
from __future__ import annotations


class BudgetExceededError(RuntimeError):
    """Raised when a pending LLM call would push cumulative spend over the cap."""


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    in_per_1m: float,
    out_per_1m: float,
) -> float:
    return (input_tokens / 1_000_000.0) * in_per_1m + (output_tokens / 1_000_000.0) * out_per_1m


class BudgetGuard:
    """Tracks cumulative spend; refuses calls that would breach `cap_usd`."""

    def __init__(self, cap_usd: float) -> None:
        if cap_usd < 0:
            raise ValueError("cap_usd must be non-negative")
        self._cap = cap_usd
        self._spent = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent

    @property
    def remaining_usd(self) -> float:
        return self._cap - self._spent

    def check_can_afford(self, est_usd: float) -> None:
        if self._spent + est_usd > self._cap + 1e-9:
            raise BudgetExceededError(
                f"Budget exceeded: spent={self._spent:.4f} + est={est_usd:.4f} > cap={self._cap:.4f}"
            )

    def charge(self, usd: float) -> None:
        self._spent += usd
```

- [ ] **Step 3:** `.\.venv\Scripts\pytest tests\test_llm_budget.py -x` must PASS.

- [ ] **Commit:** `feat(llm): BudgetGuard with pre-call estimate (spec §9)`

### Two-stage review

- [ ] Self-review: zero cap blocks, negative cap rejected, exact-cap allowed (boundary).
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 5: `strategies/llm_agents/chart.py` — mplfinance base64 PNG renderer

**Files:**
- Create: `strategies/llm_agents/__init__.py` (empty)
- Create: `strategies/llm_agents/chart.py`
- Create: `tests/test_llm_chart.py`

- [ ] **Step 1: Write the failing test `tests/test_llm_chart.py`**

```python
import base64
from datetime import datetime, timezone, timedelta

import pytest

from core.types import Bar
from strategies.llm_agents.chart import render_chart


def _synthetic_bars(n: int = 60) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 50000.0
    for i in range(n):
        o = price
        c = price * (1.0 + (0.001 if i % 2 == 0 else -0.001))
        h = max(o, c) * 1.001
        l = min(o, c) * 0.999
        bars.append(
            Bar(
                timestamp=int((start + timedelta(hours=i)).timestamp() * 1000),
                open=o, high=h, low=l, close=c,
                volume=10.0, taker_buy_volume=5.0,
                cvd=0.0, cvd_delta=0.0,
            )
        )
        price = c
    return bars


def test_render_chart_returns_base64_png():
    bars = _synthetic_bars(60)
    b64 = render_chart(bars)
    assert isinstance(b64, str)
    raw = base64.b64decode(b64)
    # PNG magic header
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_chart_empty_bars_raises():
    with pytest.raises(ValueError):
        render_chart([])
```

- [ ] **Step 2: Implement `strategies/llm_agents/chart.py`**

```python
"""Render a candlestick chart from Bars to a base64-encoded PNG.

Used by the Visual agent. Output is small (default ~120 KB) and deterministic
for a given input series (mplfinance + Agg backend).
"""
from __future__ import annotations

import base64
import io
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")  # noqa: E402 — must come before pyplot import
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from core.types import Bar


def render_chart(bars: list[Bar], *, width_px: int = 800, height_px: int = 480) -> str:
    if not bars:
        raise ValueError("render_chart requires at least one bar")

    df = pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
            "Volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex(
            [datetime.fromtimestamp(b.timestamp / 1000.0, tz=timezone.utc) for b in bars]
        ),
    )

    buf = io.BytesIO()
    mpf.plot(
        df,
        type="candle",
        volume=True,
        style="charles",
        figsize=(width_px / 100.0, height_px / 100.0),
        savefig=dict(fname=buf, dpi=100, format="png", bbox_inches="tight"),
    )
    return base64.b64encode(buf.getvalue()).decode("ascii")
```

- [ ] **Step 3:** `.\.venv\Scripts\pytest tests\test_llm_chart.py -x` must PASS.

- [ ] **Commit:** `feat(llm): mplfinance candlestick chart renderer for Visual agent`

### Two-stage review

- [ ] Self-review: Agg backend prevents Windows GUI errors; PIL/Pillow not directly used (mplfinance handles); buffer closed implicitly.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 6: `strategies/llm_agents/state.py` + `prompts.py`

**Files:**
- Create: `strategies/llm_agents/state.py`
- Create: `strategies/llm_agents/prompts.py`
- Create: `tests/test_llm_state.py` (small)

- [ ] **Step 1: Write the failing test `tests/test_llm_state.py`**

```python
from strategies.llm_agents.prompts import build_technical_prompt, build_qabba_prompt, build_visual_prompt, build_decision_prompt
from strategies.llm_agents.state import GraphState
from core.types import AgentReport, Action


def test_graph_state_typed_dict_has_required_keys():
    s: GraphState = {
        "bar_ts": 1,
        "features": {"ema_fast": 1.0},
        "image_b64": None,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }
    assert s["bar_ts"] == 1


def test_build_technical_prompt_includes_features():
    p = build_technical_prompt(
        {"ema_fast": 110.0, "ema_slow": 100.0, "rsi": 60.0, "macd_hist": 0.5}
    )
    assert "ema_fast=110" in p
    assert "ema_slow=100" in p
    assert "rsi=60" in p
    assert "macd_hist=0.5" in p


def test_build_qabba_prompt_includes_cvd():
    p = build_qabba_prompt({"cvd_delta": 1234.5, "cvd": 9999.0})
    assert "cvd_delta=1234.5" in p


def test_build_visual_prompt_mentions_chart():
    p = build_visual_prompt()
    assert "chart" in p.lower()


def test_build_decision_prompt_summarises_reports():
    reports = {
        "technical": AgentReport(action=Action.BUY, confidence=0.7, rationale="x"),
        "visual": AgentReport(action=Action.HOLD, confidence=0.5, rationale="y"),
        "qabba": AgentReport(action=Action.BUY, confidence=0.8, rationale="z"),
    }
    p = build_decision_prompt(reports)
    assert "tech=BUY:0.70" in p
    assert "visual=HOLD:0.50" in p
    assert "qabba=BUY:0.80" in p
```

- [ ] **Step 2: Implement `strategies/llm_agents/state.py`**

```python
"""LangGraph state schema for the LLM agent pipeline."""
from __future__ import annotations

from typing import TypedDict

from core.types import AgentReport


class GraphState(TypedDict):
    bar_ts: int
    features: dict[str, float]
    image_b64: str | None
    model: str
    technical: AgentReport | None
    visual: AgentReport | None
    qabba: AgentReport | None
    decision: AgentReport | None
```

- [ ] **Step 3: Implement `strategies/llm_agents/prompts.py`**

```python
"""Prompt templates for the 4 LLM agents.

Kept terse and explicit so MockClient regex extraction is reliable and so the
real OpenRouter calls stay within the per-run budget cap.
"""
from __future__ import annotations

from core.types import AgentReport


def _fmt(v: float) -> str:
    return f"{v:g}"


def build_technical_prompt(features: dict[str, float]) -> str:
    keys = ("ema_fast", "ema_slow", "rsi", "macd_hist", "adx")
    parts = [f"{k}={_fmt(features[k])}" for k in keys if k in features]
    body = " ".join(parts)
    return (
        "You are a technical analyst. Given these indicator readings, output one of "
        "BUY, SELL, HOLD followed by a confidence in [0,1] and a one-line rationale.\n"
        f"Features: {body}\n"
        "Format: <ACTION> <CONFIDENCE> <RATIONALE>"
    )


def build_qabba_prompt(features: dict[str, float]) -> str:
    parts = []
    if "cvd" in features:
        parts.append(f"cvd={_fmt(features['cvd'])}")
    if "cvd_delta" in features:
        parts.append(f"cvd_delta={_fmt(features['cvd_delta'])}")
    body = " ".join(parts)
    return (
        "You are a quantitative order-flow analyst (QABBA). Given the cumulative "
        "volume delta readings, output BUY/SELL/HOLD plus a confidence and one-line "
        f"rationale.\nFeatures: {body}\nFormat: <ACTION> <CONFIDENCE> <RATIONALE>"
    )


def build_visual_prompt() -> str:
    return (
        "You are a chart-pattern analyst. Examine the attached candlestick chart "
        "and output BUY/SELL/HOLD plus a confidence in [0,1] and a one-line "
        "rationale. Format: <ACTION> <CONFIDENCE> <RATIONALE>"
    )


def build_decision_prompt(reports: dict[str, AgentReport]) -> str:
    def _r(name: str) -> str:
        r = reports.get(name)
        if r is None:
            return f"{name}=NA"
        return f"{name}={r.action.name}:{r.confidence:.2f}"

    return (
        "You are the decision arbiter. Three analysts have voted. Output one of "
        "BUY/SELL/HOLD plus a confidence in [0,1] and a one-line rationale.\n"
        f"Votes: tech={_r('technical').split('=', 1)[1]} "
        f"visual={_r('visual').split('=', 1)[1]} "
        f"qabba={_r('qabba').split('=', 1)[1]}\n"
        "Format: <ACTION> <CONFIDENCE> <RATIONALE>"
    )
```

- [ ] **Step 4:** `.\.venv\Scripts\pytest tests\test_llm_state.py -x` must PASS.

- [ ] **Commit:** `feat(llm): GraphState TypedDict and prompt templates`

### Two-stage review

- [ ] Self-review: prompts contain stable key=value pairs MockClient can parse; no f-string injection of secrets.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 7: Parse helper + 4 node implementations

**Files:**
- Create: `strategies/llm_agents/nodes/__init__.py` (empty)
- Create: `strategies/llm_agents/nodes/_parse.py` — shared `parse_response(content) -> AgentReport`
- Create: `strategies/llm_agents/nodes/technical.py`
- Create: `strategies/llm_agents/nodes/visual.py`
- Create: `strategies/llm_agents/nodes/qabba.py`
- Create: `strategies/llm_agents/nodes/decision.py`
- Create: `tests/test_llm_nodes.py`
- Create: `tests/test_llm_decision.py`

- [ ] **Step 1: Write failing tests `tests/test_llm_nodes.py`**

```python
import pytest

from core.types import Action
from llm.client import MockClient
from strategies.llm_agents.nodes._parse import parse_response
from strategies.llm_agents.nodes.technical import technical_node
from strategies.llm_agents.nodes.visual import visual_node
from strategies.llm_agents.nodes.qabba import qabba_node
from strategies.llm_agents.state import GraphState


def test_parse_response_buy():
    r = parse_response("BUY 0.72 strong cross")
    assert r.action is Action.BUY
    assert r.confidence == pytest.approx(0.72)
    assert "cross" in r.rationale


def test_parse_response_sell():
    r = parse_response("SELL 0.40 weak")
    assert r.action is Action.SELL
    assert r.confidence == pytest.approx(0.40)


def test_parse_response_hold_default_on_garbage():
    r = parse_response("nonsense")
    assert r.action is Action.HOLD
    assert 0.0 <= r.confidence <= 1.0


def test_parse_response_clamps_confidence():
    r = parse_response("BUY 1.7 too eager")
    assert r.confidence == 1.0
    r2 = parse_response("SELL -0.3 weird")
    assert r2.confidence == 0.0


def _state(features: dict[str, float], image_b64: str | None = None) -> GraphState:
    return {
        "bar_ts": 1,
        "features": features,
        "image_b64": image_b64,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }


@pytest.mark.asyncio
async def test_technical_node_writes_report():
    client = MockClient()
    s = _state({"ema_fast": 110, "ema_slow": 100, "macd_hist": 0.5, "rsi": 60})
    out = await technical_node(s, client=client)
    assert out["technical"] is not None
    assert out["technical"].action is Action.BUY


@pytest.mark.asyncio
async def test_qabba_node_sell_on_negative_cvd():
    client = MockClient()
    s = _state({"cvd_delta": -500, "cvd": -1000})
    out = await qabba_node(s, client=client)
    assert out["qabba"].action is Action.SELL


@pytest.mark.asyncio
async def test_visual_node_hold_with_mock():
    client = MockClient()
    s = _state({}, image_b64=None)
    out = await visual_node(s, client=client)
    assert out["visual"].action is Action.HOLD
```

- [ ] **Step 2: Write failing tests `tests/test_llm_decision.py`**

```python
import pytest

from core.types import Action, AgentReport
from strategies.llm_agents.nodes.decision import decision_node
from strategies.llm_agents.state import GraphState


def _state(tech, visual, qabba) -> GraphState:
    return {
        "bar_ts": 1,
        "features": {},
        "image_b64": None,
        "model": "mock",
        "technical": tech,
        "visual": visual,
        "qabba": qabba,
        "decision": None,
    }


@pytest.mark.asyncio
async def test_decision_buy_when_all_buy():
    s = _state(
        AgentReport(action=Action.BUY, confidence=0.8, rationale="t"),
        AgentReport(action=Action.BUY, confidence=0.7, rationale="v"),
        AgentReport(action=Action.BUY, confidence=0.9, rationale="q"),
    )
    out = await decision_node(s)
    assert out["decision"].action is Action.BUY
    # buy_score = 0.40*0.9 + 0.35*0.7 + 0.25*0.8 = 0.36 + 0.245 + 0.20 = 0.805
    assert out["decision"].confidence == pytest.approx(0.805)


@pytest.mark.asyncio
async def test_decision_hold_when_split_under_threshold():
    s = _state(
        AgentReport(action=Action.BUY, confidence=0.5, rationale="t"),
        AgentReport(action=Action.SELL, confidence=0.5, rationale="v"),
        AgentReport(action=Action.HOLD, confidence=0.5, rationale="q"),
    )
    out = await decision_node(s)
    assert out["decision"].action is Action.HOLD


@pytest.mark.asyncio
async def test_decision_qabba_dominates_due_to_largest_weight():
    s = _state(
        AgentReport(action=Action.SELL, confidence=0.9, rationale="t"),
        AgentReport(action=Action.SELL, confidence=0.9, rationale="v"),
        AgentReport(action=Action.BUY, confidence=1.0, rationale="q"),
    )
    out = await decision_node(s)
    # buy_score = 0.40*1.0 = 0.40 ; sell_score = 0.35*0.9 + 0.25*0.9 = 0.315+0.225 = 0.54
    # 0.54 > 0.50 and > 0.40 → SELL
    assert out["decision"].action is Action.SELL


@pytest.mark.asyncio
async def test_decision_handles_none_reports_gracefully():
    s = _state(None, None, AgentReport(action=Action.BUY, confidence=1.0, rationale="q"))
    out = await decision_node(s)
    # buy_score = 0.40, threshold > 0.50 → HOLD
    assert out["decision"].action is Action.HOLD
```

- [ ] **Step 3: Implement `strategies/llm_agents/nodes/_parse.py`**

```python
"""Shared parser turning model output into an AgentReport."""
from __future__ import annotations

import re

from core.types import Action, AgentReport

_RE = re.compile(r"\b(BUY|SELL|HOLD)\b\s*(-?\d+\.?\d*)?\s*(.*)", re.IGNORECASE)


def parse_response(content: str) -> AgentReport:
    m = _RE.search(content)
    if not m:
        return AgentReport(action=Action.HOLD, confidence=0.5, rationale=content.strip()[:200])
    action = Action[m.group(1).upper()]
    try:
        conf = float(m.group(2)) if m.group(2) else 0.5
    except ValueError:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    rationale = (m.group(3) or "").strip()[:200]
    return AgentReport(action=action, confidence=conf, rationale=rationale)
```

- [ ] **Step 4: Implement the three analyst nodes**

`strategies/llm_agents/nodes/technical.py`:

```python
from __future__ import annotations

from llm.client import LLMClient
from strategies.llm_agents.nodes._parse import parse_response
from strategies.llm_agents.prompts import build_technical_prompt
from strategies.llm_agents.state import GraphState


async def technical_node(state: GraphState, *, client: LLMClient) -> GraphState:
    prompt = build_technical_prompt(state["features"])
    # If using CachedClient, bar_ts is required; we forward it via kwargs.
    kwargs = dict(agent="technical", prompt=prompt, image_b64=None, model=state["model"])
    if hasattr(client, "_inner"):  # cached
        kwargs["bar_ts"] = state["bar_ts"]
    resp = await client.complete(**kwargs)
    return {**state, "technical": parse_response(resp.content)}
```

`strategies/llm_agents/nodes/qabba.py` (analogous; agent="qabba"; uses `build_qabba_prompt`).

`strategies/llm_agents/nodes/visual.py` (analogous; agent="visual"; uses `build_visual_prompt`; passes `image_b64=state["image_b64"]`).

- [ ] **Step 5: Implement `strategies/llm_agents/nodes/decision.py`** (deterministic guardrail; LLM call optional)

```python
"""Decision node: deterministic weighted-consensus guardrail (spec §7.2).

LLM is intentionally NOT called here in the default path — the math wins. The
node is async to fit LangGraph's signature uniformly.
"""
from __future__ import annotations

from core.types import Action, AgentReport
from strategies.llm_agents.state import GraphState

W_QABBA = 0.40
W_VISUAL = 0.35
W_TECH = 0.25
THRESHOLD = 0.50


def _score(reports: dict[str, AgentReport | None], side: Action) -> float:
    s = 0.0
    if reports["qabba"] is not None and reports["qabba"].action is side:
        s += W_QABBA * reports["qabba"].confidence
    if reports["visual"] is not None and reports["visual"].action is side:
        s += W_VISUAL * reports["visual"].confidence
    if reports["technical"] is not None and reports["technical"].action is side:
        s += W_TECH * reports["technical"].confidence
    return s


async def decision_node(state: GraphState) -> GraphState:
    reports = {
        "technical": state["technical"],
        "visual": state["visual"],
        "qabba": state["qabba"],
    }
    buy = _score(reports, Action.BUY)
    sell = _score(reports, Action.SELL)

    if buy > THRESHOLD and buy > sell:
        action, conf = Action.BUY, buy
    elif sell > THRESHOLD and sell > buy:
        action, conf = Action.SELL, sell
    else:
        action, conf = Action.HOLD, max(buy, sell, 0.5)

    rationale = f"buy={buy:.3f} sell={sell:.3f} weights(Q={W_QABBA},V={W_VISUAL},T={W_TECH})"
    return {**state, "decision": AgentReport(action=action, confidence=conf, rationale=rationale)}
```

- [ ] **Step 6:** `.\.venv\Scripts\pytest tests\test_llm_nodes.py tests\test_llm_decision.py -x` must PASS.

- [ ] **Commit:** `feat(llm): 4 agent nodes with deterministic Decision guardrail (spec §7.2)`

### Two-stage review

- [ ] Self-review: weights sum to 1.0; HOLD on tie; None-report safe; parser clamps confidence; tests cover the exact formulas in the spec.
- [ ] Dispatch `code-reviewer` subagent — request explicit verification that `decision_node` weights match spec §7.2 (`0.40 QABBA / 0.35 Visual / 0.25 Technical`).

---

## Task 8: `strategies/llm_agents/graph.py` — wire LangGraph

**Files:**
- Create: `strategies/llm_agents/graph.py`
- Create: `tests/test_llm_graph.py`

- [ ] **Step 1: Write the failing test `tests/test_llm_graph.py`**

```python
import pytest

from core.types import Action
from llm.client import MockClient
from strategies.llm_agents.graph import build_graph


@pytest.mark.asyncio
async def test_build_graph_runs_end_to_end_with_mock_client():
    graph = build_graph(client=MockClient())
    initial = {
        "bar_ts": 1,
        "features": {
            "ema_fast": 110.0,
            "ema_slow": 100.0,
            "macd_hist": 0.5,
            "rsi": 60.0,
            "cvd": 1000.0,
            "cvd_delta": 500.0,
        },
        "image_b64": None,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }
    final = await graph.ainvoke(initial)
    assert final["technical"] is not None
    assert final["visual"] is not None
    assert final["qabba"] is not None
    assert final["decision"] is not None
    # All-bullish technical + QABBA, visual=HOLD: buy_score = 0.40*0.65 + 0.25*0.7 = 0.435
    # 0.435 < 0.50 → HOLD per guardrail
    assert final["decision"].action is Action.HOLD


@pytest.mark.asyncio
async def test_build_graph_sell_path():
    graph = build_graph(client=MockClient())
    initial = {
        "bar_ts": 1,
        "features": {
            "ema_fast": 90.0,
            "ema_slow": 100.0,
            "macd_hist": -0.5,
            "rsi": 40.0,
            "cvd": -1000.0,
            "cvd_delta": -500.0,
        },
        "image_b64": None,
        "model": "mock",
        "technical": None,
        "visual": None,
        "qabba": None,
        "decision": None,
    }
    final = await graph.ainvoke(initial)
    # technical SELL conf 0.7, qabba SELL conf 0.65, visual HOLD
    # sell_score = 0.40*0.65 + 0.25*0.7 = 0.435 < 0.50 → HOLD again
    assert final["decision"].action is Action.HOLD
```

> NOTE: MockClient confidences (0.7 tech, 0.65 qabba) intentionally make
> the weighted sum sit below 0.50 so HOLD is correct — this tests the guardrail
> is enforcing the threshold rather than just majority voting.

- [ ] **Step 2: Implement `strategies/llm_agents/graph.py`**

```python
"""LangGraph wiring: fan-out 3 analyst nodes in parallel → Decision."""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from llm.client import LLMClient
from strategies.llm_agents.nodes.decision import decision_node
from strategies.llm_agents.nodes.qabba import qabba_node
from strategies.llm_agents.nodes.technical import technical_node
from strategies.llm_agents.nodes.visual import visual_node
from strategies.llm_agents.state import GraphState


def build_graph(*, client: LLMClient):
    """Return a compiled LangGraph that, given an initial GraphState, runs the
    three analyst nodes in parallel and then the deterministic Decision node.
    """
    g = StateGraph(GraphState)
    g.add_node("technical", partial(technical_node, client=client))
    g.add_node("visual", partial(visual_node, client=client))
    g.add_node("qabba", partial(qabba_node, client=client))
    g.add_node("decision", decision_node)

    # Fan out from START to all three analysts (LangGraph runs them concurrently)
    g.add_edge(START, "technical")
    g.add_edge(START, "visual")
    g.add_edge(START, "qabba")

    # All three converge into decision
    g.add_edge("technical", "decision")
    g.add_edge("visual", "decision")
    g.add_edge("qabba", "decision")

    g.add_edge("decision", END)

    return g.compile()
```

- [ ] **Step 3:** `.\.venv\Scripts\pytest tests\test_llm_graph.py -x` must PASS.

> **POTENTIAL BLOCKER:** LangGraph state reducers — if running three nodes in
> parallel each returning a different key (`technical`, `visual`, `qabba`) works
> out-of-the-box on the installed LangGraph version, no annotation is needed.
> If it does NOT (LangGraph complains about concurrent state updates), use
> `Annotated[..., operator.add]` style reducers or split state into separate
> per-agent fields. Mark as BLOCKED and surface to the user.

- [ ] **Commit:** `feat(llm): LangGraph wiring START→{tech,visual,qabba}→decision→END`

### Two-stage review

- [ ] Self-review: parallel fan-out works; ainvoke is awaited; partial() binds client per-node.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 9: `strategies/llm_agents/strategy.py` — `LLMAgentStrategy`

**Files:**
- Create: `strategies/llm_agents/strategy.py`
- Create: `tests/test_llm_strategy.py`

- [ ] **Step 1: Write the failing test `tests/test_llm_strategy.py`**

```python
from collections import deque
from datetime import datetime, timezone, timedelta

import pytest

from core.types import Action, Bar, Signal
from llm.client import MockClient
from strategies.base import Context
from strategies.llm_agents.strategy import LLMAgentStrategy


def _bars(n: int = 60) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(
            timestamp=int((start + timedelta(hours=i)).timestamp() * 1000),
            open=50000 + i * 10,
            high=50100 + i * 10,
            low=49900 + i * 10,
            close=50050 + i * 10,
            volume=1.0,
            taker_buy_volume=0.6,
            cvd=100.0 * i,
            cvd_delta=100.0,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_llm_strategy_returns_signal():
    strat = LLMAgentStrategy(client=MockClient(), model="mock", image_window_bars=20, render_image=False)
    bars = _bars(60)
    ctx = Context(
        history=deque(bars[:-1]),
        balance=10_000.0,
        position_qty=0.0,
        symbol="BTC/USDT",
        timeframe="1h",
    )
    sig = await strat.generate_signal(bars[-1], ctx)
    assert isinstance(sig, Signal)
    assert sig.action in (Action.BUY, Action.SELL, Action.HOLD)
    assert 0.0 <= sig.confidence <= 1.0


@pytest.mark.asyncio
async def test_llm_strategy_warmup_returns_hold():
    """Too few bars in history → HOLD without invoking the graph."""
    strat = LLMAgentStrategy(client=MockClient(), model="mock", image_window_bars=20, render_image=False)
    bars = _bars(5)
    ctx = Context(
        history=deque(bars[:-1]),
        balance=10_000.0,
        position_qty=0.0,
        symbol="BTC/USDT",
        timeframe="1h",
    )
    sig = await strat.generate_signal(bars[-1], ctx)
    assert sig.action is Action.HOLD
```

- [ ] **Step 2: Implement `strategies/llm_agents/strategy.py`**

```python
"""LLM agent strategy: assembles features, optionally renders chart, runs graph."""
from __future__ import annotations

import pandas as pd

from core.types import Action, Bar, Signal
from indicators.ta import ema, macd, rsi
from llm.client import LLMClient
from strategies.base import Context, Strategy
from strategies.llm_agents.chart import render_chart
from strategies.llm_agents.graph import build_graph

WARMUP_BARS = 30


class LLMAgentStrategy(Strategy):
    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        image_window_bars: int = 60,
        render_image: bool = True,
        ema_fast_n: int = 12,
        ema_slow_n: int = 26,
        rsi_n: int = 14,
    ) -> None:
        self._client = client
        self._model = model
        self._image_window = image_window_bars
        self._render_image = render_image
        self._ema_fast_n = ema_fast_n
        self._ema_slow_n = ema_slow_n
        self._rsi_n = rsi_n
        self._graph = build_graph(client=client)

    async def generate_signal(self, bar: Bar, context: Context) -> Signal:
        history = list(context.history) + [bar]
        if len(history) < WARMUP_BARS:
            return Signal(action=Action.HOLD, confidence=0.5, reasoning="warmup", stop_loss=None)

        closes = pd.Series([b.close for b in history])
        ema_fast = float(ema(closes, self._ema_fast_n).iloc[-1])
        ema_slow = float(ema(closes, self._ema_slow_n).iloc[-1])
        rsi_v = float(rsi(closes, self._rsi_n).iloc[-1])
        _macd_line, _signal_line, macd_hist = macd(closes)
        macd_h = float(macd_hist.iloc[-1])

        features = {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi_v,
            "macd_hist": macd_h,
            "cvd": bar.cvd,
            "cvd_delta": bar.cvd_delta,
        }

        image_b64: str | None = None
        if self._render_image:
            window = history[-self._image_window :]
            image_b64 = render_chart(window)

        initial = {
            "bar_ts": bar.timestamp,
            "features": features,
            "image_b64": image_b64,
            "model": self._model,
            "technical": None,
            "visual": None,
            "qabba": None,
            "decision": None,
        }
        final = await self._graph.ainvoke(initial)
        d = final["decision"]
        return Signal(
            action=d.action,
            confidence=d.confidence,
            reasoning=d.rationale,
            stop_loss=None,
        )
```

- [ ] **Step 3:** `.\.venv\Scripts\pytest tests\test_llm_strategy.py -x` must PASS.

- [ ] **Commit:** `feat(llm): LLMAgentStrategy bridges Strategy protocol to LangGraph`

### Two-stage review

- [ ] Self-review: warmup HOLD avoids graph cost; render_image=False path skips mplfinance (faster tests); stop_loss=None deferred to broker default.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 10: Integrate `CachedClient` + `BudgetGuard` end-to-end test

**Files:**
- Create: `tests/test_llm_e2e_cached.py`

- [ ] **Step 1: Write the failing test**

```python
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from core.types import Bar
from llm.budget import BudgetGuard
from llm.cache import CachedClient
from llm.client import MockClient
from strategies.base import Context
from strategies.llm_agents.strategy import LLMAgentStrategy


def _bars(n: int) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(
            timestamp=int((start + timedelta(hours=i)).timestamp() * 1000),
            open=50000 + i * 5, high=50100 + i * 5, low=49900 + i * 5, close=50050 + i * 5,
            volume=1.0, taker_buy_volume=0.5,
            cvd=10.0 * i, cvd_delta=10.0,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_cached_strategy_replay_is_zero_cost(tmp_path: Path):
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    strat = LLMAgentStrategy(client=cached, model="mock", image_window_bars=20, render_image=False)
    bars = _bars(40)

    # First pass — populates cache
    ctx = Context(history=deque(bars[:-1]), balance=1e4, position_qty=0.0, symbol="BTC/USDT", timeframe="1h")
    sig1 = await strat.generate_signal(bars[-1], ctx)

    # Confirm 3 cache files exist (one per analyst; decision is deterministic, no LLM)
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 3

    # Second pass — replace inner with a Boom client to prove no LLM calls happen
    class Boom:
        async def complete(self, **kw):
            raise AssertionError("cache should serve all calls")

    cached2 = CachedClient(inner=Boom(), cache_dir=tmp_path)
    strat2 = LLMAgentStrategy(client=cached2, model="mock", image_window_bars=20, render_image=False)
    sig2 = await strat2.generate_signal(bars[-1], ctx)

    assert sig1.action is sig2.action
    assert sig1.confidence == pytest.approx(sig2.confidence)


def test_budget_guard_aborts_before_call():
    g = BudgetGuard(cap_usd=0.001)
    g.charge(0.001)
    with pytest.raises(Exception):
        g.check_can_afford(0.0001)
```

- [ ] **Step 2: Confirm passes (no implementation needed — just integration coverage).**

- [ ] **Commit:** `test(llm): end-to-end cached replay is zero-cost and deterministic`

### Two-stage review

- [ ] Self-review: 3 cache files = exactly the 3 analyst calls; decision is local; replay proves Boom client never invoked.
- [ ] Dispatch `code-reviewer` subagent.

---

## Task 11: `pyproject.toml`, `.gitignore`, `cache/llm/.gitkeep`, `README.md`

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `cache/llm/.gitkeep`
- Modify: `README.md` (EN + ID sections)

- [x] **Step 1: Add dependencies to `pyproject.toml`** (langgraph, langchain-core, mplfinance, pillow added; httpx already present)

- [x] **Step 2: `.gitignore`** — removed `cache/llm/` ignore rule; added comment documenting tracking intent.

- [x] **Step 3: `cache/llm/.gitkeep`** — created.

- [x] **Step 4: `README.md`** — bilingual EN+ID sections added (Mock mode, OpenRouter mode, cache replay, budget cap).

- [x] **Step 5:** `pip install -e ".[dev]"` — success.

- [x] **Step 6:** Full pytest — **179 passed, 1 skipped** in 11.54s.

- [x] **Commit:** `74bf83f chore(llm): pin langgraph/mplfinance deps, track cache dir, README sections`

### Two-stage review

- [x] Self-review checklist:
  - [x] Full test suite passes (179 + 1 skipped).
  - [x] Coverage on `llm/` and `strategies/llm_agents/` validated in prior tasks.
  - [x] `cache/llm/` exists and is tracked in git (verified via `git check-ignore -v` returning empty).
  - [x] README has both EN and ID sections.
- [x] Dispatch `code-reviewer` subagent on the full sub-plan C diff. **Verdict: APPROVE with nits.** One nit (bar_ts type) verified as false alarm — strategy.py:109 already passes `int`. No fixes required.

---

## Final verification

- [x] Full pytest: **179 passed, 1 skipped** in 11.54s.
- [x] Ruff clean on all sub-plan C touched files (pre-existing UP017/E501 outside scope).
- [ ] mypy not configured in this project.
- [x] `git push origin master` — pushed `6ecce70..74bf83f` (11 commits).
- [ ] Use skill `finishing-a-development-branch` to decide next step (sub-plan D vs PR).

---

## Risks & open questions

1. **LangGraph parallel state updates** — if the installed version requires explicit reducers for `technical`/`visual`/`qabba` keys when written concurrently, Task 8 may need `Annotated[AgentReport | None, take_last]` or a per-agent fan-in node. Mark BLOCKED if so.
2. **mplfinance on headless Windows** — `matplotlib.use("Agg")` should suffice but Pillow occasionally complains about font caches on first run. If tests are flaky, pre-warm the font cache in `conftest.py`.
3. **OpenRouter response shape** — `OpenRouterClient` is not exercised in tests beyond construction; defer real-API smoke test to sub-plan D where one full async backtest pass with a tiny dataset can validate it.
4. **Decision LLM call** — currently omitted (deterministic-only). If the seminar reviewer asks for an explicit LLM Decision call, add it as an optional logged side-effect in `decision_node` (math still wins).
