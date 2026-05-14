"""Tests for `strategies.llm_agents.chart` — mplfinance base64 PNG renderer."""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from core.types import Bar
from strategies.llm_agents.chart import render_chart


def _synthetic_bars(n: int = 60) -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    price = 50_000.0
    for i in range(n):
        o = price
        c = price * (1.0 + (0.001 if i % 2 == 0 else -0.001))
        h = max(o, c) * 1.001
        low = min(o, c) * 0.999
        bars.append(
            Bar(
                timestamp=start + timedelta(hours=i),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=10.0,
                taker_buy_volume=5.0,
                cvd=0.0,
                cvd_delta=0.0,
            )
        )
        price = c
    return bars


def test_render_chart_returns_base64_png():
    bars = _synthetic_bars(60)
    b64 = render_chart(bars)
    assert isinstance(b64, str)
    raw = base64.b64decode(b64)
    # PNG magic header
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_chart_empty_bars_raises():
    with pytest.raises(ValueError):
        render_chart([])


def test_render_chart_single_bar_still_renders():
    bars = _synthetic_bars(1)
    b64 = render_chart(bars)
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_chart_deterministic_within_process():
    """Same bars → byte-identical PNG within one process (cache-replay invariant)."""
    bars = _synthetic_bars(30)
    a = render_chart(bars)
    b = render_chart(bars)
    assert a == b


def test_render_chart_differs_when_bars_differ():
    bars1 = _synthetic_bars(30)
    bars2 = _synthetic_bars(31)
    assert render_chart(bars1) != render_chart(bars2)


def test_render_chart_custom_size():
    bars = _synthetic_bars(20)
    b64 = render_chart(bars, width_px=400, height_px=240)
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
