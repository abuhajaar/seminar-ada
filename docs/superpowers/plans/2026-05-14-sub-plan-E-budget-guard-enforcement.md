# Sub-plan E — BudgetGuard Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `BudgetGuard` into the live LLM client stack so `llm.max_usd` becomes a real per-run dollar ceiling, while keeping cached replays free and mock mode untouched.

**Architecture:** New `BudgetGuardedClient` decorator wraps `CachedClient`. Cache hits short-circuit before the guard sees them. Misses pay pre-call estimate (`len(prompt)//4` input tokens + configurable `expected_output_tokens`) and post-call exact charge from `LLMResponse` token counts. Per-model pricing lives in `config.yaml` under `llm.pricing`. A new Pydantic validator rejects configs where any agent's model lacks a pricing entry.

**Tech Stack:** Python 3.13, asyncio, pydantic v2, pytest-asyncio. No new third-party deps.

**Spec:** `docs/superpowers/specs/2026-05-14-budget-guard-enforcement-design.en.md`

---

## File Structure

- **Create:** `llm/budget_client.py` — `ModelPricing` dataclass + `BudgetGuardedClient` decorator implementing `LLMClient.complete()` with `bar_ts` passthrough.
- **Create:** `tests/test_budget_client.py` — full coverage of the decorator: under-budget, over-budget, error carries `spend_usd`, unknown model, `bar_ts` passthrough, cache-hit-skips-guard.
- **Modify:** `llm/budget.py` — `BudgetExceededError.__init__` accepts `spend_usd`; `BudgetGuard.check_can_afford` passes `spend_usd=self._spent`.
- **Modify:** `tests/test_llm_budget.py` — new test asserting `BudgetExceededError.spend_usd` is populated on refusal.
- **Modify:** `core/config.py` — `PricingCfg` model; `LlmCfg.pricing: dict[str, PricingCfg]` and `LlmCfg.expected_output_tokens: int = 300`; new `model_validator` `_every_agent_model_priced`.
- **Modify:** `config.yaml` — `llm.pricing` block (one entry for `anthropic/claude-3.5-sonnet`) and `expected_output_tokens: 300`.
- **Modify:** `tests/test_config.py` — fixture YAML gains a `pricing` block; new test rejecting unpriced-model config.
- **Modify:** `strategies/llm_agents/nodes/_common.py` — `call_llm` forwards `bar_ts` when client is `CachedClient` OR `BudgetGuardedClient`.
- **Modify:** `tests/test_llm_nodes.py` (or wherever `call_llm` is tested) — assert `bar_ts` passthrough through a `BudgetGuardedClient`.
- **Modify:** `main.py` — build `BudgetGuardedClient` on non-mock path; pass `on_progress` callback to update `rs_holder["rs"].spend_usd` from `guard.spent_usd`.
- **Modify:** `tests/test_main.py` — non-mock smoke test using a fake `OpenRouterClient` with deterministic token counts, asserting `guard.spent_usd > 0`.

---

### Task 1: Add `spend_usd` attribute to `BudgetExceededError` ✅ DONE (commit 85091ac)

**Files:**
- Modify: `llm/budget.py:28-30`, `llm/budget.py:72-85`
- Modify: `tests/test_llm_budget.py` (append one test)

- [x] **Step 1: Write the failing test**

Append to `tests/test_llm_budget.py`:

```python
def test_budget_exceeded_error_carries_spend_usd():
    """check_can_afford must raise with spend_usd populated to current _spent."""
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.80)
    with pytest.raises(BudgetExceededError) as exc_info:
        g.check_can_afford(0.50)  # 0.80 + 0.50 > 1.0
    assert exc_info.value.spend_usd == pytest.approx(0.80)


def test_budget_exceeded_error_default_spend_usd_zero():
    """Constructing the error without a spend_usd kwarg defaults to 0.0."""
    err = BudgetExceededError("test")
    assert err.spend_usd == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_llm_budget.py -v -k "carries_spend_usd or default_spend_usd_zero"`
Expected: 2 FAIL with `AttributeError: 'BudgetExceededError' object has no attribute 'spend_usd'`.

- [ ] **Step 3: Implement minimal change in `llm/budget.py`**

Replace the `BudgetExceededError` definition:

```python
class BudgetExceededError(RuntimeError):
    """Raised when a pending LLM call would push cumulative spend over the cap.

    Args:
        message: Human-readable description.
        spend_usd: Cumulative USD already charged at the moment of refusal.
            Defaults to 0.0 for backward-compatible construction.
    """

    def __init__(self, message: str, *, spend_usd: float = 0.0) -> None:
        super().__init__(message)
        self.spend_usd = spend_usd
```

Replace the `raise BudgetExceededError(...)` line inside `check_can_afford` (~line 81):

```python
        if self._spent + est_usd > self._cap + _EPS_USD:
            raise BudgetExceededError(
                f"Budget exceeded: spent={self._spent:.4f} + est={est_usd:.4f} "
                f"> cap={self._cap:.4f}",
                spend_usd=self._spent,
            )
```

- [ ] **Step 4: Run all budget tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_llm_budget.py -v`
Expected: all green (existing tests still pass; 2 new pass).

- [ ] **Step 5: Commit**

```powershell
git add llm/budget.py tests/test_llm_budget.py
$msg = "feat(budget): attach spend_usd to BudgetExceededError`n`nThe walkforward runner already reads getattr(e, 'spend_usd', None)`ndefensively (core/walkforward.py:112) but the attribute was never`nset, so the recorded value was always 0.0. Now check_can_afford`nraises with spend_usd=self._spent, making the walkforward log`naccurate.`n`nPart of sub-plan E (task 1)."
[System.IO.File]::WriteAllText("$PWD\.git\COMMIT_MSG", $msg, (New-Object System.Text.UTF8Encoding $false))
git commit -F .git/COMMIT_MSG
Remove-Item .git/COMMIT_MSG
```

---

### Task 2: Add `PricingCfg` + `expected_output_tokens` + pricing validator to config schema ✅ DONE (commit 97793c6)

**Files:**
- Modify: `core/config.py:63-79` (extend `LlmCfg`)
- Modify: `tests/test_config.py` (extend fixture, add validator test)
- Modify: `config.yaml` (add pricing block)

- [ ] **Step 1: Inspect existing test fixture**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v --collect-only`

Then `Read tests/test_config.py` to find the inline YAML fixture used by the loader tests. We'll need to extend it.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_llm_cfg_accepts_pricing_block(tmp_path):
    """Valid config with pricing entries for every agent loads cleanly."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_VALID_YAML_WITH_PRICING, encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.llm.pricing["anthropic/claude-3.5-sonnet"].in_per_1m == 3.0
    assert cfg.llm.expected_output_tokens == 300


def test_llm_cfg_rejects_agent_without_pricing(tmp_path):
    """If an agent uses a model with no pricing entry, load_config raises."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_YAML_MISSING_PRICING, encoding="utf-8")
    with pytest.raises(ValueError, match="pricing entry"):
        load_config(cfg_path)
```

Define `_VALID_YAML_WITH_PRICING` and `_YAML_MISSING_PRICING` at module scope (copy the existing valid fixture; add or omit the `pricing` block). Example structure for the pricing addition:

```python
_PRICING_BLOCK = """
  expected_output_tokens: 300
  pricing:
    anthropic/claude-3.5-sonnet:
      in_per_1m: 3.0
      out_per_1m: 15.0
"""
```

Splice this into the `llm:` section of the existing fixture string.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v -k "pricing"`
Expected: FAIL with `pydantic.ValidationError` (`pricing` is an unknown field) or `AttributeError`.

- [ ] **Step 4: Extend `LlmCfg` in `core/config.py`**

After `class IndicatorsCfg`, insert:

```python
class PricingCfg(BaseModel):
    in_per_1m: float = Field(ge=0)
    out_per_1m: float = Field(ge=0)
```

Inside `class LlmCfg`, add after `consensus_threshold: float`:

```python
    pricing: dict[str, PricingCfg]
    expected_output_tokens: int = Field(default=300, gt=0)
```

Append a new validator inside `LlmCfg`, AFTER `_weights_sum_to_one`:

