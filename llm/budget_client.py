"""Budget-enforcing decorator client (sub-plan E).

Wraps any ``LLMClient`` with a pre-call cost estimate against a shared
``BudgetGuard`` and a post-call exact charge derived from the returned
``LLMResponse`` token counts. The intended stack is::

    BudgetGuardedClient(inner=CachedClient(OpenRouterClient(...)), ...)

This ordering — guard *outside* cache — is intentional. Cache hits never
reach the guard, so pre-warmed seminar replays remain zero-cost and survive
even after the cap is exhausted. Cache misses pay the per-call price.

When the inner is a ``CachedClient``, this decorator peeks the cache before
running ``check_can_afford``. A hit returns immediately and bypasses both
the estimate gate and the post-call charge, preserving the zero-cost replay
guarantee. A miss falls through to the normal guard-estimate / inner-call /
charge sequence; the subsequent ``CachedClient.complete()`` will see the
same cache miss and proceed to fetch.

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

    def _cache_hit(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
        bar_ts: int | None,
    ) -> LLMResponse | None:
        """Return cached response if the inner is a CachedClient with a hit.

        Returns None for any other situation (bare inner, missing bar_ts,
        cache miss, or corrupt cache file). Delegates to the public
        ``CachedClient.peek()`` so cache-key and on-disk-layout details
        stay encapsulated in ``llm/cache.py``.
        """
        if not isinstance(self._inner, CachedClient) or bar_ts is None:
            return None
        return self._inner.peek(
            agent=agent,
            prompt=prompt,
            image_b64=image_b64,
            model=model,
            bar_ts=bar_ts,
        )

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

        # Cache-hit short-circuit: zero cost, zero guard interaction. This
        # preserves the replay guarantee even when the cap is exhausted.
        cached = self._cache_hit(
            agent=agent, prompt=prompt, image_b64=image_b64,
            model=model, bar_ts=bar_ts,
        )
        if cached is not None:
            return cached

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
