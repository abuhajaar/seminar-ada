"""LangGraph wiring: fan-out 3 analyst nodes in parallel → Decision.

Topology (spec §7):
    START → {technical, visual, qabba}  (parallel fan-out)
                |
                v
            decision → END

Each analyst writes a disjoint key into ``GraphState`` (``technical`` /
``visual`` / ``qabba``), so LangGraph's default replacement semantics suffice;
no custom reducers are required.

The ``client`` is bound per-node via ``functools.partial`` so the compiled
graph is a closure-free reusable object.
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from llm.client import LLMClient
from strategies.llm_agents.nodes.decision import (
    THRESHOLD as DEFAULT_THRESHOLD,
)
from strategies.llm_agents.nodes.decision import (
    W_QABBA,
    W_TECH,
    W_VISUAL,
    make_decision_node,
)
from strategies.llm_agents.nodes.qabba import qabba_node
from strategies.llm_agents.nodes.technical import technical_node
from strategies.llm_agents.nodes.visual import visual_node
from strategies.llm_agents.state import GraphState

_DEFAULT_WEIGHTS: dict[str, float] = {
    "qabba": W_QABBA,
    "visual": W_VISUAL,
    "technical": W_TECH,
}


def build_graph(
    *,
    client: LLMClient,
    consensus_weights: dict[str, float] | None = None,
    consensus_threshold: float | None = None,
) -> CompiledStateGraph:
    """Compile and return the LLM agent LangGraph.

    Args:
        client: The ``LLMClient`` to inject into the three analyst nodes.
            Typically a ``CachedClient`` wrapping either ``OpenRouterClient``
            or ``MockClient``. Decision node performs no I/O and ignores it.
        consensus_weights: Optional override for the decision node's weights
            (keys ``qabba``, ``visual``, ``technical``; must sum to 1.0).
            Defaults to spec §7.2 (0.40/0.35/0.25).
        consensus_threshold: Optional override for the side-wins threshold
            (a side wins iff its weighted score is strictly greater).
            Defaults to spec §7.2 (0.50).

    Returns:
        A compiled LangGraph; invoke with ``await graph.ainvoke(initial_state)``.
    """
    weights = consensus_weights if consensus_weights is not None else _DEFAULT_WEIGHTS
    threshold = consensus_threshold if consensus_threshold is not None else DEFAULT_THRESHOLD

    g: StateGraph = StateGraph(GraphState)
    g.add_node("technical", partial(technical_node, client=client))
    g.add_node("visual", partial(visual_node, client=client))
    g.add_node("qabba", partial(qabba_node, client=client))
    g.add_node(
        "decision",
        make_decision_node(weights=weights, threshold=threshold),
    )

    # Fan out from START to all three analysts (LangGraph runs them concurrently).
    g.add_edge(START, "technical")
    g.add_edge(START, "visual")
    g.add_edge(START, "qabba")

    # All three converge into decision (LangGraph waits for all predecessors).
    g.add_edge("technical", "decision")
    g.add_edge("visual", "decision")
    g.add_edge("qabba", "decision")

    g.add_edge("decision", END)

    return g.compile()