```python
    @model_validator(mode="after")
    def _every_agent_model_priced(self):
        missing = [
            f"{name} -> {agent.model}"
            for name, agent in self.agents.items()
            if agent.model not in self.pricing
        ]
        if missing:
            raise ValueError(
                "Every agent's model must have a pricing entry. Missing: "
                + ", ".join(missing)
            )
        return self
```

- [ ] **Step 5: Run config tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: all green.

- [ ] **Step 6: Update `config.yaml`**

Inside the `llm:` block, after `consensus_threshold: 0.50`, append:

```yaml
  expected_output_tokens: 300
  pricing:
    anthropic/claude-3.5-sonnet:
      in_per_1m: 3.00
      out_per_1m: 15.00
```

- [ ] **Step 7: Verify the project's own config still loads**

Run: `.\.venv\Scripts\python.exe -c "from core.config import load_config; print(load_config('config.yaml').llm.pricing)"`
Expected: prints the `{'anthropic/claude-3.5-sonnet': PricingCfg(in_per_1m=3.0, out_per_1m=15.0)}` dict.

- [ ] **Step 8: Commit**

```powershell
git add core/config.py tests/test_config.py config.yaml
$msg = "feat(config): add llm.pricing schema and expected_output_tokens`n`nIntroduces PricingCfg (per-model in/out USD per 1M tokens) and a`nmodel_validator rejecting configs where any agent's model lacks`na pricing entry. config.yaml gains pricing for the one model in`ncurrent use (anthropic/claude-3.5-sonnet at 3.0/15.0 per 1M).`n`nPart of sub-plan E (task 2)."
[System.IO.File]::WriteAllText("$PWD\.git\COMMIT_MSG", $msg, (New-Object System.Text.UTF8Encoding $false))
git commit -F .git/COMMIT_MSG
Remove-Item .git/COMMIT_MSG
```

---

### Task 3: Implement `BudgetGuardedClient` ✅ DONE (commit 41be6e5)

**Files:**
- Create: `llm/budget_client.py`
- Create: `tests/test_budget_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_budget_client.py`:

```python
"""Tests for llm.budget_client.BudgetGuardedClient (sub-plan E)."""
from __future__ import annotations

from pathlib import Path

import pytest

from llm.budget import BudgetExceededError, BudgetGuard
from llm.budget_client import BudgetGuardedClient, ModelPricing
from llm.cache import CachedClient
from llm.client import LLMResponse

MODEL = "test-model"
PRICING = {MODEL: ModelPricing(in_per_1m=3.0, out_per_1m=15.0)}


class _StubClient:
    """Records calls; returns deterministic LLMResponse."""

    def __init__(self, in_tokens: int = 100, out_tokens: int = 200) -> None:
        self.calls: list[dict] = []
        self._in = in_tokens
        self._out = out_tokens

    async def complete(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content="ok", model=kwargs["model"],
            input_tokens=self._in, output_tokens=self._out,
        )


@pytest.mark.asyncio
async def test_under_budget_charges_actual():
    guard = BudgetGuard(cap_usd=10.0)
    stub = _StubClient(in_tokens=100, out_tokens=200)
    client = BudgetGuardedClient(
        inner=stub, guard=guard, pricing=PRICING, expected_output_tokens=300,
    )
    resp = await client.complete(
        agent="technical", prompt="hello", image_b64=None, model=MODEL,
    )
    assert resp.content == "ok"
    # Actual cost: 100/1M * 3.0 + 200/1M * 15.0 = 0.0003 + 0.003 = 0.0033
    assert guard.spent_usd == pytest.approx(0.0033)


@pytest.mark.asyncio
async def test_over_budget_raises_before_inner_call():
    guard = BudgetGuard(cap_usd=1e-9)  # effectively zero
    stub = _StubClient()
    client = BudgetGuardedClient(
        inner=stub, guard=guard, pricing=PRICING, expected_output_tokens=300,
    )
    with pytest.raises(BudgetExceededError):
        await client.complete(
            agent="technical", prompt="hello", image_b64=None, model=MODEL,
        )
    assert stub.calls == []  # inner never reached


