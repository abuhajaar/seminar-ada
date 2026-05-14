"""QABBA (order-flow) analyst node: reads CVD features, emits AgentReport."""
from __future__ import annotations

from llm.client import LLMClient
from strategies.llm_agents.nodes._common import call_llm
from strategies.llm_agents.nodes._parse import parse_response
from strategies.llm_agents.prompts import build_qabba_prompt
from strategies.llm_agents.state import GraphState


async def qabba_node(state: GraphState, *, client: LLMClient) -> dict:
    """Return a partial state update containing only the ``qabba`` key.

    See ``technical_node`` for why analyst nodes return deltas (not full state).
    """
    prompt = build_qabba_prompt(state["features"])
    resp = await call_llm(
        client=client,
        agent="qabba",
        prompt=prompt,
        image_b64=None,
        model=state["model"],
        bar_ts=state["bar_ts"],
    )
    return {"qabba": parse_response(resp.content)}
