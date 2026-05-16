"""Decision node: deterministic weighted-consensus guardrail (spec §7.2).

LLM is intentionally NOT called here. The three analysts have already voted;
math determines the trade and the result is reproducible bar-for-bar.

Weights (spec §7.2 default): 0.40 QABBA + 0.35 Visual + 0.25 Technical.
Threshold (spec §7.2 default): a side wins iff its score is STRICTLY greater
than 0.50 AND strictly greater than the opposing side. Anything else is HOLD.

Both weights and threshold are configurable via `make_decision_node(...)`;
the module-level constants and `decision_node` preserve spec defaults for
back-compat and direct unit testing.

The node is ``async def`` to fit LangGraph's uniform signature, but performs
no I/O.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.types import Action, AgentReport
from strategies.llm_agents.state import GraphState

W_QABBA: float = 0.40
W_VISUAL: float = 0.35
W_TECH: float = 0.25
THRESHOLD: float = 0.50

DecisionNode = Callable[[GraphState], Awaitable[dict[str, Any]]]


def _score_side(
    reports: dict[str, AgentReport | None],
    side: Action,
    w_qabba: float,
    w_visual: float,
    w_tech: float,
) -> float:
    s = 0.0
    q = reports.get("qabba")
    v = reports.get("visual")
    t = reports.get("technical")
    if q is not None and q.action is side:
        s += w_qabba * q.confidence
    if v is not None and v.action is side:
        s += w_visual * v.confidence
    if t is not None and t.action is side:
        s += w_tech * t.confidence
    return s


def make_decision_node(
    *,
    weights: dict[str, float],
    threshold: float,
) -> DecisionNode:
    """Return a decision_node configured with the given weights and threshold.

    Args:
        weights: Mapping with keys ``qabba``, ``visual``, ``technical``; values
            must sum to 1.0 (validated upstream by `LLMSettings`).
        threshold: A side wins iff its weighted score is strictly greater than
            this value (and strictly greater than the opposing side).

    Returns:
        An async callable matching the LangGraph node signature.
    """
    w_q = weights["qabba"]
    w_v = weights["visual"]
    w_t = weights["technical"]

    async def _node(state: GraphState) -> dict:
        reports: dict[str, AgentReport | None] = {
            "technical": state["technical"],
            "visual": state["visual"],
            "qabba": state["qabba"],
        }
        buy = _score_side(reports, Action.BUY, w_q, w_v, w_t)
        sell = _score_side(reports, Action.SELL, w_q, w_v, w_t)

        if buy > threshold and buy > sell:
            action, conf = Action.BUY, buy
        elif sell > threshold and sell > buy:
            action, conf = Action.SELL, sell
        else:
            # HOLD branch. Floor confidence at 0.5 so neutral/no-vote HOLDs read
            # as "moderately confident in inaction"; below-threshold HOLDs
            # surface the winning side's score (e.g. 0.435) so reviewers can see
            # the near-miss.
            action, conf = Action.HOLD, max(buy, sell, 0.5)

        rationale = (
            f"buy={buy:.3f} sell={sell:.3f} "
            f"weights(Q={w_q},V={w_v},T={w_t}) thr={threshold}"
        )
        return {
            "decision": AgentReport(action=action, confidence=conf, rationale=rationale),
        }

    return _node


# Spec-default node, preserved for back-compat / direct unit tests.
decision_node: DecisionNode = make_decision_node(
    weights={"qabba": W_QABBA, "visual": W_VISUAL, "technical": W_TECH},
    threshold=THRESHOLD,
)