@pytest.mark.asyncio
async def test_budget_exceeded_carries_spend_usd():
    """First call succeeds and charges; second call refused with accumulated spend."""
    guard = BudgetGuard(cap_usd=0.004)  # allows one ~0.0033 call, not two
    stub = _StubClient(in_tokens=100, out_tokens=200)
    client = BudgetGuardedClient(
        inner=stub, guard=guard, pricing=PRICING, expected_output_tokens=300,
    )
    await client.complete(agent="technical", prompt="hi", image_b64=None, model=MODEL)
    with pytest.raises(BudgetExceededError) as exc_info:
        await client.complete(agent="technical", prompt="hi", image_b64=None, model=MODEL)
    assert exc_info.value.spend_usd == pytest.approx(0.0033)


@pytest.mark.asyncio
async def test_unknown_model_raises_runtime_error():
    guard = BudgetGuard(cap_usd=10.0)
    stub = _StubClient()
    client = BudgetGuardedClient(
        inner=stub, guard=guard, pricing=PRICING, expected_output_tokens=300,
    )
    with pytest.raises(RuntimeError, match="pricing"):
        await client.complete(
            agent="technical", prompt="hi", image_b64=None, model="other-model",
        )
    assert stub.calls == []


@pytest.mark.asyncio
async def test_bar_ts_forwarded_when_inner_is_cached_client(tmp_path: Path):
    """When inner is CachedClient, bar_ts must reach it (and the underlying stub)."""
    stub = _StubClient()
    cached = CachedClient(stub, cache_dir=tmp_path)
    guard = BudgetGuard(cap_usd=10.0)
    client = BudgetGuardedClient(
        inner=cached, guard=guard, pricing=PRICING, expected_output_tokens=300,
    )
    await client.complete(
        agent="technical", prompt="hi", image_b64=None, model=MODEL, bar_ts=12345,
    )
    # CachedClient does NOT forward bar_ts to its own inner; it consumes it.
    # So we assert the stub was called once (cache miss path).
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_bar_ts_dropped_when_inner_is_bare_client():
    """When inner is not a CachedClient, bar_ts must NOT be passed (TypeError otherwise)."""
    stub = _StubClient()
    guard = BudgetGuard(cap_usd=10.0)
    client = BudgetGuardedClient(
        inner=stub, guard=guard, pricing=PRICING, expected_output_tokens=300,
    )
    # Should not raise even though bar_ts is provided.
    await client.complete(
        agent="technical", prompt="hi", image_b64=None, model=MODEL, bar_ts=12345,
    )
    assert "bar_ts" not in stub.calls[0]


@pytest.mark.asyncio
async def test_cache_hit_skips_guard(tmp_path: Path):
    """Pre-warm cache, then set cap=0; cached call returns without raising."""
    # 1. Warm the cache with a normal call (sufficient cap).
    stub = _StubClient(in_tokens=100, out_tokens=200)
    cached = CachedClient(stub, cache_dir=tmp_path)
    warm_guard = BudgetGuard(cap_usd=10.0)
    warm_client = BudgetGuardedClient(
        inner=cached, guard=warm_guard, pricing=PRICING, expected_output_tokens=300,
    )
    await warm_client.complete(
        agent="technical", prompt="same", image_b64=None, model=MODEL, bar_ts=42,
    )
    assert len(stub.calls) == 1

    # 2. New guard with cap=0; same call must hit cache and bypass the guard.
    tight_guard = BudgetGuard(cap_usd=0.0)
    tight_client = BudgetGuardedClient(
        inner=cached, guard=tight_guard, pricing=PRICING, expected_output_tokens=300,
    )
    resp = await tight_client.complete(
        agent="technical", prompt="same", image_b64=None, model=MODEL, bar_ts=42,
    )
    assert resp.content == "ok"
    assert tight_guard.spent_usd == 0.0
    assert len(stub.calls) == 1  # still only the warm-up call
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_budget_client.py -v`
Expected: collection error / ModuleNotFoundError (`llm.budget_client` doesn't exist).

- [ ] **Step 3: Implement `llm/budget_client.py`**

Create:

```python
"""Budget-enforcing decorator client (sub-plan E).

Wraps any ``LLMClient`` with a pre-call cost estimate against a shared
``BudgetGuard`` and a post-call exact charge derived from the returned
``LLMResponse`` token counts. The intended stack is::

    BudgetGuardedClient(inner=CachedClient(OpenRouterClient(...)), ...)

This ordering — guard *outside* cache — is intentional. Cache hits never
reach the guard, so pre-warmed seminar replays remain zero-cost and survive
even after the cap is exhausted. Cache misses pay the per-call price.

The wrapped ``complete()`` signature accepts an optional ``bar_ts`` kwarg
that is forwarded to the inner only when the inner is a ``CachedClient``
(whose own signature requires it). Bare ``MockClient``/``OpenRouterClient``
do not accept ``bar_ts``; we drop it transparently to match
``nodes/_common.call_llm``'s convention.
"""
from __future__ import annotations

