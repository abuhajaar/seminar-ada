"""Bar-keyed JSON cache for LLM responses (spec §6 layout, spec Q2 key).

Key = sha256(model || agent || sha256(prompt) || sha256(image_b64) || bar_ts).
File layout: <cache_dir>/<model_safe>/<agent>/<key>.json.

The wrapped `complete()` signature gains a required `bar_ts` kwarg used in the
cache key. This means cached calls are deterministic and replayable per bar,
which the seminar replay path depends on (zero LLM calls, zero cost).
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
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
    """Sanitize a model identifier for use as a directory name."""
    return model.replace("/", "_").replace(":", "_").replace("\\", "_")


class CachedClient:
    """Decorator over any LLMClient that persists responses to disk.

    The wrapped `complete()` adds a required `bar_ts` kwarg used in the cache
    key per spec Q2 (deterministic-by-bar caching).
    """

    def __init__(self, inner: LLMClient, cache_dir: Path | str) -> None:
        self._inner = inner
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        # Single global lock: simple + correct. Serializes only on misses; hits
        # bypass the lock entirely. If parallel-bar replays ever profile-bound
        # here, switch to a per-key lock dict.
        self._lock = asyncio.Lock()

    def _path_for(self, *, model: str, agent: str, key: str) -> Path:
        # `agent` is expected pre-lowercased by the caller (normalized once in
        # `complete()`), so no `.lower()` here.
        sub = self._dir / _safe_model(model) / agent
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{key}.json"

    @staticmethod
    def _try_read(path: Path) -> LLMResponse | None:
        """Read a cache file; return None if missing or corrupt JSON.

        Corrupt files (e.g. from a crash mid-write) are treated as a miss so
        the caller refetches and overwrites cleanly.
        """
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            # Bad file — drop it and treat as a miss.
            with contextlib.suppress(OSError):
                path.unlink()
            return None
        return LLMResponse(**obj)

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
        bar_ts: int,
    ) -> LLMResponse:
        # Normalize agent casing exactly once. Downstream (cache_key, _path_for)
        # uses this value as-is so the key and the on-disk path agree.
        agent = agent.lower()
        key = cache_key(
            model=model, agent=agent, prompt=prompt, image_b64=image_b64, bar_ts=bar_ts
        )
        path = self._path_for(model=model, agent=agent, key=key)

        if path.exists():
            cached = self._try_read(path)
            if cached is not None:
                return cached

        async with self._lock:
            # Double-check under the lock to avoid duplicate work across awaits.
            if path.exists():
                cached = self._try_read(path)
                if cached is not None:
                    return cached
            resp = await self._inner.complete(
                agent=agent, prompt=prompt, image_b64=image_b64, model=model
            )
            # Atomic write: temp file on the same volume + os.replace ensures
            # readers see either the previous absence or the complete new file
            # — no partial reads even if we crash mid-write.
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(resp), indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return resp
