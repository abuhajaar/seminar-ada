"""Strategy contract used by both the heuristic and LLM bots.

`Strategy.on_bar` is async because the LLM bot's implementation does network
I/O. The heuristic bot returns immediately; the engine awaits both via
`asyncio.gather` (sub-plan D).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from core.types import Bar, Signal

if TYPE_CHECKING:
    from core.bar_artifacts import BarArtifactSink


@dataclass(frozen=True)
class Context:
    """Per-bar context handed to the strategy."""
    symbol: str
    equity: float
    risk_pct: float
    in_position: bool
    bar_index: int | None = None
    artifact_sink: "BarArtifactSink | None" = None


class Strategy(Protocol):
    async def on_bar(self, bar: Bar, ctx: Context) -> Signal: ...