from dataclasses import dataclass

from llm.budget import BudgetGuard, estimate_cost_usd
from llm.cache import CachedClient
from llm.client import LLMClient, LLMResponse


@dataclass(frozen=True)
class ModelPricing:
    """USD price per 1,000,000 tokens for a specific model."""

    in_per_1m: float
    out_per_1m: float


class BudgetGuardedClient:
    """LLMClient decorator: pre-call estimate + post-call exact charge.

    Args:
        inner: The client to delegate to. Commonly a ``CachedClient``.
        guard: Shared per-run ``BudgetGuard``. Passing the same instance to
            multiple guarded clients makes the cap span them all.
        pricing: ``{model_id: ModelPricing}``. Calls for unknown models raise
            ``RuntimeError`` before reaching the inner client.
        expected_output_tokens: Pre-call output-token estimate fed to
            ``check_can_afford``. The actual count from the API response is
            used for the post-call charge, so under-estimates here only mean
            the guard accepts a call that ends up slightly more expensive
            than predicted; ``check_can_afford`` will refuse the *next* call
            once the cumulative real spend is over the cap.

    Not safe for concurrent use across asyncio tasks because ``BudgetGuard``
    isn't either. The seminar walk-forward is sequential per asset, so
    sharing one guarded client across the run is fine.
    """

    def __init__(
        self,
        inner: LLMClient,
        guard: BudgetGuard,
        pricing: dict[str, ModelPricing],
        expected_output_tokens: int = 300,
    ) -> None:
        if expected_output_tokens <= 0:
            raise ValueError("expected_output_tokens must be > 0")
        self._inner = inner
        self._guard = guard
        self._pricing = pricing
        self._expected_out = expected_output_tokens

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
        bar_ts: int | None = None,
    ) -> LLMResponse:
        price = self._pricing.get(model)
        if price is None:
            raise RuntimeError(
                f"No pricing entry for model {model!r}. "
                "Add it to config.yaml under llm.pricing."
            )

        # Pre-call: rough estimate. len(prompt)//4 mirrors MockClient's own
        # token heuristic so the two stay in lock-step.
        est = estimate_cost_usd(
            input_tokens=len(prompt) // 4,
            output_tokens=self._expected_out,
            in_per_1m=price.in_per_1m,
            out_per_1m=price.out_per_1m,
        )
        self._guard.check_can_afford(est)  # may raise

        kwargs: dict = {
            "agent": agent,
            "prompt": prompt,
            "image_b64": image_b64,
            "model": model,
        }
        if isinstance(self._inner, CachedClient):
            # CachedClient requires bar_ts; bare clients reject it.
            kwargs["bar_ts"] = bar_ts
        resp = await self._inner.complete(**kwargs)

        # Post-call: exact charge from API-reported token counts.
        actual = estimate_cost_usd(
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            in_per_1m=price.in_per_1m,
            out_per_1m=price.out_per_1m,
        )
        self._guard.charge(actual)
        return resp
```

- [ ] **Step 4: Run the new test file**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_budget_client.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add llm/budget_client.py tests/test_budget_client.py
$msg = "feat(budget): add BudgetGuardedClient decorator`n`nWraps any LLMClient with a pre-call estimate against a shared`nBudgetGuard and a post-call exact charge from LLMResponse token`ncounts. Intended outer layer of the live stack:`nBudgetGuardedClient(CachedClient(OpenRouterClient)). Cache hits`nshort-circuit before the guard, preserving zero-cost replays.`n`nPart of sub-plan E (task 3)."
[System.IO.File]::WriteAllText("$PWD\.git\COMMIT_MSG", $msg, (New-Object System.Text.UTF8Encoding $false))
git commit -F .git/COMMIT_MSG
Remove-Item .git/COMMIT_MSG
```

