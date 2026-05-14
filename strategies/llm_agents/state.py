"""LangGraph state schema for the LLM agent pipeline.

Keys are intentionally permissive (analyst slots default to ``None`` and are
filled in by their respective nodes). LangGraph treats this as a state schema
and merges node outputs by replacement; parallel nodes write disjoint keys so
no custom reducers are required.
"""
from __future__ import annotations

from typing import TypedDict

from core.types import AgentReport


class GraphState(TypedDict):
    bar_ts: int  # ms-since-epoch for cache key (derived from Bar.timestamp by strategy)
    features: dict[str, float]
    image_b64: str | None
    model: str
    technical: AgentReport | None
    visual: AgentReport | None
    qabba: AgentReport | None
    decision: AgentReport | None
