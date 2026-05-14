"""LLM client protocol and implementations.

`OpenRouterClient` is the real backend (httpx + OpenRouter API).
`MockClient` is a deterministic stand-in derived from prompt features, used for
tests and for seminar replay without spending money. All calls are async.
"""
from __future__ import annotations

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
    """

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

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
            httpx.HTTPStatusError: on non-2xx response from OpenRouter; caller is
                responsible for retry/backoff (use `tenacity` or similar).
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

        async with httpx.AsyncClient(timeout=self._timeout) as cli:
            resp = await cli.post(self.BASE_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        msg = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            content=msg if isinstance(msg, str) else str(msg),
            model=model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )
