"""Shared parser turning LLM model output into an :class:`AgentReport`.

Tolerant: matches the **first** BUY/SELL/HOLD token (word-boundary,
case-insensitive) and ignores any subsequent action tokens — so
``"BUY 0.8 then SELL 0.9"`` parses as BUY. Extracts an optional confidence
float that immediately follows, clamps it to [0, 1], and treats anything beyond
as one-line rationale (truncated at 200 chars to bound state size).
Unparseable text defaults to ``HOLD@0.5``.
"""
from __future__ import annotations

import re

from core.types import Action, AgentReport

_RE = re.compile(r"\b(BUY|SELL|HOLD)\b\s*(-?\d+\.?\d*)?\s*(.*)", re.IGNORECASE)
_MAX_RATIONALE = 200


def parse_response(content: str) -> AgentReport:
    """Parse a free-form model response into an ``AgentReport``."""
    m = _RE.search(content)
    if not m:
        return AgentReport(
            action=Action.HOLD,
            confidence=0.5,
            rationale=content.strip()[:_MAX_RATIONALE],
        )
    action = Action[m.group(1).upper()]
    try:
        conf = float(m.group(2)) if m.group(2) else 0.5
    except ValueError:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    rationale = (m.group(3) or "").strip()[:_MAX_RATIONALE]
    return AgentReport(action=action, confidence=conf, rationale=rationale)
