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
from strategies.llm_agents.nodes.decision import decision_node
from strategies.llm_agents.nodes.qabba import qabba_node
from strategies.llm_agents.nodes.technical import technical_node
from strategies.llm_agents.nodes.visual import visual_node
from strategies.llm_agents.state import GraphState


def build_graph(*, client: LLMClient) -> CompiledStateGraph:
    """Compile and return the LLM agent LangGraph.

    Args:
        client: The ``LLMClient`` to inject into the three analyst nodes.
            Typically a ``CachedClient`` wrapping either ``OpenRouterClient``
            or ``MockClient``. Decision node performs no I/O and ignores it.

    Returns:
        A compiled LangGraph; invoke with ``await graph.ainvoke(initial_state)``.
    """
    g: StateGraph = StateGraph(GraphState)
    g.add_node("technical", partial(technical_node, client=client))
    g.add_node("visual", partial(visual_node, client=client))
    g.add_node("qabba", partial(qabba_node, client=client))
    g.add_node("decision", decision_node)

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
