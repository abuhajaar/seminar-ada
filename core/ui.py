"""Rich layout components for the dual-bot TUI.

This module renders a static snapshot of `RunState` into a `rich.layout.Layout`
divided into four regions:

    +-------------------------- header --------------------------+
    |                trad              |               llm        |
    +-------------------------- footer --------------------------+

The live ticker (Task 7) wraps `build_layout` in `rich.live.Live`. This module
itself is fully synchronous and pure — it only reads `RunState`, never mutates.

Key public surface:
    - `build_layout(run_state)` → `rich.layout.Layout`
    - `render_panels(run_state)` → `dict[str, Panel]` (exposed for tests)
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.run_state import RunState

_BAR_CHARS = "▁▂▃▄▅▆▇█"
_MID_CHAR = _BAR_CHARS[len(_BAR_CHARS) // 2]  # "▄"


def _sparkline(values: list[float], width: int = 50) -> str:
    """Map ``values`` to an 8-level unicode bar-chart string.

    Behaviour:
        * empty input → ``""``
        * ``len(values) > width`` → keep the trailing ``width`` points
        * all values equal → all middle-level chars (no division by zero)
        * otherwise linearly scale min..max onto ``_BAR_CHARS``

    The returned string length always equals ``min(width, len(values))``.
    """
    if not values:
        return ""
    sample = values[-width:] if len(values) > width else values
    lo = min(sample)
    hi = max(sample)
    if hi == lo:
        return _MID_CHAR * len(sample)
    span = hi - lo
    n = len(_BAR_CHARS)
    chars: list[str] = []
    for v in sample:
        # Normalise to [0, 1] then bucket into [0, n-1].
        frac = (v - lo) / span
        idx = int(frac * (n - 1) + 0.5)  # round to nearest
        if idx < 0:
            idx = 0
        elif idx >= n:
            idx = n - 1
        chars.append(_BAR_CHARS[idx])
    return "".join(chars)


def _header(rs: RunState) -> Panel:
    """Top strip: symbol, timeframe, bar progress, timestamp, last close."""
    ts_str = "—" if rs.bar_ts is None else str(rs.bar_ts)
    close_str = f"${rs.bar_close:,.2f}"
    body = (
        f"{rs.symbol}  {rs.timeframe}  |  "
        f"Bar {rs.current_bar}/{rs.total_bars}  |  "
        f"{ts_str}  |  {close_str}"
    )
    return Panel(Text(body, style="bold"), title="run", border_style="cyan")


def _bot_panel(
    name: str,
    equity: float,
    trades: int,
    win_pct: float,
    mdd: float,
    curve: list[float],
    last_signal: str | None,
    rationale: str | None,
) -> Panel:
    """Render one bot's stats as a table + sparkline inside a Panel.

    Multi-line ``rationale`` (the LLM panel) is rendered verbatim; the trad
    panel typically passes a one-line summary. Missing values display as ``—``.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="dim")
    table.add_column(justify="left")

    table.add_row("equity", f"${equity:,.2f}")
    table.add_row("trades", str(trades))
    table.add_row("win %", f"{win_pct:.1f}")
    table.add_row("max DD", f"{mdd:.2f}%")
    table.add_row("signal", last_signal if last_signal else "—")

    rationale_text = rationale if rationale else "—"
    table.add_row("note", rationale_text)

    spark = _sparkline(curve) if curve else ""
    if spark:
        table.add_row("curve", spark)

    style = "green" if name.lower().startswith("trad") else "magenta"
    return Panel(table, title=name, border_style=style)


def _footer(rs: RunState) -> Panel:
    """Bottom strip: cache hit-rate and budget spend."""
    total = rs.cache_hits + rs.cache_misses
    hit_pct = 0 if total == 0 else round(100 * rs.cache_hits / total)
    body = (
        f"cache hit {hit_pct}%  "
        f"spend ${rs.spend_usd:.2f}/${rs.budget_usd:.2f}"
    )
    return Panel(Text(body), title="budget", border_style="yellow")


def render_panels(run_state: RunState) -> dict[str, RenderableType]:
    """Return the four region Panels keyed by layout region name.

    Exposed for direct testing and reuse by the Task 7 live ticker.
    """
    trad_panel = _bot_panel(
        name="Traditional",
        equity=run_state.trad_equity,
        trades=run_state.trad_trades,
        win_pct=run_state.trad_win_pct,
        mdd=run_state.trad_mdd,
        curve=run_state.trad_curve,
        last_signal=run_state.last_trad_signal,
        rationale=run_state.last_trad_rationale or None,
    )

    # LLM rationale is a deque of the last 10 messages; render newest-last.
    llm_rationale = (
        "\n".join(run_state.llm_reasoning) if run_state.llm_reasoning else None
    )
    llm_panel = _bot_panel(
        name="LLM",
        equity=run_state.llm_equity,
        trades=run_state.llm_trades,
        win_pct=run_state.llm_win_pct,
        mdd=run_state.llm_mdd,
        curve=run_state.llm_curve,
        last_signal=None,  # LLM bot logs full rationale rather than a label
        rationale=llm_rationale,
    )

    return {
        "header": _header(run_state),
        "trad": trad_panel,
        "llm": llm_panel,
        "footer": _footer(run_state),
    }


def build_layout(run_state: RunState) -> Layout:
    """Compose the four panels into a Rich Layout.

    Layout shape: header on top (3 rows), trad/llm side-by-side in the middle,
    footer on the bottom (3 rows). The middle row expands to fill remaining
    vertical space.
    """
    panels = render_panels(run_state)

    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="trad", ratio=1),
        Layout(name="llm", ratio=1),
    )

    layout["header"].update(panels["header"])
    layout["body"]["trad"].update(panels["trad"])
    layout["body"]["llm"].update(panels["llm"])
    layout["footer"].update(panels["footer"])

    return layout
