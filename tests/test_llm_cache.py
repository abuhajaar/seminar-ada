"""Tests for llm.cache: bar-keyed JSON cache decorator (spec §6, Q2)."""
from __future__ import annotations

import json
from pathlib import Path

from llm.cache import CachedClient, cache_key
from llm.client import MockClient


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
