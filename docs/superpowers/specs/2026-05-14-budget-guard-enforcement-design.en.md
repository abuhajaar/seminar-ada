# Spec: Budget Guard Enforcement — Live OpenRouter Safety Net

**Date:** 2026-05-14
**Status:** Approved
**Supersedes:** Sub-plan C tech debt item "BudgetGuard not wired"

## Problem

`llm.max_usd` in `config.yaml` is currently a comment. `BudgetGuard` exists in
`llm/budget.py` and is unit-tested, but no production code path instantiates
it. A live OpenRouter run can therefore exceed the configured cap without any
circuit breaker. Mock-mode runs are unaffected because `MockClient` makes no
network calls, but the seminar demo will use the real OpenRouter API and
needs the cap to be real.

`BudgetExceededError` carries only a string message; `core/walkforward.py:112`
already uses `getattr(e, "spend_usd", None) or 0.0` defensively, but the
attribute is never set, so the recorded `spend_usd` is always `0.0`.

## Goal

Make `llm.max_usd` a real per-run dollar ceiling for live OpenRouter calls
while keeping cached replays free, mock mode untouched, and the rest of the
engine / strategy code unchanged.

## Non-Goals

- Streaming `RunState.spend_usd` during a single asset's engine run. The TUI
  footer is updated once per asset (between assets) from `guard.spent_usd`.
  Within-asset streaming would require threading the guard ref into the
  engine or `RunState` and is out of scope here.
- Exact tokenization via `tiktoken` or a per-model tokenizer. The heuristic
  `len(prompt) // 4` is sufficient at the seminar scale.
- Image-token cost accounting. The Visual node will under-charge by the
  image overhead, which is acceptable at a $10 cap.
- Tracking refunded or partial-failure billing. OpenRouter charges per
  successful response; we follow that convention.

## Architecture

Add a third decorator layer to the LLM client stack:

```
BudgetGuardedClient   ← NEW: pre-call estimate + post-call charge
  └── CachedClient    ← unchanged; cache hits short-circuit before guard
        └── OpenRouterClient | MockClient
```

The guard wraps the cache (not the inverse). This means:

- **Cache misses** flow through the guard → cache → inner. Both
  `check_can_afford` (pre) and `charge` (post) run.
- **Cache hits** are served by `CachedClient` itself; `BudgetGuardedClient`
  never sees them. Cached replays remain free even after the cap is hit.

This ordering is *intentional* and is the seminar-replay invariant: a
pre-warmed cache must be playable offline at zero cost.

## Components

### `llm/budget.py` (modify)

`BudgetExceededError` gains a `spend_usd: float` attribute:

```python
class BudgetExceededError(RuntimeError):
    def __init__(self, message: str, *, spend_usd: float = 0.0) -> None:
        super().__init__(message)
        self.spend_usd = spend_usd
```

`BudgetGuard.check_can_afford` raises with `spend_usd=self._spent` so callers
get the cumulative spend at the moment of refusal.

### `llm/budget_client.py` (new)

Decorator client wrapping any `LLMClient`. Implements `complete()` with the
same signature as `CachedClient.complete()` (i.e. accepts an optional
`bar_ts` kwarg forwarded to the inner only if the inner is a `CachedClient`).

```python
@dataclass(frozen=True)
class ModelPricing:
    in_per_1m: float
    out_per_1m: float

class BudgetGuardedClient:
    def __init__(
        self,
        inner: LLMClient,
        guard: BudgetGuard,
        pricing: dict[str, ModelPricing],
        expected_output_tokens: int = 300,
    ) -> None: ...

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
            raise RuntimeError(f"No pricing entry for model {model!r}")
        est = estimate_cost_usd(
            input_tokens=len(prompt) // 4,
            output_tokens=self._expected_out,
            in_per_1m=price.in_per_1m,
            out_per_1m=price.out_per_1m,
        )
        self._guard.check_can_afford(est)
        kwargs = {"agent": agent, "prompt": prompt, "image_b64": image_b64, "model": model}
        if isinstance(self._inner, CachedClient):
            kwargs["bar_ts"] = bar_ts
        resp = await self._inner.complete(**kwargs)
        actual = estimate_cost_usd(
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            in_per_1m=price.in_per_1m,
            out_per_1m=price.out_per_1m,
        )
        self._guard.charge(actual)
        return resp
```

The `_common.call_llm` helper already handles `isinstance(client, CachedClient)`
to decide whether to pass `bar_ts`. Because `BudgetGuardedClient` is NOT a
`CachedClient` but wraps one, `call_llm` will NOT pass `bar_ts` through the
top-level guard call. We therefore add a parallel `isinstance` branch in
`call_llm`: if the client is a `BudgetGuardedClient`, also forward `bar_ts`.
Tests cover this.

### `core/config.py` (modify)

New `PricingCfg` and additions to `LlmCfg`:

