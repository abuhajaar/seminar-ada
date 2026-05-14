"""Visual (chart-pattern) analyst node: reads chart image, emits AgentReport."""
from __future__ import annotations

from llm.client import LLMClient
from strategies.llm_agents.nodes._common import call_llm
from strategies.llm_agents.nodes._parse import parse_response
from strategies.llm_agents.prompts import build_visual_prompt
from strategies.llm_agents.state import GraphState


async def visual_node(state: GraphState, *, client: LLMClient) -> GraphState:
    prompt = build_visual_prompt()
    resp = await call_llm(
        client=client,
        agent="visual",
        prompt=prompt,
        image_b64=state["image_b64"],
        model=state["model"],
        bar_ts=state["bar_ts"],
    )
    return {**state, "visual": parse_response(resp.content)}
