"""Tests for `llm.budget` — pre-call estimate + cumulative spend tracking (spec §9)."""
from __future__ import annotations

import pytest

from llm.budget import BudgetExceededError, BudgetGuard, estimate_cost_usd


def test_estimate_cost_usd_basic():
    # 1000 input + 500 output tokens at $3/1M in, $15/1M out
    c = estimate_cost_usd(input_tokens=1000, output_tokens=500, in_per_1m=3.0, out_per_1m=15.0)
    assert c == pytest.approx(0.003 + 0.0075)


def test_estimate_cost_usd_zero_tokens():
    c = estimate_cost_usd(input_tokens=0, output_tokens=0, in_per_1m=3.0, out_per_1m=15.0)
    assert c == 0.0


def test_estimate_cost_usd_rejects_negative_tokens():
    with pytest.raises(ValueError):
        estimate_cost_usd(input_tokens=-1, output_tokens=0, in_per_1m=3.0, out_per_1m=15.0)
    with pytest.raises(ValueError):
        estimate_cost_usd(input_tokens=0, output_tokens=-1, in_per_1m=3.0, out_per_1m=15.0)


def test_estimate_cost_usd_rejects_negative_price():
    with pytest.raises(ValueError):
        estimate_cost_usd(input_tokens=1, output_tokens=1, in_per_1m=-1.0, out_per_1m=15.0)


def test_budget_guard_allows_under_cap():
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.10)
    g.charge(0.20)
    assert g.spent_usd == pytest.approx(0.30)
    assert g.remaining_usd == pytest.approx(0.70)


def test_budget_guard_check_before_charge_raises_when_over():
    g = BudgetGuard(cap_usd=0.50)
    g.charge(0.40)
    with pytest.raises(BudgetExceededError):
        g.check_can_afford(0.20)


def test_budget_guard_check_allows_exact_cap():
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.50)
    g.check_can_afford(0.50)  # should not raise


def test_budget_guard_zero_cap_blocks_everything():
    g = BudgetGuard(cap_usd=0.0)
    with pytest.raises(BudgetExceededError):
        g.check_can_afford(0.001)


def test_budget_guard_rejects_negative_cap():
    with pytest.raises(ValueError):
        BudgetGuard(cap_usd=-0.01)


def test_budget_guard_rejects_negative_charge():
    g = BudgetGuard(cap_usd=1.0)
    with pytest.raises(ValueError):
        g.charge(-0.01)


def test_budget_guard_rejects_negative_estimate():
    g = BudgetGuard(cap_usd=1.0)
    with pytest.raises(ValueError):
        g.check_can_afford(-0.01)


def test_budget_guard_initial_state():
    g = BudgetGuard(cap_usd=2.5)
    assert g.spent_usd == 0.0
    assert g.remaining_usd == pytest.approx(2.5)


def test_budget_exceeded_error_message_contains_numbers():
    g = BudgetGuard(cap_usd=0.50)
    g.charge(0.40)
    with pytest.raises(BudgetExceededError) as exc:
        g.check_can_afford(0.20)
    msg = str(exc.value)
    assert "0.40" in msg or "0.4000" in msg
    assert "0.50" in msg or "0.5000" in msg


def test_budget_guard_floating_point_boundary():
    """0.1 + 0.2 != 0.3 in float; tolerance should allow exact-cap pass."""
    g = BudgetGuard(cap_usd=0.3)
    g.charge(0.1)
    g.charge(0.2)
    # remaining could be slightly negative due to FP; check_can_afford(0.0) must not raise
    g.check_can_afford(0.0)


def test_budget_exceeded_error_carries_spend_usd():
    """check_can_afford must raise with spend_usd populated to current _spent."""
    g = BudgetGuard(cap_usd=1.0)
    g.charge(0.80)
    with pytest.raises(BudgetExceededError) as exc_info:
        g.check_can_afford(0.50)  # 0.80 + 0.50 > 1.0
    assert exc_info.value.spend_usd == pytest.approx(0.80)


def test_budget_exceeded_error_default_spend_usd_zero():
    """Constructing the error without a spend_usd kwarg defaults to 0.0."""
    err = BudgetExceededError("test")
    assert err.spend_usd == 0.0
