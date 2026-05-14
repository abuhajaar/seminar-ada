"""Per-run USD budget guard for LLM calls (spec §9).

Usage pattern:
    guard = BudgetGuard(cap_usd=cfg.llm.max_usd)
    est = estimate_cost_usd(
        input_tokens=token_estimate,
        output_tokens=expected_output,
        in_per_1m=price_in,
        out_per_1m=price_out,
    )
    guard.check_can_afford(est)   # raises BudgetExceededError pre-call
    resp = await client.complete(...)
    actual = estimate_cost_usd(
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        in_per_1m=price_in,
        out_per_1m=price_out,
    )
    guard.charge(actual)
"""
from __future__ import annotations

# Floating-point tolerance for "spent + estimate <= cap" comparison.
# Set well below 1 cent so it cannot mask real budget breaches.
_EPS_USD = 1e-9


class BudgetExceededError(RuntimeError):
    """Raised when a pending LLM call would push cumulative spend over the cap.

    Args:
        message: Human-readable description.
        spend_usd: Cumulative USD already charged at the moment of refusal.
            Defaults to 0.0 for backward-compatible construction.
    """

    def __init__(self, message: str, *, spend_usd: float = 0.0) -> None:
        super().__init__(message)
        self.spend_usd = spend_usd


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    in_per_1m: float,
    out_per_1m: float,
) -> float:
    """Compute expected USD cost from token counts and per-million prices.

    Prices are in USD per 1,000,000 tokens (the OpenRouter pricing convention).
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if in_per_1m < 0 or out_per_1m < 0:
        raise ValueError("per-million prices must be non-negative")
    return (input_tokens / 1_000_000.0) * in_per_1m + (output_tokens / 1_000_000.0) * out_per_1m


class BudgetGuard:
    """Tracks cumulative spend; refuses calls that would breach ``cap_usd``.

    Not safe for concurrent use; intended for single-task async strategy. Sub-plan
    D may parallelise across symbols, but a *separate* guard per run is the
    intended pattern — sharing one across tasks would race on ``_spent``.
    """

    def __init__(self, cap_usd: float) -> None:
        if cap_usd < 0:
            raise ValueError("cap_usd must be non-negative")
        self._cap = cap_usd
        self._spent = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent

    @property
    def remaining_usd(self) -> float:
        return self._cap - self._spent

    def check_can_afford(self, est_usd: float) -> None:
        """Raise ``BudgetExceededError`` if charging ``est_usd`` would breach cap.

        A small floating-point tolerance (``_EPS_USD``) makes exact-cap calls
        pass even when accumulated rounding pushes ``spent + est`` a few ulps
        above ``cap``. The tolerance is far smaller than any real cost.
        """
        if est_usd < 0:
            raise ValueError("est_usd must be non-negative")
        if self._spent + est_usd > self._cap + _EPS_USD:
            raise BudgetExceededError(
                f"Budget exceeded: spent={self._spent:.4f} + est={est_usd:.4f} "
                f"> cap={self._cap:.4f}",
                spend_usd=self._spent,
            )

    def charge(self, usd: float) -> None:
        """Record actual cost after a successful call.

        Intentionally does NOT validate against the cap — the pre-call gate is
        ``check_can_afford``. Because ``check_can_afford`` permits ``_EPS_USD``
        of slop, ``_spent`` may end a few ulps above ``_cap`` and
        ``remaining_usd`` may go slightly negative; this is by design.
        """
        if usd < 0:
            raise ValueError("usd must be non-negative")
        self._spent += usd