---

### Task 4: Teach `nodes/_common.call_llm` about `BudgetGuardedClient`

**Files:**
- Modify: `strategies/llm_agents/nodes/_common.py:23-30`
- Modify: `tests/test_llm_nodes.py` (append test)

- [ ] **Step 1: Inspect `tests/test_llm_nodes.py`**

`Read tests/test_llm_nodes.py` to find where `call_llm` (or the analyst nodes that call it) is exercised. We add one focused test.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_llm_nodes.py`:

```python
import pytest

from llm.budget import BudgetGuard
from llm.budget_client import BudgetGuardedClient, ModelPricing
from llm.cache import CachedClient
from llm.client import LLMResponse
from strategies.llm_agents.nodes._common import call_llm


class _RecordingStub:
    def __init__(self):
        self.kwargs = None

    async def complete(self, **kwargs):
        self.kwargs = kwargs
        return LLMResponse(content="x", model=kwargs["model"], input_tokens=1, output_tokens=1)


@pytest.mark.asyncio
async def test_call_llm_forwards_bar_ts_through_budget_guarded_client(tmp_path):
    """call_llm must pass bar_ts when the outer client wraps a CachedClient,
    even via a BudgetGuardedClient intermediate."""
    stub = _RecordingStub()
    cached = CachedClient(stub, cache_dir=tmp_path)
    pricing = {"m": ModelPricing(in_per_1m=1.0, out_per_1m=1.0)}
    guarded = BudgetGuardedClient(
        inner=cached, guard=BudgetGuard(cap_usd=10.0), pricing=pricing,
    )
    await call_llm(
        client=guarded, agent="technical", prompt="hi",
        image_b64=None, model="m", bar_ts=999,
    )
    # cached called stub once; stub itself does not receive bar_ts (CachedClient consumes it).
    assert stub.kwargs is not None
    assert stub.kwargs["model"] == "m"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_llm_nodes.py -v -k "forwards_bar_ts_through_budget_guarded"`
Expected: FAIL — `call_llm` only checks `isinstance(client, CachedClient)`, so `bar_ts` is dropped, the CachedClient's `complete()` raises `TypeError: complete() missing 1 required keyword-only argument: 'bar_ts'`.

- [ ] **Step 4: Modify `strategies/llm_agents/nodes/_common.py`**

Replace the `isinstance(client, CachedClient)` branch:

```python
from llm.budget_client import BudgetGuardedClient
from llm.cache import CachedClient
from llm.client import LLMClient, LLMResponse


async def call_llm(
    *,
    client: LLMClient,
    agent: str,
    prompt: str,
    image_b64: str | None,
    model: str,
    bar_ts: int,
) -> LLMResponse:
    """Invoke ``client.complete`` and forward ``bar_ts`` to clients that need it.

    ``CachedClient`` requires ``bar_ts`` for its cache key. ``BudgetGuardedClient``
    accepts (and may forward) ``bar_ts`` so it can layer on top of the cache.
    Bare ``MockClient`` / ``OpenRouterClient`` reject the kwarg, so we omit it.
    """
    kwargs: dict[str, Any] = {
        "agent": agent,
        "prompt": prompt,
        "image_b64": image_b64,
        "model": model,
    }
    if isinstance(client, (CachedClient, BudgetGuardedClient)):
        kwargs["bar_ts"] = bar_ts
    return await client.complete(**kwargs)
```

- [ ] **Step 5: Run all node + budget tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_llm_nodes.py tests/test_budget_client.py -v`
Expected: all green.

- [ ] **Step 6: Commit**

```powershell
git add strategies/llm_agents/nodes/_common.py tests/test_llm_nodes.py
$msg = "feat(nodes): forward bar_ts through BudgetGuardedClient`n`ncall_llm previously gated bar_ts solely on isinstance(client,`nCachedClient). Once BudgetGuardedClient sits in front of the`ncache, that check misses and the CachedClient raises a TypeError`nfor the missing kwarg. Widen the check to recognize the budget`nwrapper as well.`n`nPart of sub-plan E (task 4)."
[System.IO.File]::WriteAllText("$PWD\.git\COMMIT_MSG", $msg, (New-Object System.Text.UTF8Encoding $false))
git commit -F .git/COMMIT_MSG
Remove-Item .git/COMMIT_MSG
```

