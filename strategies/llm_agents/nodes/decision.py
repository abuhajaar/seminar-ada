"""Decision node: deterministic weighted-consensus guardrail (spec §7.2).

LLM is intentionally NOT called here. The three analysts have already voted;
math determines the trade and the result is reproducible bar-for-bar.

Weights (spec §7.2): 0.40 QABBA + 0.35 Visual + 0.25 Technical.
Threshold (spec §7.2): a side wins iff its score is STRICTLY greater than 0.50
AND strictly greater than the opposing side. Anything else is HOLD.

The node is ``async def`` to fit LangGraph's uniform signature, but performs
no I/O.
"""
from __future__ import annotations

from core.types import Action, AgentReport
from strategies.llm_agents.state import GraphState

W_QABBA: float = 0.40
W_VISUAL: float = 0.35
W_TECH: float = 0.25
THRESHOLD: float = 0.50


def _score(
    reports: dict[str, AgentReport | None],
    side: Action,
) -> float:
    s = 0.0
    q = reports.get("qabba")
    v = reports.get("visual")
    t = reports.get("technical")
    if q is not None and q.action is side:
        s += W_QABBA * q.confidence
    if v is not None and v.action is side:
        s += W_VISUAL * v.confidence
    if t is not None and t.action is side:
        s += W_TECH * t.confidence
    return s


async def decision_node(state: GraphState) -> dict:
    """Return a partial state update containing only the ``decision`` key.

    Decision runs sequentially after fan-in so the parallel-write constraint
    does not apply, but we return a delta for consistency with analyst nodes.
    """
    reports: dict[str, AgentReport | None] = {
        "technical": state["technical"],
        "visual": state["visual"],
        "qabba": state["qabba"],
    }
    buy = _score(reports, Action.BUY)
    sell = _score(reports, Action.SELL)

    if buy > THRESHOLD and buy > sell:
        action, conf = Action.BUY, buy
    elif sell > THRESHOLD and sell > buy:
        action, conf = Action.SELL, sell
    else:
        # HOLD branch. Floor confidence at 0.5 so neutral/no-vote HOLDs read as
        # "moderately confident in inaction"; below-threshold HOLDs surface the
        # winning side's score (e.g. 0.435) so reviewers can see the near-miss.
        action, conf = Action.HOLD, max(buy, sell, 0.5)

    rationale = (
        f"buy={buy:.3f} sell={sell:.3f} "
        f"weights(Q={W_QABBA},V={W_VISUAL},T={W_TECH}) thr={THRESHOLD}"
    )
    return {
        "decision": AgentReport(action=action, confidence=conf, rationale=rationale),
    }
