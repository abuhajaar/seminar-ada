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
