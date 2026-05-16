"""Typer CLI entrypoint for the seminar comparative backtest.

Assembles the LLM client stack (mock / OpenRouter → BudgetGuard tracking →
disk-backed cache), builds fresh strategy pairs per asset, and drives the
multi-asset walk-forward runner. Optionally renders a Rich live TUI ticker.

Usage::

    uv run python main.py --mock                 # deterministic offline replay
    uv run python main.py                        # live OpenRouter (needs API key)
    uv run python main.py --no-tui --assets BTC/USDT --start 2025-04-01 --end 2025-04-21

TUI integration note: the walk-forward loop iterates assets and creates a
fresh ``RunState`` per asset. The ``start_live`` ticker reads a *single*
``RunState`` instance. To bridge these, we pass a tiny ``_LiveProxy`` that
attribute-forwards to whichever ``RunState`` is current; the per-asset
factory swaps the holder before each engine call. This keeps ``core.ui``
unchanged while letting one persistent ticker follow the whole run.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import dotenv
import typer
from rich.console import Console
from rich.table import Table

from core import ui, walkforward
from core.config import load_config
from core.run_state import RunState
from data.loader import load_bars
from data.paths import DEFAULT_ROOT
from llm.budget import BudgetGuard
from llm.budget_client import BudgetGuardedClient, ModelPricing
from llm.cache import CachedClient
from llm.client import MockClient, OpenRouterClient
from strategies.base import Strategy
from strategies.llm_agents.strategy import LLMAgentStrategy
from strategies.traditional import TraditionalStrategy

app = typer.Typer(add_completion=False, help="Comparative backtest: Traditional vs LLM agents.")


class _LiveProxy:
    """Attribute-forwarding stand-in for whichever RunState is current.

    The walk-forward loop creates a fresh ``RunState`` per asset. The Rich
    ticker, by contrast, captures the object reference once when ``start_live``
    is called. We pass a proxy whose ``__getattr__`` reads through a mutable
    holder so a single long-lived ticker can follow every asset.
    """

    def __init__(self, holder: dict[str, RunState]) -> None:
        object.__setattr__(self, "_holder", holder)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._holder["rs"], name)


def _parse_date(s: str | None, fallback: date) -> date:
    if s is None:
        return fallback
    return date.fromisoformat(s)


def _pick_llm_model(cfg: Any) -> str:
    """Pick a model id for ``LLMAgentStrategy``.

    The legacy single-model layout is not part of the current config schema
    (each agent has its own model). The strategy is parameterized by *one*
    model string — we prefer the ``decision`` agent's model because it's the
    final voter; if absent fall back to any agent.
    """
    agents = cfg.llm.agents
    if "decision" in agents:
        return agents["decision"].model
    # Fall back to the first agent in declaration order.
    return next(iter(agents.values())).model


def _print_summary_table(console: Console, results: dict[str, dict[str, Any]]) -> None:
    table = Table(title="Walk-forward results", show_lines=True)
    table.add_column("Asset", style="cyan", no_wrap=True)
    table.add_column("Strategy", style="bold")
    table.add_column("Return %", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win %", justify="right")
    table.add_column("Max DD %", justify="right")
    table.add_column("Status", style="dim")

    for asset, by_strat in results.items():
        for leg in ("trad", "llm"):
            m = by_strat.get(leg, {})
            status = str(m.get("status", "ok"))
            if status == "ok":
                ret = f"{m.get('total_return_pct', 0.0):.2f}"
                trades = str(m.get("num_trades", 0))
                winp = f"{m.get('win_rate_pct', 0.0):.1f}"
                mdd = f"{m.get('max_drawdown_pct', 0.0):.2f}"
            else:
                ret = trades = winp = mdd = "—"
            table.add_row(asset, leg, ret, trades, winp, mdd, status)

    console.print(table)


@app.command()
def run(
    config: Path = typer.Option(  # noqa: B008
        Path("config.yaml"), "--config", help="Path to config.yaml."
    ),
    mock: bool = typer.Option(  # noqa: B008
        False, "--mock", help="Use deterministic MockClient (no API key needed)."
    ),
    no_tui: bool = typer.Option(  # noqa: B008
        False, "--no-tui", help="Disable the live Rich TUI ticker."
    ),
    assets: list[str] | None = typer.Option(  # noqa: B008
        None, "--assets",
        help="Override cfg.run.assets (repeatable or comma-separated).",
    ),
    start: str | None = typer.Option(  # noqa: B008
        None, "--start", help="Override start date (ISO YYYY-MM-DD)."
    ),
    end: str | None = typer.Option(  # noqa: B008
        None, "--end", help="Override end date (ISO YYYY-MM-DD)."
    ),
    out_dir: Path = typer.Option(  # noqa: B008
        Path("results"), "--out-dir",
        help="Output root; runs are written to <out_dir>/runs/<ts>/.",
    ),
    data_root: Path = typer.Option(  # noqa: B008
        DEFAULT_ROOT, "--data-root", help="Override data cache root."
    ),
) -> None:
    """Run the comparative walk-forward backtest."""
    dotenv.load_dotenv()

    cfg = load_config(config)

    # CLI overrides.
    if assets:
        # Support both repeated --assets and a single comma-separated value.
        flat: list[str] = []
        for a in assets:
            flat.extend(part.strip() for part in a.split(",") if part.strip())
        cfg.run.assets = flat
    cfg.run.start = _parse_date(start, cfg.run.start)
    cfg.run.end = _parse_date(end, cfg.run.end)

    # walkforward.run reads attrs off cfg.run / cfg.execution. The Pydantic
    # model is frozen against unknown fields, so we wrap it in plain
    # SimpleNamespaces just to attach out_dir (the canonical pattern used by
    # tests/test_walkforward.py).
    wf_cfg = SimpleNamespace(
        run=SimpleNamespace(
            assets=cfg.run.assets,
            timeframe=cfg.run.timeframe,
            start=cfg.run.start,
            end=cfg.run.end,
            initial_balance=cfg.run.initial_balance,
            out_dir=out_dir,
        ),
        execution=SimpleNamespace(
            taker_fee_bps=cfg.execution.taker_fee_bps,
            slippage_bps=cfg.execution.slippage_bps,
            risk_pct=cfg.execution.risk_pct,
        ),
    )

    console = Console()

    # ── Build LLM client stack ────────────────────────────────────────────
    # Layering: BudgetGuardedClient -> CachedClient -> inner.
    # Cache hits short-circuit inside CachedClient and never reach the guard
    # — pre-warmed seminar replays stay free even when the cap is exhausted.
    if mock:
        inner = MockClient()
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            console.print(
                "[red]ERROR:[/red] OPENROUTER_API_KEY is not set. "
                "Pass --mock for an offline run, or populate .env."
            )
            raise typer.Exit(code=2)
        inner = OpenRouterClient(api_key=api_key)

    cached = CachedClient(inner, cache_dir=Path(cfg.llm.cache_dir))

    guard: BudgetGuard | None = None
    if mock:
        client = cached
    else:
        guard = BudgetGuard(cap_usd=cfg.llm.max_usd)
        pricing = {
            m: ModelPricing(**p.model_dump())
            for m, p in cfg.llm.pricing.items()
        }
        client = BudgetGuardedClient(
            inner=cached,
            guard=guard,
            pricing=pricing,
            expected_output_tokens=cfg.llm.expected_output_tokens,
        )

    llm_model = _pick_llm_model(cfg)

    # ── Closures captured by walkforward.run ──────────────────────────────
    def bars_loader(symbol: str):
        return load_bars(
            symbol,
            wf_cfg.run.timeframe,
            wf_cfg.run.start,
            wf_cfg.run.end,
            root=Path(data_root),
        )

    def build_strategies(symbol: str) -> tuple[Strategy, Strategy]:
        trad = TraditionalStrategy()
        llm = LLMAgentStrategy(
            client=client,
            model=llm_model,
            image_window_bars=cfg.llm.image_window_bars,
            consensus_weights=cfg.llm.consensus_weights,
            consensus_threshold=cfg.llm.consensus_threshold,
        )
        return trad, llm

    # ── TUI plumbing (option B: LiveProxy follows current asset) ──────────
    rs_holder: dict[str, RunState] = {
        "rs": RunState(symbol="—", timeframe=wf_cfg.run.timeframe, total_bars=0),
    }
    rs_holder["rs"].budget_usd = cfg.llm.max_usd

    def run_state_factory(symbol: str) -> RunState:
        rs = RunState(symbol=symbol, timeframe=wf_cfg.run.timeframe, total_bars=0)
        rs.budget_usd = cfg.llm.max_usd
        rs_holder["rs"] = rs
        return rs

    # Always install the factory: in both --tui and --no-tui modes we want
    # rs_holder["rs"] to advance per asset so _on_progress writes to the
    # *current* RunState rather than the initial placeholder.
    rsf = run_state_factory

    def _on_progress(_symbol: str, _idx: int, _total: int) -> None:
        if guard is not None:
            rs_holder["rs"].spend_usd = guard.spent_usd

    async def _main() -> dict[str, dict[str, Any]]:
        if no_tui:
            return await walkforward.run(
                wf_cfg.run.assets, bars_loader, build_strategies, wf_cfg,
                run_state_factory=rsf,
                on_progress=_on_progress,
            )
        # Live ticker reads through the proxy; engine writes to whichever
        # RunState run_state_factory just minted.
        proxy = _LiveProxy(rs_holder)
        await ui.start_live(proxy, console=console, interval=0.25)  # type: ignore[arg-type]
        try:
            return await walkforward.run(
                wf_cfg.run.assets, bars_loader, build_strategies, wf_cfg,
                run_state_factory=rsf,
                on_progress=_on_progress,
            )
        finally:
            await ui.stop_live()

    started_at = datetime.now()
    results = asyncio.run(_main())
    elapsed = (datetime.now() - started_at).total_seconds()

    # ── Final summary ─────────────────────────────────────────────────────
    _print_summary_table(console, results)
    console.print(f"[dim]Elapsed:[/dim] {elapsed:.2f}s")

    # Locate the summary.json that walkforward just wrote (most-recent run dir).
    runs_root = out_dir / "runs"
    summary_path: Path | None = None
    if runs_root.exists():
        candidates = sorted(runs_root.glob("*/summary.json"))
        if candidates:
            summary_path = candidates[-1]
    if summary_path is not None:
        console.print(f"[green]summary.json:[/green] {summary_path}")
    else:
        # Surface the in-memory results so a no-out-dir / failed-write case
        # still leaves the user with something machine-readable.
        console.print("[yellow]No summary.json found; results follow:[/yellow]")
        console.print(json.dumps(results, default=str, indent=2))


if __name__ == "__main__":
    app()