```python
class PricingCfg(BaseModel):
    in_per_1m: float = Field(ge=0)
    out_per_1m: float = Field(ge=0)

class LlmCfg(BaseModel):
    # ... existing fields ...
    pricing: dict[str, PricingCfg]
    expected_output_tokens: int = 300

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

The existing `_weights_sum_to_one` validator stays; both validators run.

### `config.yaml` (modify)

Add a `pricing` block keyed by model id, and an `expected_output_tokens`
value:

```yaml
llm:
  # ... existing fields ...
  expected_output_tokens: 300
  pricing:
    anthropic/claude-3.5-sonnet:
      in_per_1m: 3.00
      out_per_1m: 15.00
```

Numbers reflect Anthropic's published Claude 3.5 Sonnet pricing on
OpenRouter. The user is responsible for updating these if pricing changes
before the seminar.

### `main.py` (modify)

Replace the client-stack assembly in `run()`:

```python
cached = CachedClient(inner, cache_dir=Path(cfg.llm.cache_dir))
if mock:
    client = cached
    guard = None
else:
    guard = BudgetGuard(cap_usd=cfg.llm.max_usd)
    pricing = {m: ModelPricing(**p.model_dump()) for m, p in cfg.llm.pricing.items()}
    client = BudgetGuardedClient(
        inner=cached,
        guard=guard,
        pricing=pricing,
        expected_output_tokens=cfg.llm.expected_output_tokens,
    )
```

Between assets (after `walkforward.run` returns or raises), update the live
RunState's `spend_usd`:

```python
if guard is not None:
    rs_holder["rs"].spend_usd = guard.spent_usd
```

The simplest place to do this is via a small per-asset progress callback
passed to `walkforward.run` (the runner already supports `on_progress`).

### Tests

**New: `tests/test_budget_client.py`**

1. `test_under_budget_charges_actual` — cap=10.0, inner returns 100 in /
   200 out tokens; assert `guard.spent_usd ≈ estimate_cost_usd(100, 200)`.
2. `test_pre_call_check_uses_estimate` — set cap just below estimated cost;
   assert `BudgetExceededError` raised and inner never awaited.
3. `test_budget_exceeded_carries_spend_usd` — assert `e.spend_usd` equals
   `guard.spent_usd` at refusal time (zero for first call, prior charges
   accumulated for later calls).
4. `test_unknown_model_raises_runtime_error` — model absent from pricing.
5. `test_bar_ts_forwarded_to_cached_inner` — when inner is a
   `CachedClient`, `bar_ts` reaches the inner client; when inner is a bare
   client, `bar_ts` is dropped.
6. `test_cache_hit_skips_guard` — set cap=0.0, pre-populate the cache
   directory with a response file, assert subsequent call returns cached
   value without raising and `guard.spent_usd == 0.0`. (Verifies the
   guard-wraps-cache ordering.)
7. `test_call_llm_forwards_bar_ts_to_budget_guarded_client` — update for
   the parallel isinstance check in `nodes/_common.call_llm`.

**Modified: `tests/test_main.py`**

8. `test_main_runs_with_budget_guard` — exercise the non-mock path with a
   stub `OpenRouterClient` that returns deterministic `LLMResponse`s; run
   2 assets; assert exit 0 and `guard.spent_usd > 0`.

**Modified: `tests/test_budget.py`**

9. `test_budget_exceeded_error_has_spend_usd` — direct test on
   `BudgetExceededError`.

**Modified: `tests/test_config.py`**

10. `test_config_rejects_agent_without_pricing` — load a config where the
    `decision` agent's model is missing from `pricing`; assert `ValueError`
    with the expected message.

All existing tests continue to pass unmodified.

## Failure modes

| Scenario | Behavior |
|---|---|
| Cap hit pre-call | `check_can_afford` raises `BudgetExceededError(spend_usd=guard.spent_usd)`; engine raises out of `run_async`; walkforward catches and records `{"status": "budget_exceeded", "spend_usd": ...}`; continues to next asset. Earlier assets keep their `trades.csv` / `equity.csv`. |
| Cap hit mid-asset (between calls) | Same path. The asset's *current* portfolios are abandoned (engine raised before returning), so partial trades are not persisted for that asset. |
| Cache hit when cap already exhausted | Returns the cached response. By design — pre-warmed seminar replays are zero-cost. |
| Unknown model at runtime | Impossible: `LlmCfg._every_agent_model_priced` rejects misconfig at `load_config`. |
| `cfg.llm.max_usd = 0.0` | First non-cached call raises immediately. Tests at this boundary. |
| Inner client raises (HTTP error) | Bubbles up past the guard *without* charging — `charge` runs only on successful response. Subsequent calls retain full remaining budget. |

## Spec — Indonesian companion

See `2026-05-14-budget-guard-enforcement-design.id.md`.