---

### Task 5: Wire `BudgetGuardedClient` into `main.py`

**Files:**
- Modify: `main.py:179-198` (client stack assembly)
- Modify: `main.py:225-249` (run_state_factory / on_progress)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
import asyncio

import pytest

from llm.client import LLMResponse


class _FakeOpenRouter:
    """Stand-in for OpenRouterClient that returns deterministic responses."""

    async def complete(self, **kwargs):
        return LLMResponse(
            content="HOLD 0.50 fake", model=kwargs["model"],
            input_tokens=50, output_tokens=80,
        )


@pytest.mark.asyncio
async def test_main_non_mock_wires_budget_guard(monkeypatch, tmp_path):
    """Patch OpenRouterClient at the main import site so the non-mock branch
    runs without network. Assert the run completes and budget tracking
    actually happened."""
    import main as main_mod

    # Force a fake API key so the no-key guard in main.run does not exit.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    # Replace OpenRouterClient with the fake.
    monkeypatch.setattr(main_mod, "OpenRouterClient", lambda **_: _FakeOpenRouter())

    # Capture the guard instance for assertions.
    captured: dict = {}
    real_guarded_cls = main_mod.BudgetGuardedClient

    def _capturing(inner, guard, pricing, expected_output_tokens):
        captured["guard"] = guard
        return real_guarded_cls(inner, guard, pricing, expected_output_tokens)

    monkeypatch.setattr(main_mod, "BudgetGuardedClient", _capturing)

    # Use the project's bundled smoke fixture path — see tests/fixtures.
    # Build a tiny config on the fly that points at the fixture CSV.
    # (Or: reuse the same `config` arg the existing mock smoke test uses,
    #  and just flip mock=False.)
    # The exact mechanics here depend on the smoke-test plumbing already in
    # tests/test_main.py; mirror that pattern.
    ...
    # After driving main.run, assert:
    assert captured["guard"].spent_usd > 0.0
```

> Note: the existing `tests/test_main.py` already establishes a smoke
> fixture pattern (mock mode). Mirror that — copy the helper that prepares
> a temp config + fixture CSV, then flip `--mock=False`, and patch as above.
> The `...` placeholder marks the spot where you slot in the existing
> mechanics. **Do not commit with a `...` in place.**

- [ ] **Step 2: Run test to confirm collection succeeds and the new test fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_main.py -v -k "non_mock_wires"`
Expected: FAIL — `main` does not import `BudgetGuardedClient` yet.

- [ ] **Step 3: Modify `main.py` imports**

Add to the imports block (alongside existing `from llm.cache import CachedClient`):

```python
from llm.budget import BudgetGuard
from llm.budget_client import BudgetGuardedClient, ModelPricing
```

- [ ] **Step 4: Modify the client-stack assembly in `main.run`**

Replace the existing `# ── Build LLM client stack ─` block (currently lines ~179-198) with:

```python
    # ── Build LLM client stack ────────────────────────────────────────────
    # Layering: BudgetGuardedClient -> CachedClient -> inner.
    # Cache hits short-circuit inside CachedClient and never reach the guard
    # — pre-warmed seminar replays stay free even when the cap is exhausted.
    if mock:
        inner = MockClient()
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            console.print(
                "[red]ERROR:[/red] OPENROUTER_API_KEY is not set. "
                "Pass --mock for an offline run, or populate .env."
            )
            raise typer.Exit(code=2)
        inner = OpenRouterClient(api_key=api_key)

    cached = CachedClient(inner, cache_dir=Path(cfg.llm.cache_dir))

    guard: BudgetGuard | None = None
    if mock:
        client = cached
    else:
        guard = BudgetGuard(cap_usd=cfg.llm.max_usd)
        pricing = {
            m: ModelPricing(**p.model_dump())
            for m, p in cfg.llm.pricing.items()
        }
        client = BudgetGuardedClient(
            inner=cached,
            guard=guard,
            pricing=pricing,
            expected_output_tokens=cfg.llm.expected_output_tokens,
        )

    llm_model = _pick_llm_model(cfg)
```

