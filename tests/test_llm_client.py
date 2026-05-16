"""Tests for llm.client: LLMClient Protocol, LLMResponse, MockClient, OpenRouterClient."""
from __future__ import annotations

import httpx
import pytest
import respx

from llm.client import LLMClient, LLMResponse, LLMResponseError, MockClient, OpenRouterClient


def test_llm_response_is_a_dataclass_with_required_fields():
    r = LLMResponse(content="HOLD 0.5 reason", model="mock", input_tokens=10, output_tokens=5)
    assert r.content == "HOLD 0.5 reason"
    assert r.model == "mock"
    assert r.input_tokens == 10
    assert r.output_tokens == 5


async def test_mock_client_implements_protocol():
    client: LLMClient = MockClient()
    r = await client.complete(
        agent="technical",
        prompt="features: ema_fast=100 ema_slow=95 rsi=55",
        image_b64=None,
        model="mock",
    )
    assert isinstance(r, LLMResponse)
    assert r.model == "mock"


async def test_mock_client_technical_buy_on_bullish_features():
    client = MockClient()
    r = await client.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100 rsi=60 macd_hist=0.5",
        image_b64=None,
        model="mock",
    )
    assert "BUY" in r.content.upper()


async def test_mock_client_technical_sell_on_bearish_features():
    client = MockClient()
    r = await client.complete(
        agent="technical",
        prompt="ema_fast=90 ema_slow=100 rsi=40 macd_hist=-0.5",
        image_b64=None,
        model="mock",
    )
    assert "SELL" in r.content.upper()


async def test_mock_client_technical_hold_on_missing_features():
    client = MockClient()
    r = await client.complete(
        agent="technical",
        prompt="(no numeric features)",
        image_b64=None,
        model="mock",
    )
    assert "HOLD" in r.content.upper()


async def test_mock_client_qabba_buy_on_positive_cvd():
    client = MockClient()
    r = await client.complete(
        agent="qabba",
        prompt="cvd_delta=12345.6",
        image_b64=None,
        model="mock",
    )
    assert "BUY" in r.content.upper()


async def test_mock_client_qabba_sell_on_negative_cvd():
    client = MockClient()
    r = await client.complete(
        agent="qabba",
        prompt="cvd_delta=-9999.0",
        image_b64=None,
        model="mock",
    )
    assert "SELL" in r.content.upper()


async def test_mock_client_visual_returns_hold_without_image():
    client = MockClient()
    r = await client.complete(
        agent="visual",
        prompt="(no image)",
        image_b64=None,
        model="mock",
    )
    assert "HOLD" in r.content.upper()


async def test_mock_client_decision_picks_majority_buy():
    client = MockClient()
    r = await client.complete(
        agent="decision",
        prompt="tech=BUY:0.7 visual=BUY:0.6 qabba=BUY:0.8",
        image_b64=None,
        model="mock",
    )
    assert "BUY" in r.content.upper()


async def test_mock_client_decision_picks_majority_sell():
    client = MockClient()
    r = await client.complete(
        agent="decision",
        prompt="tech=SELL:0.7 visual=SELL:0.6 qabba=SELL:0.8",
        image_b64=None,
        model="mock",
    )
    assert "SELL" in r.content.upper()


async def test_mock_client_deterministic_same_prompt_same_output():
    """Same inputs must yield byte-identical output (no randomness)."""
    client = MockClient()
    r1 = await client.complete(
        agent="technical", prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None, model="mock",
    )
    r2 = await client.complete(
        agent="technical", prompt="ema_fast=110 ema_slow=100 macd_hist=0.5",
        image_b64=None, model="mock",
    )
    assert r1.content == r2.content


async def test_openrouter_client_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = OpenRouterClient(api_key=None)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet"
        )


@respx.mock
async def test_openrouter_client_posts_and_parses_response():
    """Mock the OpenRouter HTTP endpoint and verify request + response handling."""
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "BUY 0.8 strong trend"}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 7},
            },
        )
    )
    client = OpenRouterClient(api_key="sk-test")
    r = await client.complete(
        agent="technical",
        prompt="ema_fast=110 ema_slow=100",
        image_b64=None,
        model="anthropic/claude-3.5-sonnet",
    )
    assert route.called
    assert r.content == "BUY 0.8 strong trend"
    assert r.model == "anthropic/claude-3.5-sonnet"
    assert r.input_tokens == 42
    assert r.output_tokens == 7

    # Verify Authorization header and payload shape
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer sk-test"
    import json as _json
    body = _json.loads(req.content)
    assert body["model"] == "anthropic/claude-3.5-sonnet"
    assert body["temperature"] == 0
    assert body["messages"][0]["role"] == "user"
    # Content is a list with at least the text block
    assert body["messages"][0]["content"][0]["type"] == "text"


@respx.mock
async def test_openrouter_client_includes_image_when_provided():
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "HOLD 0.5 unclear"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )
    )
    client = OpenRouterClient(api_key="sk-test")
    await client.complete(
        agent="visual",
        prompt="examine this chart",
        image_b64="AAAA",  # tiny fake base64
        model="anthropic/claude-3.5-sonnet",
    )
    import json as _json
    body = _json.loads(route.calls.last.request.content)
    content = body["messages"][0]["content"]
    # Should have 2 content blocks: text + image_url
    assert len(content) == 2
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["image_url"]["url"].endswith("AAAA")


