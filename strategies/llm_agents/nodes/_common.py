"""Helpers shared by all analyst nodes."""
from __future__ import annotations

from typing import Any

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
    """Invoke ``client.complete`` and forward ``bar_ts`` iff the client is a
    ``CachedClient`` (whose signature requires it). All other ``LLMClient``
    implementations are unaware of bar timing.
    """
    kwargs: dict[str, Any] = {
        "agent": agent,
        "prompt": prompt,
        "image_b64": image_b64,
        "model": model,
    }
    if isinstance(client, CachedClient):
        kwargs["bar_ts"] = bar_ts
    return await client.complete(**kwargs)
