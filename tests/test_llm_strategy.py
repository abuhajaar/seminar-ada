"""LLMAgentStrategy: bridges the Strategy protocol to the 4-agent LangGraph.

These tests use ``MockClient`` and ``render_image=False`` so they stay fast and
deterministic and don't depend on mplfinance rendering.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.types import Action, Bar, Signal
from llm.client import MockClient
from strategies.base import Context
from strategies.llm_agents.strategy import WARMUP_BARS, LLMAgentStrategy


def _bar(i: int, *, close: float | None = None) -> Bar:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    c = close if close is not None else 50_000.0 + i * 10.0
    return Bar(
        timestamp=start + timedelta(hours=i),
        open=c - 5.0,
        high=c + 50.0,
        low=c - 50.0,
        close=c,
        volume=1.0,
        taker_buy_volume=0.6,
        cvd=100.0 * i,
        cvd_delta=100.0,
    )


def _ctx(in_position: bool = False) -> Context:
    return Context(symbol="BTC/USDT", equity=10_000.0, risk_pct=0.01, in_position=in_position)


@pytest.mark.asyncio
async def test_warmup_returns_hold_without_invoking_graph() -> None:
    """During warmup the strategy must NOT call the graph."""
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
    )
    sig: Signal | None = None
    for i in range(WARMUP_BARS - 1):
        sig = await strat.on_bar(_bar(i), _ctx())
    assert sig is not None
    assert sig.action is Action.HOLD
    assert sig.confidence == 0.0
    assert "warmup" in sig.reasoning


@pytest.mark.asyncio
async def test_returns_signal_after_warmup_bullish_ramp() -> None:
    """After warmup, the strategy returns a well-formed Signal.

    We only assert the *shape* of the return — action in {BUY, SELL, HOLD},
    confidence in [0, 1], rationale containing the decision-node audit trail
    — because the actual decision depends on weighted-consensus math that is
    covered exhaustively in test_llm_graph.py / test_llm_decision.py.
    """
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
    )
    last: Signal | None = None
    # +1 past WARMUP so the gate clears.
    for i in range(WARMUP_BARS + 5):
        last = await strat.on_bar(_bar(i), _ctx())
    assert last is not None
    assert isinstance(last, Signal)
    assert last.action in (Action.BUY, Action.SELL, Action.HOLD)
    assert 0.0 <= last.confidence <= 1.0
    # Rationale comes from the deterministic decision node.
    assert "buy=" in last.reasoning
    assert "sell=" in last.reasoning


@pytest.mark.asyncio
async def test_non_hold_signal_carries_finite_stop_loss() -> None:
    """Non-HOLD signals must ship with a SuperTrend-derived stop_loss.

    The `core/engine` opens positions only when `signal.stop_loss is not None`
    (see `core/engine.py:84` and `core/engine_sync.py:98`). Returning
    ``stop_loss=None`` silently blocks every LLM entry — this regression is
    what made the bot trade zero times across the entire run history.

    With a bullish synthetic ramp + `MockClient`, Technical and QABBA both
    vote BUY (Visual is HOLD), so the weighted-consensus decision is BUY at
    high confidence. We assert (a) the signal is non-HOLD as expected, and
    (b) the stop is finite and below the latest close (long stop placement).
    """
    # Threshold below MockClient's BUY mass (Technical 0.7 * 0.25 + QABBA 0.7 *
    # 0.4 = 0.455 of the BUY pool with Visual at 0.5 weight on HOLD); a 0.2
    # threshold guarantees a BUY decision regardless of weight tweaks.
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
        consensus_threshold=0.2,
    )
    last: Signal | None = None
    last_bar: Bar | None = None
    # +5 past warmup so consensus has stable indicator inputs.
    for i in range(WARMUP_BARS + 5):
        last_bar = _bar(i)
        last = await strat.on_bar(last_bar, _ctx())
    assert last is not None
    assert last_bar is not None
    assert last.action is Action.BUY, f"expected BUY on bullish ramp, got {last.action}"
    assert last.stop_loss is not None, "non-HOLD signal must carry a stop_loss"
    import math

    assert math.isfinite(last.stop_loss)
    # SuperTrend on a long is the trailing line *below* price.
    assert last.stop_loss < last_bar.close, (
        f"long stop {last.stop_loss} must sit below close {last_bar.close}"
    )


@pytest.mark.asyncio
async def test_hold_signal_has_none_stop_loss() -> None:
    """HOLD signals do not need a stop and must explicitly carry None."""
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        render_image=False,
    )
    # Warmup HOLDs are emitted without invoking the graph.
    sig: Signal | None = None
    for i in range(WARMUP_BARS - 1):
        sig = await strat.on_bar(_bar(i), _ctx())
    assert sig is not None
    assert sig.action is Action.HOLD
    assert sig.stop_loss is None


@pytest.mark.asyncio
async def test_strategy_routes_through_cached_client_per_agent(tmp_path) -> None:
    """Strategy must invoke the graph via the injected (Cached) client.

    Indirectly validates the bar_ts plumbing: CachedClient writes one file per
    (model, agent, prompt_hash, image_hash, bar_ts) tuple. After running past
    warmup, all three analyst agents must have cache entries in their own
    sub-directories — this confirms (a) the strategy uses the injected client
    (not a fresh one), (b) bar_ts is hashable / serializable, and (c) the
    layout matches spec §6.
    """
    from llm.cache import CachedClient

    cached = CachedClient(inner=MockClient(), cache_dir=tmp_path)
    strat = LLMAgentStrategy(client=cached, model="mock", render_image=False)
    for i in range(WARMUP_BARS + 2):
        await strat.on_bar(_bar(i), _ctx())
    files = list(tmp_path.rglob("*.json"))
    assert len(files) > 0
    # Cache layout: <cache_dir>/<model_safe>/<agent>/<key>.json
    agents = {p.parent.name for p in files}
    assert agents == {"technical", "visual", "qabba"}


@pytest.mark.asyncio
async def test_render_image_true_path_does_not_crash() -> None:
    """Exercise the mplfinance render path end-to-end (one bar past warmup)."""
    strat = LLMAgentStrategy(
        client=MockClient(),
        model="mock",
        image_window_bars=30,
        render_image=True,
    )
    last: Signal | None = None
    for i in range(WARMUP_BARS + 1):
        last = await strat.on_bar(_bar(i), _ctx())
    assert last is not None
    assert isinstance(last, Signal)


# ──────────────────────────────────────────────────────────────────────────
# H2 + H3: warmup deep enough for MACD-hist + defensive NaN guard.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warmup_is_at_least_macd_hist_first_finite_index() -> None:
    """`WARMUP_BARS` must be large enough that MACD(12,26,9).hist is finite
    on the first post-warmup bar.

    EMA(slow=26) first non-NaN at bar index 25; the MACD signal line is
    EMA(9) over the dropna'd MACD line, so its first non-NaN value sits at
    original index 25 + 8 = 33 (zero-based). To have a finite ``hist`` on
    bar number N (1-indexed), we need ``N - 1 >= 33`` ⇒ ``N >= 34``.

    Pre-fix ``WARMUP_BARS=30`` produced ``hist=nan``, which `_fmt` rendered
    as the literal string ``"nan"`` into the technical analyst prompt (see
    audit H2). 60 is a safe ceiling that also matches the SuperTrend depth
    used by `TraditionalStrategy`.
    """
    assert WARMUP_BARS >= 34, (
        f"WARMUP_BARS={WARMUP_BARS} is below the MACD-hist finite threshold; "
        f"the strategy will emit 'macd_hist=nan' into prompts"
    )


@pytest.mark.asyncio
async def test_features_finite_on_first_post_warmup_bar() -> None:
    """Integration: after exactly WARMUP_BARS bars, every indicator value
    fed to the prompts is finite.

    We capture the prompt strings via a recording client and assert the
    technical prompt never contains the literal token 'nan'. This catches
    both (a) WARMUP_BARS being too small and (b) any future refactor that
    adds a slower indicator without bumping warmup.
    """
    import math
    import re

    from llm.client import LLMResponse

    class _RecordingClient:
        """Captures the most recent prompt for each agent."""

        def __init__(self) -> None:
            self.last_prompts: dict[str, str] = {}

        async def complete(
            self,
            *,
            agent: str,
            prompt: str,
            image_b64: str | None = None,  # noqa: ARG002
            model: str = "mock",
        ) -> LLMResponse:
            self.last_prompts[agent] = prompt
            return LLMResponse(
                content="HOLD 0.5 recording", model=model,
                input_tokens=0, output_tokens=0,
            )

    client = _RecordingClient()
    strat = LLMAgentStrategy(client=client, model="mock", render_image=False)
    last_sig: Signal | None = None
    for i in range(WARMUP_BARS):
        last_sig = await strat.on_bar(_bar(i), _ctx())

    # The WARMUP_BARS-th call (1-indexed) is the first that invokes the graph.
    assert last_sig is not None
    assert "technical" in client.last_prompts, (
        "graph must have been invoked on the first post-warmup bar"
    )
    tech_prompt = client.last_prompts["technical"]
    # Reject the literal token 'nan' (case-insensitive, word-boundary).
    assert not re.search(r"\bnan\b", tech_prompt, re.IGNORECASE), (
        f"technical prompt leaked a NaN indicator value:\n{tech_prompt}"
    )
    # Belt-and-braces: each numeric value parses to a finite float.
    for match in re.finditer(r"(\w+)=(-?\d+\.?\d*)", tech_prompt):
        key, val = match.group(1), match.group(2)
        assert math.isfinite(float(val)), f"{key}={val} is not finite"
    # H1: the Technical analyst prompt advertises 'adx' (prompts.py:36) — the
    # strategy must actually supply it. The Traditional strategy uses ADX as
    # its regime filter at length 14; the LLM strategy mirrors that choice.
    assert re.search(r"\badx=(-?\d+\.?\d*)\b", tech_prompt), (
        f"technical prompt missing the 'adx' feature it advertises:\n{tech_prompt}"
    )


@pytest.mark.asyncio
async def test_nan_indicator_yields_hold_not_propagated() -> None:
    """Defensive guard: if any indicator value is NaN at decision time, the
    strategy must HOLD instead of emitting 'nan' into the prompt.

    This is independent of `WARMUP_BARS` — a future indicator addition or
    a pathological bar series could still produce a NaN. The strategy must
    never serialize NaN as a feature value.

    We construct a degenerate case: all bars have identical close → RSI's
    avg_loss is zero → ``avg_gain / avg_loss`` is ``0/0 == NaN``. Even at
    WARMUP_BARS the strategy must return HOLD with a clear rationale, not
    invoke the graph with rsi=nan.
    """
    from llm.client import LLMResponse

    class _AssertNoNanClient:
        """Fails the test if any prompt ever contains 'nan'."""

        def __init__(self) -> None:
            self.called = False

        async def complete(
            self,
            *,
            agent: str,  # noqa: ARG002
            prompt: str,
            image_b64: str | None = None,  # noqa: ARG002
            model: str = "mock",
        ) -> LLMResponse:
            self.called = True
            import re

            assert not re.search(r"\bnan\b", prompt, re.IGNORECASE), (
                f"prompt leaked nan despite guard:\n{prompt}"
            )
            return LLMResponse(
                content="HOLD 0.5 nan-guard", model=model,
                input_tokens=0, output_tokens=0,
            )

    client = _AssertNoNanClient()
    strat = LLMAgentStrategy(client=client, model="mock", render_image=False)
    # Flat-close ramp: all close==50_000 ⇒ RSI denominator is 0 ⇒ NaN.
    sig: Signal | None = None
    for i in range(WARMUP_BARS + 5):
        sig = await strat.on_bar(_bar(i, close=50_000.0), _ctx())
    assert sig is not None
    assert sig.action is Action.HOLD, (
        f"NaN indicator must yield HOLD, got {sig.action}"
    )
    assert sig.stop_loss is None
    # Either the graph was never called (guard short-circuited) or, if it
    # was, every prompt was nan-free (asserted inside the client).
