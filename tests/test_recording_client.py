import json
from pathlib import Path

import pytest

from core.bar_artifacts import BarArtifactSink
from llm.client import LLMResponse
from llm.recording import RecordingClient


class _StubClient:
    """Minimal stand-in for any LLMClient: returns a canned LLMResponse."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def complete(self, *, agent: str, prompt: str, image_b64, model, **kwargs):
        self.calls.append(
            {"agent": agent, "prompt": prompt, "image_b64": image_b64, "model": model, **kwargs}
        )
        return LLMResponse(
            content='{"action": "BUY", "confidence": 0.7, "rationale": "ok"}',
            model=model,
            input_tokens=10,
            output_tokens=10,
        )


@pytest.mark.asyncio
async def test_recording_client_writes_prompt_and_response(tmp_path: Path):
    inner = _StubClient()
    sink = BarArtifactSink(tmp_path / "0001")
    rec = RecordingClient(inner=inner, sink=sink)
    resp = await rec.complete(
        agent="technical", prompt="HELLO PROMPT", image_b64=None, model="x", bar_ts=1
    )
    assert resp.content.startswith("{")
    assert (tmp_path / "0001" / "technical_input.txt").read_text(encoding="utf-8") == "HELLO PROMPT"
    out = json.loads((tmp_path / "0001" / "technical_output.json").read_text(encoding="utf-8"))
    assert out["raw"].startswith("{")


@pytest.mark.asyncio
async def test_recording_client_writes_image_when_present(tmp_path: Path):
    import base64

    png_bytes = b"\x89PNG\r\n\x1a\nFAKE"
    image_b64 = base64.b64encode(png_bytes).decode("ascii")
    inner = _StubClient()
    sink = BarArtifactSink(tmp_path / "0001")
    rec = RecordingClient(inner=inner, sink=sink)
    await rec.complete(agent="visual", prompt="P", image_b64=image_b64, model="x", bar_ts=1)
    assert (tmp_path / "0001" / "visual_input.png").read_bytes() == png_bytes


@pytest.mark.asyncio
async def test_recording_client_forwards_all_kwargs(tmp_path: Path):
    """bar_ts must be forwarded to inner (CachedClient / BudgetGuardedClient need it)."""
    inner = _StubClient()
    sink = BarArtifactSink(tmp_path / "0001")
    rec = RecordingClient(inner=inner, sink=sink)
    await rec.complete(agent="qabba", prompt="P", image_b64=None, model="m", bar_ts=12345)
    assert inner.calls[0]["bar_ts"] == 12345
