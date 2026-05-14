"""Technical analyst node: reads indicator features, emits AgentReport."""
from __future__ import annotations

from llm.client import LLMClient
from strategies.llm_agents.nodes._common import call_llm
from strategies.llm_agents.nodes._parse import parse_response
from strategies.llm_agents.prompts import build_technical_prompt
from strategies.llm_agents.state import GraphState


async def technical_node(state: GraphState, *, client: LLMClient) -> dict:
    """Return a partial state update containing only the ``technical`` key.

    LangGraph merges concurrent node outputs by channel; returning shared keys
    (``bar_ts``, ``model``, ``features``) from multiple parallel nodes raises
    ``InvalidUpdateError`` on its default ``LastValue`` reducer. Each analyst
    node therefore writes ONLY the slot it owns.
    """
    prompt = build_technical_prompt(state["features"])
    resp = await call_llm(
        client=client,
        agent="technical",
        prompt=prompt,
        image_b64=None,
        model=state["model"],
        bar_ts=state["bar_ts"],
    )
    return {"technical": parse_response(resp.content)}
