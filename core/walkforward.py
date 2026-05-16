"""Multi-asset walk-forward runner.

For each configured symbol:

1. Materialize bars once (so we can set ``RunState.total_bars`` up front).
2. Build a *fresh* (trad, llm) strategy pair via ``build_strategies(symbol)``
   — keeps per-asset state isolated; the LLM client stack stays shared via
   closure in the caller.
3. Optionally build a fresh ``RunState`` via ``run_state_factory(symbol)``.
4. Call ``engine.run_async`` to drive the dual-strategy bar loop.
5. If ``cfg.run.out_dir`` is set, persist per-asset CSV artifacts (trades and
   equity for each leg) into ``<out_dir>/runs/<ts>/<symbol_safe>/`` and write
   one aggregate ``summary.json`` at the run-dir root.
6. On ``BudgetExceededError`` mid-asset, ``engine.run_async`` raises before
   returning either portfolio, so *both* legs for that asset are discarded.
   The asset's entry becomes
   ``{"trad": {"status": "not_run"}, "llm": {"status": "budget_exceeded", ...}}``
   and the walk continues to the next asset. No per-asset CSV artifacts are
   written for a budget-exceeded asset, and it is omitted from the aggregate
   ``summary.json``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from core import engine, persistence
from core.run_state import RunState
from core.types import Bar
from llm.budget import BudgetExceededError
from strategies.base import Strategy

logger = logging.getLogger(__name__)


def _safe_symbol(symbol: str) -> str:
    """Filesystem-safe per-asset dirname."""
    return symbol.replace("/", "_").replace("\\", "_")


async def run(
    assets: list[str],
    bars_loader: Callable[[str], Iterable[Bar]],
    build_strategies: Callable[[str], tuple[Strategy, Strategy]],
    cfg: Any,
    *,
    run_state_factory: Callable[[str], RunState] | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the dual-strategy engine over every asset in ``assets``.

    Returns ``{symbol: {"trad": MetricsDict|dict, "llm": MetricsDict|dict}}``.
    LLM-leg dicts may carry ``{"status": "budget_exceeded", ...}`` if the
    budget cap was hit mid-run for that asset.
    """
    if not assets:
        # Early return — avoid creating an empty timestamped run directory.
        return {}

    initial_balance = cfg.run.initial_balance
    taker_fee_bps = cfg.execution.taker_fee_bps
    slippage_bps = cfg.execution.slippage_bps
    risk_pct = cfg.execution.risk_pct
    timeframe = cfg.run.timeframe
    out_dir = getattr(cfg.run, "out_dir", None)

    results: dict[str, dict[str, Any]] = {}

    # Set up the run directory once per walk-forward (not per asset) so all
    # assets share a single timestamped folder and one summary.json.
    run_dir = None
    if out_dir:
        run_dir = persistence.make_run_dir(out_dir)

    metrics_by_asset_for_summary: dict[str, dict[str, Any]] = {}

    for idx, symbol in enumerate(assets, start=1):
        bars = list(bars_loader(symbol))
        trad_strategy, llm_strategy = build_strategies(symbol)

        run_state: RunState | None = None
        if run_state_factory is not None:
            run_state = run_state_factory(symbol)
            run_state.symbol = symbol
            run_state.timeframe = timeframe
            run_state.total_bars = len(bars)

        trad_metrics: dict[str, Any] = {"status": "not_run"}
        llm_metrics: dict[str, Any] = {"status": "not_run"}
        trad_port = None
        llm_port = None

        try:
            trad_port, llm_port, trad_metrics, llm_metrics = await engine.run_async(
                bars=iter(bars),
                trad_strategy=trad_strategy,
                llm_strategy=llm_strategy,
                symbol=symbol,
                initial_balance=initial_balance,
                taker_fee_bps=taker_fee_bps,
                slippage_bps=slippage_bps,
                risk_pct=risk_pct,
                run_state=run_state,
            )
        except BudgetExceededError as e:
            # engine.run_async raised before returning portfolios, so both
            # legs are lost for this asset. trad_metrics stays {"status":
            # "not_run"} from above; we only fill in the llm side. The
            # spend_usd attr is populated by BudgetGuard.check_can_afford
            # (see sub-plan E task 1); the getattr fallback is defensive
            # against future callers raising the error directly.
            spend = getattr(e, "spend_usd", None) or 0.0
            llm_metrics = {
                "status": "budget_exceeded",
                "spend_usd": spend,
                "error": str(e),
            }
            logger.warning(
                "Budget exceeded for %s: %s. Continuing with remaining assets.",
                symbol, e,
            )

        # Persist per-asset CSV artifacts when out_dir is set AND the engine
        # succeeded for at least one leg (we have a Portfolio object to dump).
        if run_dir is not None and trad_port is not None and llm_port is not None:
            asset_dir = run_dir / _safe_symbol(symbol)
            asset_dir.mkdir(parents=True, exist_ok=True)
            persistence.write_trades(asset_dir / "trad_trades.csv", trad_port, timeframe=timeframe)
            persistence.write_trades(asset_dir / "llm_trades.csv", llm_port, timeframe=timeframe)
            persistence.write_equity(asset_dir / "trad_equity.csv", trad_port)
            persistence.write_equity(asset_dir / "llm_equity.csv", llm_port)
            metrics_by_asset_for_summary[symbol] = {
                "trad": trad_metrics,
                "llm": llm_metrics,
            }

        results[symbol] = {"trad": trad_metrics, "llm": llm_metrics}

        if on_progress is not None:
            on_progress(symbol, idx, len(assets))

    # Single summary.json across all assets, written at the run-dir root.
    # `write_summary` aggregates (mean/std) across assets; it assumes
    # MetricsDict-shaped entries, so only feed it assets whose engine call
    # actually completed.
    if run_dir is not None and metrics_by_asset_for_summary:
        persistence.write_summary(
            run_dir / "summary.json",
            metrics_by_asset_for_summary,
        )

    return results
