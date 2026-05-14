"""Rich layout components for the dual-bot TUI (Task 6 + Task 7 live ticker)."""

from __future__ import annotations

import asyncio
from collections import deque

from rich.console import Console
from rich.panel import Panel

from core import ui
from core.run_state import RunState


def _make_populated_run_state() -> RunState:
    """Build a fully populated RunState matching the spec fixture."""
    rs = RunState(symbol="BTC/USDT", timeframe="1h", total_bars=10)
    rs.current_bar = 10
    rs.bar_ts = "2025-04-01T05:00:00"
    rs.bar_close = 68000.0
    rs.trad_equity = 10250.0
    rs.llm_equity = 9800.0
    rs.trad_curve = [
        10000.0, 10050.0, 10080.0, 10120.0, 10100.0,
        10150.0, 10180.0, 10200.0, 10230.0, 10250.0,
    ]
    rs.llm_curve = [
        10000.0, 9990.0, 9970.0, 9950.0, 9920.0,
        9900.0, 9880.0, 9860.0, 9830.0, 9800.0,
    ]
    rs.trad_trades = 2
    rs.llm_trades = 1
    rs.trad_win_pct = 50.0
    rs.llm_win_pct = 0.0
    rs.trad_mdd = -1.5
    rs.llm_mdd = -2.0
    rs.last_trad_signal = "BUY"
    rs.last_trad_rationale = "EMA20>EMA50, RSI=55"
    rs.llm_reasoning = deque(
        ["Bullish trend confirmed", "Volume rising"], maxlen=10,
    )
    rs.cache_hits = 7
    rs.cache_misses = 3
    rs.spend_usd = 0.42
    rs.budget_usd = 5.0
    return rs


def test_layout_renders() -> None:
    """build_layout renders a populated RunState with all expected content."""
    rs = _make_populated_run_state()
    console = Console(record=True, width=120)
    layout = ui.build_layout(rs)
    console.print(layout)
    out = console.export_text()

    # Header fields.
    assert "BTC/USDT" in out
    assert "1h" in out
    assert "10/10" in out
    assert "68,000.00" in out
    # Bot panel stats.
    assert "10,250" in out
    assert "BUY" in out
    assert "EMA20" in out
    assert "Bullish" in out
    # Footer.
    assert "cache hit 70%" in out
    assert "$0.42" in out
    assert "$5.00" in out


def test_render_panels_shape() -> None:
    """render_panels returns the four expected regions as Rich Panels."""
    rs = _make_populated_run_state()
    panels = ui.render_panels(rs)
    assert set(panels.keys()) == {"header", "trad", "llm", "footer"}
    for v in panels.values():
        assert isinstance(v, Panel)


def test_sparkline_length_short() -> None:
    assert len(ui._sparkline([1.0, 2.0, 3.0])) == 3


def test_sparkline_length_clamped_to_width() -> None:
    assert len(ui._sparkline([1.0] * 100, width=50)) == 50


def test_sparkline_empty() -> None:
    assert ui._sparkline([]) == ""


def test_sparkline_all_equal_middle_level() -> None:
    """All-equal values map to a single middle-level char repeated."""
    out = ui._sparkline([1.0, 1.0, 1.0])
    assert len(out) == 3
    # All chars identical and from the bar-char set.
    assert len(set(out)) == 1
    assert out[0] in "▁▂▃▄▅▆▇█"


def test_sparkline_min_max_endpoints() -> None:
    """Two-value spark: min → lowest bar, max → highest bar."""
    out = ui._sparkline([1.0, 10.0])
    assert len(out) == 2
    assert out[0] == "▁"
    assert out[1] == "█"


def test_footer_cache_hit_zero_when_no_traffic() -> None:
    """Footer must not divide by zero when no cache traffic yet."""
    rs = RunState(symbol="BTC/USDT", timeframe="1h", total_bars=10)
    panels = ui.render_panels(rs)
    console = Console(record=True, width=120)
    console.print(panels["footer"])
    out = console.export_text()
    assert "cache hit 0%" in out


def test_header_handles_none_bar_ts() -> None:
    """_header must not crash when bar_ts is None / bar_close is 0.0."""
    rs = RunState(symbol="ETH/USDT", timeframe="4h", total_bars=5)
    # bar_ts stays None, bar_close stays 0.0
    layout = ui.build_layout(rs)
    console = Console(record=True, width=120)
    console.print(layout)  # must not raise
    out = console.export_text()
    assert "ETH/USDT" in out
    assert "4h" in out


async def test_live_ticker_redraws() -> None:
    """start_live should redraw the layout as RunState mutates."""
    rs = RunState(symbol="BTC/USDT", timeframe="1h", total_bars=20)
    rs.bar_close = 50000.0
    console = Console(record=True, width=120, force_terminal=True)
    await ui.start_live(rs, console=console, interval=0.02)
    try:
        for i in range(1, 6):
            rs.current_bar = i * 4  # 4, 8, 12, 16, 20
            await asyncio.sleep(0.05)  # let the ticker tick at least once
    finally:
        await ui.stop_live()
    out = console.export_text()
    # Require ≥2 distinct bar numbers to prove the ticker re-read RunState
    # across mutations, not just that a single early frame rendered.
    hits = [n for n in (4, 8, 12, 16, 20) if f"{n}/20" in out]
    assert len(hits) >= 2, (
        f"Expected ≥2 distinct bar numbers, got {hits}. Output: {out[:500]}"
    )


async def test_stop_live_idempotent() -> None:
    """stop_live must be a no-op when nothing is running."""
    await ui.stop_live()  # before any start
    rs = RunState(symbol="X", timeframe="1h", total_bars=2)
    await ui.start_live(rs, console=Console(record=True), interval=0.01)
    await asyncio.sleep(0.02)
    await ui.stop_live()
    await ui.stop_live()  # second call should be a no-op