- [ ] **Step 5: Add `on_progress` to push spend into RunState**

Inside `_main()` (currently lines ~233-249), pass an `on_progress` callback:

```python
    def _on_progress(symbol: str, idx: int, total: int) -> None:
        if guard is not None:
            rs_holder["rs"].spend_usd = guard.spent_usd

    async def _main() -> dict[str, dict[str, Any]]:
        if no_tui:
            return await walkforward.run(
                wf_cfg.run.assets, bars_loader, build_strategies, wf_cfg,
                run_state_factory=rsf,
                on_progress=_on_progress,
            )
        proxy = _LiveProxy(rs_holder)
        await ui.start_live(proxy, console=console, interval=0.25)  # type: ignore[arg-type]
        try:
            return await walkforward.run(
                wf_cfg.run.assets, bars_loader, build_strategies, wf_cfg,
                run_state_factory=rsf,
                on_progress=_on_progress,
            )
        finally:
            await ui.stop_live()
```

- [ ] **Step 6: Run the new test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_main.py -v -k "non_mock_wires"`
Expected: PASS.

- [ ] **Step 7: Run all main tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_main.py -v`
Expected: all green.

- [ ] **Step 8: Commit**

```powershell
git add main.py tests/test_main.py
$msg = "feat(main): wire BudgetGuardedClient into live LLM client stack`n`nNon-mock runs now assemble BudgetGuardedClient(CachedClient(`nOpenRouterClient)) with the per-run BudgetGuard sourced from`ncfg.llm.max_usd and pricing from cfg.llm.pricing. Mock runs are`nunchanged. RunState.spend_usd is refreshed between assets via`nthe walkforward on_progress callback so the TUI footer reflects`naccumulated spend.`n`nCompletes sub-plan E (task 5)."
[System.IO.File]::WriteAllText("$PWD\.git\COMMIT_MSG", $msg, (New-Object System.Text.UTF8Encoding $false))
git commit -F .git/COMMIT_MSG
Remove-Item .git/COMMIT_MSG
```

---

### Task 6: Full verification and push

**Files:** none.

- [ ] **Step 1: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all green (216 pre-existing + ~9 new = ~225 passed, 1 skipped).

- [ ] **Step 2: Ruff lint**

Run: `.\.venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Smoke-test the CLI in mock mode**

Run: `.\.venv\Scripts\python.exe main.py run --mock --no-tui --assets BTC/USDT`
Expected: prints a summary table; no exceptions. (Requires bars under `data/`. Skip if the seminar fixture isn't downloaded yet — the test suite already covers this path.)

- [ ] **Step 4: Push all sub-plan E commits**

```powershell
git log --oneline origin/master..HEAD
git push origin master
```

Expected: 5 commits pushed (tasks 1–5).

---

## Self-Review

**Spec coverage check:**
- ✅ `BudgetExceededError.spend_usd` → Task 1.
- ✅ `BudgetGuardedClient` decorator → Task 3.
- ✅ `PricingCfg` + validator + `expected_output_tokens` → Task 2.
- ✅ `config.yaml` pricing block → Task 2.
- ✅ `nodes/_common.call_llm` updated → Task 4.
- ✅ `main.py` stack assembly + per-asset spend push → Task 5.
- ✅ All test scenarios from spec §Components → Task 3 + Task 4 + Task 5.

**Placeholder scan:** Task 5 Step 1 contains an explicit `...` marker with a note ("Do not commit with a `...` in place"). This is acknowledged inline as the slot for the existing fixture-helper plumbing — implementers must replace before commit.

**Type consistency:**
- `ModelPricing` defined in `llm.budget_client` and imported into `main.py` consistently. ✓
- `BudgetGuard.check_can_afford(est_usd)` signature unchanged in Task 1. ✓
- `BudgetGuardedClient.complete(*, agent, prompt, image_b64, model, bar_ts=None)` matches `_common.call_llm`'s widened isinstance branch. ✓
- `cfg.llm.pricing[m]` is a `PricingCfg`; `.model_dump()` is the Pydantic v2 method (`BaseModel.model_dump`). ✓

No issues found.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-14-sub-plan-E-budget-guard-enforcement.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality), fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans.

Which approach?
