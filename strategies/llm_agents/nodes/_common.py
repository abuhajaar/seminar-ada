"""Helpers shared by all analyst nodes."""
from __future__ import annotations

from typing import Any

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
    accepts ``bar_ts`` and forwards it to its inner cache, so we must include it
    when the budget wrapper is on top of the cache. Bare ``MockClient`` /
    ``OpenRouterClient`` reject the kwarg, so we omit it for them.
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
