"""LLM client protocol and implementations.

`OpenRouterClient` is the real backend (httpx + OpenRouter API).
`MockClient` is a deterministic stand-in derived from prompt features, used for
tests and for seminar replay without spending money. All calls are async.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

# Mock confidence levels — exposed as named constants because tests assert on them.
_MOCK_CONF_TECHNICAL = 0.70  # two confirming indicators (ema cross + macd sign)
_MOCK_CONF_QABBA = 0.65      # single-indicator signal (cvd direction)
_MOCK_CONF_DECISION = 0.60   # majority vote, not unanimous
_MOCK_CONF_NEUTRAL = 0.50    # no clear signal


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMResponseError(RuntimeError):
    """Raised when an OpenRouter 200-OK response is structurally malformed.

    Subclass of ``RuntimeError`` so callers (e.g. ``core.walkforward``) can
    catch it alongside other transient runtime failures and continue with
    the next asset instead of crashing the whole walk.
    """


class LLMClient(Protocol):
    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
    ) -> LLMResponse: ...


def _extract_float(text: str, key: str) -> float | None:
    """Find `key=<number>` in text; return float or None."""
    pat = re.compile(rf"{re.escape(key)}\s*=\s*(-?\d+\.?\d*)")
    m = pat.search(text)
    return float(m.group(1)) if m else None


class MockClient:
    """Deterministic LLM stand-in keyed off prompt features.

    Technical: BUY if ema_fast>ema_slow AND macd_hist>0, SELL if both reversed, else HOLD.
    QABBA: BUY if cvd_delta>0, SELL if <0, else HOLD.
    Visual: HOLD always (chart-vision stubbed; real path needs OpenRouterClient).
    Decision: count BUY/SELL tokens in prompt; majority wins, else HOLD.
    """

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
    ) -> LLMResponse:
        agent_l = agent.lower()
        action = "HOLD"
        confidence = 0.5

        if agent_l == "technical":
            ema_fast = _extract_float(prompt, "ema_fast")
            ema_slow = _extract_float(prompt, "ema_slow")
            macd_hist = _extract_float(prompt, "macd_hist")
            if ema_fast is not None and ema_slow is not None and macd_hist is not None:
                if ema_fast > ema_slow and macd_hist > 0:
                    action, confidence = "BUY", _MOCK_CONF_TECHNICAL
                elif ema_fast < ema_slow and macd_hist < 0:
                    action, confidence = "SELL", _MOCK_CONF_TECHNICAL
        elif agent_l == "qabba":
            cvd = _extract_float(prompt, "cvd_delta")
            if cvd is not None:
                if cvd > 0:
                    action, confidence = "BUY", _MOCK_CONF_QABBA
                elif cvd < 0:
                    action, confidence = "SELL", _MOCK_CONF_QABBA
        elif agent_l == "visual":
            action, confidence = "HOLD", _MOCK_CONF_NEUTRAL
        elif agent_l == "decision":
            upper = prompt.upper()
            ups = len(re.findall(r"\bBUY\b", upper))
            downs = len(re.findall(r"\bSELL\b", upper))
            if ups > downs:
                action, confidence = "BUY", _MOCK_CONF_DECISION
            elif downs > ups:
                action, confidence = "SELL", _MOCK_CONF_DECISION

        content = f"{action} {confidence:.2f} mock-{agent_l}"
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=len(prompt) // 4,
            output_tokens=len(content) // 4,
        )


class OpenRouterClient:
    """Async OpenRouter chat-completions client.

    Reads `OPENROUTER_API_KEY` from environment if `api_key` is None.
    Vision-capable models accept a single base64 PNG in `image_b64`;
    non-vision agents pass None.

    Retries up to ``_MAX_ATTEMPTS`` (3) times on transient failures
    (HTTP 429, 5xx, ``httpx.TransportError``, ``asyncio.TimeoutError``)
    with exponential backoff (0.5s, 1s, 2s — no jitter). 4xx other than
    429 (auth, bad-request) raises immediately. Malformed 200-OK payloads
    raise ``LLMResponseError`` (no retry — body is unrecoverable).
    """

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
    _MAX_ATTEMPTS = 3
    _BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0)
    _RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(self, api_key: str | None = None, timeout_s: float = 60.0) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self._timeout = timeout_s

    async def complete(
        self,
        *,
        agent: str,
        prompt: str,
        image_b64: str | None,
        model: str,
    ) -> LLMResponse:
        """Call OpenRouter chat-completions and return an LLMResponse.

        Raises:
            RuntimeError: if no API key is configured.
            httpx.HTTPStatusError: on non-retryable 4xx (auth, bad-request)
                or after exhausting retries on retryable failures.
            LLMResponseError: on malformed 200-OK body (no retry — content
                is unrecoverable).
        """
        if not self._api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set; pass api_key explicitly "
                "or use MockClient for offline runs."
            )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                }
            )
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        data = await self._post_with_retry(payload, headers)

        choices = data.get("choices")
        if not choices:
            raise LLMResponseError(
                "OpenRouter response missing 'choices' or empty: "
                f"{list(data.keys())}"
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise LLMResponseError(
                f"OpenRouter response missing 'message' in first choice: {choices[0]!r}"
            )
        if "content" not in message:
            raise LLMResponseError(
                f"OpenRouter response missing 'content' in message: {message!r}"
            )
        msg = message["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            content=msg if isinstance(msg, str) else str(msg),
            model=model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )

    async def _post_with_retry(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """POST with exponential backoff on transient failures.

        Returns the decoded JSON body. Raises on non-retryable HTTP errors
        or after exhausting ``_MAX_ATTEMPTS``. Malformed JSON raises
        ``LLMResponseError`` immediately (no retry — body is unrecoverable).
        """
        last_exc: BaseException | None = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as cli:
                    resp = await cli.post(self.BASE_URL, json=payload, headers=headers)
                if resp.status_code in self._RETRYABLE_STATUS:
                    last_exc = httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    if attempt < self._MAX_ATTEMPTS - 1:
                        await asyncio.sleep(self._BACKOFF_SECONDS[attempt])
                        continue
                    resp.raise_for_status()
                resp.raise_for_status()
                try:
                    return resp.json()
                except ValueError as exc:
                    raise LLMResponseError(
                        f"OpenRouter returned non-JSON body: {exc}"
                    ) from exc
            except (TimeoutError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < self._MAX_ATTEMPTS - 1:
                    await asyncio.sleep(self._BACKOFF_SECONDS[attempt])
                    continue
                raise
        # Defensive — loop above always returns or raises on the last attempt.
        assert last_exc is not None
        raise last_exc