# ---------------------------------------------------------------------------
# C4: malformed response handling
#
# Pre-fix, `OpenRouterClient.complete` indexed `data["choices"][0]["message"]
# ["content"]` unguarded. A single malformed-but-200-OK payload from
# OpenRouter would raise KeyError/IndexError mid-walk and kill the demo.
# The hardened path must raise `LLMResponseError` (a subclass of
# RuntimeError) so walkforward can catch it as a transient asset-level
# error rather than crashing the whole run.
# ---------------------------------------------------------------------------


@respx.mock
async def test_openrouter_client_raises_llm_response_error_on_missing_choices():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"usage": {}}),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(LLMResponseError, match="choices"):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )


@respx.mock
async def test_openrouter_client_raises_llm_response_error_on_empty_choices():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [], "usage": {}}),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(LLMResponseError, match="choices"):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )


@respx.mock
async def test_openrouter_client_raises_llm_response_error_on_missing_message():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{}], "usage": {}}),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(LLMResponseError, match="message"):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )


@respx.mock
async def test_openrouter_client_raises_llm_response_error_on_missing_content():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {}}], "usage": {}}),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(LLMResponseError, match="content"):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )


@respx.mock
async def test_openrouter_client_raises_llm_response_error_on_invalid_json():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, text="<html>not json</html>"),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(LLMResponseError, match="JSON"):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )


def test_llm_response_error_is_a_runtime_error_subclass():
    """walkforward and other callers catch RuntimeError as a transient class."""
    assert issubclass(LLMResponseError, RuntimeError)


# ---------------------------------------------------------------------------
# C4 (retry): retry/backoff on transient OpenRouter failures
#
# Pre-fix, a single 429/503 from OpenRouter aborted the asset (no retry).
# The hardened client retries up to 3 times with exponential backoff
# (0.5s, 1s, 2s) on:
#   - HTTP 429 (rate limit)
#   - HTTP 5xx (server errors)
#   - httpx.TransportError (network blip)
#   - asyncio.TimeoutError
# Non-retryable: 4xx other than 429 (auth, bad request) raises immediately.
# ---------------------------------------------------------------------------


@respx.mock
async def test_openrouter_client_retries_on_429_and_succeeds(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("llm.client.asyncio.sleep", fake_sleep)

    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limit"}),
            httpx.Response(429, json={"error": "rate limit"}),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "BUY 0.8 ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            ),
        ]
    )
    client = OpenRouterClient(api_key="sk-test")
    r = await client.complete(
        agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
    )
    assert r.content == "BUY 0.8 ok"
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


@respx.mock
async def test_openrouter_client_retries_on_503_and_succeeds(monkeypatch):
    async def fake_sleep(_s: float) -> None:
        pass

    monkeypatch.setattr("llm.client.asyncio.sleep", fake_sleep)

    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "HOLD 0.5 ok"}}],
                    "usage": {},
                },
            ),
        ]
    )
    client = OpenRouterClient(api_key="sk-test")
    r = await client.complete(
        agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
    )
    assert r.content == "HOLD 0.5 ok"
    assert route.call_count == 2


@respx.mock
async def test_openrouter_client_gives_up_after_3_attempts(monkeypatch):
    async def fake_sleep(_s: float) -> None:
        pass

    monkeypatch.setattr("llm.client.asyncio.sleep", fake_sleep)

    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(503),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(httpx.HTTPStatusError):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )
    assert route.call_count == 3


@respx.mock
async def test_openrouter_client_does_not_retry_on_400(monkeypatch):
    async def fake_sleep(_s: float) -> None:
        pass

    monkeypatch.setattr("llm.client.asyncio.sleep", fake_sleep)

    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": "bad request"}),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(httpx.HTTPStatusError):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )
    assert route.call_count == 1


@respx.mock
async def test_openrouter_client_does_not_retry_on_401(monkeypatch):
    async def fake_sleep(_s: float) -> None:
        pass

    monkeypatch.setattr("llm.client.asyncio.sleep", fake_sleep)

    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"}),
    )
    client = OpenRouterClient(api_key="sk-test")
    with pytest.raises(httpx.HTTPStatusError):
        await client.complete(
            agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
        )
    assert route.call_count == 1


@respx.mock
async def test_openrouter_client_retries_on_transport_error(monkeypatch):
    async def fake_sleep(_s: float) -> None:
        pass

    monkeypatch.setattr("llm.client.asyncio.sleep", fake_sleep)

    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.ConnectError("network blip"),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "BUY 0.7 ok"}}],
                    "usage": {},
                },
            ),
        ]
    )
    client = OpenRouterClient(api_key="sk-test")
    r = await client.complete(
        agent="technical", prompt="x", image_b64=None, model="anthropic/claude-3.5-sonnet",
    )
    assert r.content == "BUY 0.7 ok"
    assert route.call_count == 2
