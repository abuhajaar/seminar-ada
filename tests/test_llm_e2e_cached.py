"""End-to-end integration: CachedClient + BudgetGuard + LLMAgentStrategy.

Validates the spec's two big promises for the seminar replay:
1. A cached LLM run is **zero-cost** — no calls to the underlying client.
2. A cached LLM run is **deterministic** — identical Signal across passes.

The first pass populates the cache by running the strategy with MockClient.
The second pass replaces the inner client with a `BoomClient` that explodes
on any call, so a successful replay proves every LLM hop was served by the
on-disk cache.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.types import Bar
from llm.budget import BudgetExceededError, BudgetGuard
from llm.cache import CachedClient
from llm.client import LLMResponse, MockClient
from strategies.base import Context
from strategies.llm_agents.strategy import WARMUP_BARS, LLMAgentStrategy


def _bars(n: int) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(
            timestamp=start + timedelta(hours=i),
            open=50_000.0 + i * 5,
            high=50_100.0 + i * 5,
            low=49_900.0 + i * 5,
            close=50_050.0 + i * 5,
            volume=1.0,
            taker_buy_volume=0.5,
            cvd=10.0 * i,
            cvd_delta=10.0,
        )
        for i in range(n)
    ]


def _ctx() -> Context:
    return Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.01, in_position=False)


class _BoomClient:
    """Asserts that every `.complete(...)` is a cache hit upstream of it."""

    async def complete(self, **kwargs: object) -> LLMResponse:  # noqa: ARG002
        raise AssertionError(
            "BoomClient.complete called — cache should have served this request"
        )


@pytest.mark.asyncio
async def test_cached_strategy_replay_is_zero_cost_and_deterministic(tmp_path: Path) -> None:
    """One bar past warmup -> 3 analyst calls -> 3 cache files -> zero calls on replay.

    `_bars(WARMUP_BARS)` produces exactly ``WARMUP_BARS`` bars. The warmup gate
    returns HOLD without invoking the graph while ``len(self._bars) < WARMUP_BARS``,
    so bars 1..WARMUP_BARS-1 are gated and the LAST bar is the first to invoke
    the graph -> exactly one graph invocation -> one cache file per analyst.
    """
    bars = _bars(WARMUP_BARS)

    # First pass: populates cache.
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    strat = LLMAgentStrategy(
        client=cached,
        model="mock",
        image_window_bars=20,
        render_image=False,
    )
    last_sig = None
    for b in bars:
        last_sig = await strat.on_bar(b, _ctx())
    assert last_sig is not None

    # Exactly one graph invocation happened (the bar past warmup), producing
    # one cache file per analyst (decision is deterministic and not cached).
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 3, f"expected 3 cache files, got {len(files)}: {files}"
    agents_with_cache = {p.parent.name for p in files}
    assert agents_with_cache == {"technical", "visual", "qabba"}

    # Second pass: replace the inner with BoomClient. Identical Bar objects
    # (same timestamps) yield identical cache keys, so the replay must be
    # served entirely from disk.
    cached2 = CachedClient(inner=_BoomClient(), cache_dir=tmp_path)
    strat2 = LLMAgentStrategy(
        client=cached2,
        model="mock",
        image_window_bars=20,
        render_image=False,
    )
    last_sig2 = None
    for b in bars:
        last_sig2 = await strat2.on_bar(b, _ctx())
    assert last_sig2 is not None

    # Determinism: same action, same confidence, same rationale.
    assert last_sig.action is last_sig2.action
    assert last_sig.confidence == pytest.approx(last_sig2.confidence)
    assert last_sig.reasoning == last_sig2.reasoning


@pytest.mark.asyncio
async def test_cached_strategy_no_extra_cache_files_on_replay(tmp_path: Path) -> None:
    """Replay must not write additional cache files — pure read-through."""
    bars = _bars(WARMUP_BARS)

    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    strat = LLMAgentStrategy(client=cached, model="mock", render_image=False)
    for b in bars:
        await strat.on_bar(b, _ctx())

    files_after_first = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.json"))
    mtimes_first = {p: (tmp_path / p).stat().st_mtime_ns for p in files_after_first}

    # Replay with BoomClient.
    cached2 = CachedClient(inner=_BoomClient(), cache_dir=tmp_path)
    strat2 = LLMAgentStrategy(client=cached2, model="mock", render_image=False)
    for b in bars:
        await strat2.on_bar(b, _ctx())

    files_after_second = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.json"))
    assert files_after_first == files_after_second, "replay wrote new cache files"
    for p in files_after_second:
        # mtime equality is reliable here (not subject to NTFS 100ns rounding)
        # because the cache hit path performs ZERO writes — it returns the
        # decoded payload before reaching any write call. If this assertion
        # ever fails, that means someone introduced a write-through on the hit
        # path, not a timing flake.
        assert (tmp_path / p).stat().st_mtime_ns == mtimes_first[p], (
            f"replay rewrote {p}; cache should be read-only on hit"
        )


def test_budget_guard_aborts_before_call() -> None:
    """Spec §9: pre-call check refuses the next call once the cap is reached."""
    g = BudgetGuard(cap_usd=0.001)
    g.charge(0.001)
    with pytest.raises(BudgetExceededError):
        g.check_can_afford(0.0001)


def test_budget_guard_allows_calls_under_cap() -> None:
    """Pre-call check is permissive while the running total stays under the cap."""
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.5)
    # Should NOT raise — 0.5 + 0.4 < 1.0.
    g.check_can_afford(0.4)


class _StrongBuyClient:
    """All three analysts return BUY @ 0.95 -> weighted sum 0.95 > 0.50 -> BUY.

    Forces the decision node into a non-HOLD branch so determinism assertions
    cover the interesting code path, not just the HOLD-floor fallback.
    """

    async def complete(
        self,
        *,
        agent: str,  # noqa: ARG002
        prompt: str,  # noqa: ARG002
        image_b64: str | None,  # noqa: ARG002
        model: str,
    ) -> LLMResponse:
        return LLMResponse(
            content="BUY 0.95 strong-buy",
            model=model,
            input_tokens=1,
            output_tokens=1,
        )


@pytest.mark.asyncio
async def test_cached_replay_is_deterministic_on_buy_path(tmp_path: Path) -> None:
    """Replay determinism must hold on a BUY decision, not just HOLD.

    Uses a fixed-output client whose analysts unanimously return BUY @ 0.95;
    the weighted-consensus guardrail then yields BUY @ 0.95 (well above the
    0.50 threshold). The replay through BoomClient must reproduce the exact
    same Signal — same action, same confidence, same rationale string.
    """
    bars = _bars(WARMUP_BARS)

    cached = CachedClient(inner=_StrongBuyClient(), cache_dir=tmp_path)
    strat = LLMAgentStrategy(client=cached, model="strong", render_image=False)
    sig1 = None
    for b in bars:
        sig1 = await strat.on_bar(b, _ctx())
    assert sig1 is not None
    # Exercise the BUY branch (not the HOLD floor).
    from core.types import Action

    assert sig1.action is Action.BUY
    assert sig1.confidence == pytest.approx(0.95)

    # Replay with BoomClient: cache must serve every analyst call.
    cached2 = CachedClient(inner=_BoomClient(), cache_dir=tmp_path)
    strat2 = LLMAgentStrategy(client=cached2, model="strong", render_image=False)
    sig2 = None
    for b in bars:
        sig2 = await strat2.on_bar(b, _ctx())
    assert sig2 is not None

    assert sig2.action is Action.BUY
    assert sig2.confidence == pytest.approx(sig1.confidence)
    assert sig2.reasoning == sig1.reasoning
