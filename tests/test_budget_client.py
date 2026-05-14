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
    # Cap admits the first call's pre-call estimate (~0.0045) but the
    # second call sees spent=0.0033 + est=0.0045 > cap and is refused.
    guard = BudgetGuard(cap_usd=0.005)
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
