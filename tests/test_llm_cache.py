"""Tests for llm.cache: bar-keyed JSON cache decorator (spec §6, Q2)."""
from __future__ import annotations

import json
from pathlib import Path

from llm.cache import CachedClient, cache_key
from llm.client import LLMResponse, MockClient


def test_cache_key_stable_for_same_inputs():
    k1 = cache_key(model="m", agent="technical", prompt="abc", image_b64=None, bar_ts=123)
    k2 = cache_key(model="m", agent="technical", prompt="abc", image_b64=None, bar_ts=123)
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex digest length


def test_cache_key_changes_with_model():
    k1 = cache_key(model="a", agent="technical", prompt="x", image_b64=None, bar_ts=1)
    k2 = cache_key(model="b", agent="technical", prompt="x", image_b64=None, bar_ts=1)
    assert k1 != k2


def test_cache_key_changes_with_agent():
    k1 = cache_key(model="m", agent="technical", prompt="x", image_b64=None, bar_ts=1)
    k2 = cache_key(model="m", agent="qabba", prompt="x", image_b64=None, bar_ts=1)
    assert k1 != k2


def test_cache_key_changes_with_prompt():
    k1 = cache_key(model="m", agent="technical", prompt="abc", image_b64=None, bar_ts=1)
    k2 = cache_key(model="m", agent="technical", prompt="xyz", image_b64=None, bar_ts=1)
    assert k1 != k2


def test_cache_key_changes_with_image():
    k1 = cache_key(model="m", agent="visual", prompt="x", image_b64=None, bar_ts=1)
    k2 = cache_key(model="m", agent="visual", prompt="x", image_b64="AAAA", bar_ts=1)
    assert k1 != k2


def test_cache_key_changes_with_bar_ts():
    k1 = cache_key(model="m", agent="technical", prompt="x", image_b64=None, bar_ts=1)
    k2 = cache_key(model="m", agent="technical", prompt="x", image_b64=None, bar_ts=2)
    assert k1 != k2


async def test_cached_client_writes_file_on_miss(tmp_path: Path):
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1_700_000_000_000,
    )
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1


async def test_cached_client_returns_identical_response_on_hit(tmp_path: Path):
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    r1 = await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1_700_000_000_000,
    )
    r2 = await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1_700_000_000_000,
    )
    assert r1 == r2  # frozen dataclass equality


async def test_cached_client_hit_does_not_call_inner(tmp_path: Path):
    """On cache hit, the wrapped client must NOT be invoked."""
    # Populate cache
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    r1 = await cached.complete(
        agent="qabba",
        prompt="cvd_delta=1000",
        image_b64=None,
        model="mock",
        bar_ts=42,
    )

    # Replace inner with a Boom client — any call raises
    class Boom:
        async def complete(self, **kwargs):
            raise AssertionError("inner client must not be called on cache hit")

    cached2 = CachedClient(inner=Boom(), cache_dir=tmp_path)
    r2 = await cached2.complete(
        agent="qabba",
        prompt="cvd_delta=1000",
        image_b64=None,
        model="mock",
        bar_ts=42,
    )
    assert r2.content == r1.content
    assert r2.model == r1.model


async def test_cached_client_writes_valid_json_with_all_fields(tmp_path: Path):
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
    assert set(obj.keys()) == {"content", "model", "input_tokens", "output_tokens"}
    assert isinstance(obj["content"], str)
    assert isinstance(obj["model"], str)
    assert isinstance(obj["input_tokens"], int)
    assert isinstance(obj["output_tokens"], int)


async def test_cached_client_layout_model_agent_subdirs(tmp_path: Path):
    """Files live under <cache_dir>/<model_safe>/<agent>/<key>.json (spec §6 layout)."""
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="anthropic/claude-3.5-sonnet",
        bar_ts=1,
    )
    # forward slash in model name must be sanitized
    matches = list(tmp_path.glob("anthropic_claude-3.5-sonnet/technical/*.json"))
    assert len(matches) == 1


async def test_cached_client_different_bar_ts_creates_separate_entries(tmp_path: Path):
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    for ts in (1, 2, 3):
        await cached.complete(
            agent="technical",
            prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
            image_b64=None,
            model="mock",
            bar_ts=ts,
        )
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 3


async def test_cached_client_treats_corrupt_json_as_miss(tmp_path: Path):
    """If a cache file exists but is unreadable JSON, treat it as a miss and
    overwrite with a fresh result. Guards against crash-time partial writes."""
    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    # Populate cache cleanly
    await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1,
    )
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    # Corrupt the file
    files[0].write_text("{ this is not valid json", encoding="utf-8")
    # Next call must succeed (refetch) and overwrite cleanly
    r = await cached.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None,
        model="mock",
        bar_ts=1,
    )
    assert "BUY" in r.content.upper()
    # File should now be valid JSON again
    import json
    obj = json.loads(files[0].read_text(encoding="utf-8"))
    assert "content" in obj


# --- peek() ----------------------------------------------------------------


class _CountingMock:
    """MockClient-like stub that records call count for peek tests."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, **kwargs):
        from llm.client import LLMResponse
        self.calls += 1
        return LLMResponse(
            content="BUY 0.6 stub",
            model=kwargs["model"],
            input_tokens=10,
            output_tokens=20,
        )


def test_peek_returns_none_on_miss(tmp_path: Path):
    cached = CachedClient(inner=_CountingMock(), cache_dir=tmp_path)
    result = cached.peek(
        agent="technical", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    assert result is None


async def test_peek_returns_cached_on_hit(tmp_path: Path):
    stub = _CountingMock()
    cached = CachedClient(inner=stub, cache_dir=tmp_path)
    # Warm the cache.
    warm = await cached.complete(
        agent="technical", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    assert stub.calls == 1
    # Peek must return the same payload without touching the inner.
    peeked = cached.peek(
        agent="technical", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    assert peeked is not None
    assert peeked.content == warm.content
    assert stub.calls == 1  # no extra inner call


async def test_peek_normalizes_agent_case(tmp_path: Path):
    """Cache key normalizes agent to lowercase; peek must agree."""
    cached = CachedClient(inner=_CountingMock(), cache_dir=tmp_path)
    # Warm with mixed case; CachedClient lowercases internally.
    await cached.complete(
        agent="Technical", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    # Peek with a different casing should still hit.
    result = cached.peek(
        agent="TECHNICAL", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    assert result is not None


async def test_peek_returns_none_on_corrupt_file(tmp_path: Path):
    """Corrupt cache files are treated as misses (and unlinked) by _try_read."""
    cached = CachedClient(inner=_CountingMock(), cache_dir=tmp_path)
    await cached.complete(
        agent="technical", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    files[0].write_text("{ not valid json", encoding="utf-8")
    result = cached.peek(
        agent="technical", prompt="x", image_b64=None, model="m", bar_ts=1,
    )
    assert result is None
    # _try_read unlinks corrupt files.
    assert not files[0].exists()


def test_peek_does_not_call_inner(tmp_path: Path):
    """peek() must be a pure read; it should never invoke the inner client."""
    stub = _CountingMock()
    cached = CachedClient(inner=stub, cache_dir=tmp_path)
    # Miss path
    cached.peek(agent="technical", prompt="x", image_b64=None, model="m", bar_ts=1)
    assert stub.calls == 0


async def test_concurrent_writes_to_same_key_do_not_corrupt(tmp_path: Path):
    """Two CachedClient instances sharing one cache dir must not produce a
    truncated/half-written file when they race on the same key.

    Audit fix C2: previously the tmp-file name was a deterministic
    ``<key>.json.tmp`` shared across processes/instances, so a slow writer
    could see its tmp file truncated by a faster one mid-write. The fix
    uses a unique tmp name per write so each writer atomically replaces
    with a complete payload.

    This test directly inspects the path the writer uses by monkeypatching
    ``os.replace`` to record the source tmp path and asserting the two
    parallel writers picked *different* tmp names (so neither can clobber
    the other before its own replace lands).
    """
    import asyncio
    import os as _os

    class _SlowClient:
        def __init__(self, content: str) -> None:
            self.content = content

        async def complete(self, **kwargs) -> LLMResponse:
            # Yield so the two writers interleave.
            await asyncio.sleep(0)
            return LLMResponse(
                content=self.content,
                model=kwargs["model"],
                input_tokens=1,
                output_tokens=1,
            )

    seen_tmp_paths: list[str] = []
    real_replace = _os.replace

    def _spy_replace(src, dst):
        seen_tmp_paths.append(str(src))
        return real_replace(src, dst)

    c1 = CachedClient(inner=_SlowClient("A" * 4096), cache_dir=tmp_path)
    c2 = CachedClient(inner=_SlowClient("B" * 4096), cache_dir=tmp_path)

    kwargs = {
        "agent": "technical",
        "prompt": "same-prompt",
        "image_b64": None,
        "model": "mock",
        "bar_ts": 1,
    }

    import unittest.mock as _mock
    with _mock.patch("llm.cache.os.replace", side_effect=_spy_replace):
        await asyncio.gather(c1.complete(**kwargs), c2.complete(**kwargs))

    # Each writer must use a *unique* tmp-file path so they cannot
    # accidentally truncate each other's in-flight write.
    assert len(seen_tmp_paths) == 2
    assert seen_tmp_paths[0] != seen_tmp_paths[1], (
        f"Both writers used the same tmp path: {seen_tmp_paths}"
    )

    # And no stray tmp files left behind.
    json_files = list(tmp_path.rglob("*.json"))
    tmp_files = list(tmp_path.rglob("*.json.tmp")) + list(tmp_path.rglob("*.tmp"))
    assert len(json_files) == 1, json_files
    assert tmp_files == [], tmp_files

    blob = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert blob["content"] in {"A" * 4096, "B" * 4096}
    assert blob["model"] == "mock"
