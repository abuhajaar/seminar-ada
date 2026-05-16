"""Replay cached LLM votes through the configured decision node and tally outcomes.

Reads the parquet/csv data the same way the strategy did, rebuilds the prompts
to fetch the cached agent reports, and runs them through `make_decision_node`
with the current config values. Prints a BUY/SELL/HOLD tally and a sample of
the highest-confidence non-HOLD decisions.
"""
from __future__ import annotations

import asyncio
from collections import Counter, deque
from pathlib import Path

from core.config import load_config
from core.types import Action, AgentReport, Bar
from data.loader import load_bars
from llm.cache import CachedClient
from llm.client import OpenRouterClient
from strategies.llm_agents.chart import render_chart
from strategies.llm_agents.nodes.decision import make_decision_node
from strategies.llm_agents.prompts import (
    build_qabba_prompt,
    build_technical_prompt,
    build_visual_prompt,
)
import pandas as pd
from indicators.ta import ema, macd, rsi


async def main():
    cfg = load_config(Path("config.yaml"))
    bars = list(load_bars(
        cfg.run.assets[0], cfg.run.timeframe, cfg.run.start, cfg.run.end,
        root=Path("data/cache"),
    ))
    print(f"Loaded {len(bars)} bars from {bars[0].timestamp} to {bars[-1].timestamp}")

    # CachedClient with no inner -> raises on miss; perfect for replay-from-cache.
    class _Sentinel:
        async def complete(self, *a, **k):
            raise RuntimeError("cache MISS during replay")
    inner = _Sentinel()
    client = CachedClient(inner=inner, cache_dir=Path("cache/llm"))  # type: ignore

    decision = make_decision_node(
        weights=cfg.llm.consensus_weights, threshold=cfg.llm.consensus_threshold,
    )
    print(f"weights={cfg.llm.consensus_weights} threshold={cfg.llm.consensus_threshold}")

    rolling: deque[Bar] = deque()
    WARMUP = 30
    tally: Counter[str] = Counter()
    nontrivial = []
    for i, bar in enumerate(bars):
        rolling.append(bar)
        if len(rolling) < WARMUP:
            continue
        closes = pd.Series([b.close for b in rolling], dtype=float)
        ema_f = float(ema(closes, length=12).iloc[-1])
        ema_s = float(ema(closes, length=26).iloc[-1])
        rsi_v = float(rsi(closes, length=14).iloc[-1])
        macd_h = float(macd(closes, fast=12, slow=26, signal=9)["hist"].iloc[-1])
        features = {"ema_fast": ema_f, "ema_slow": ema_s, "rsi": rsi_v,
                    "macd_hist": macd_h, "cvd": float(bar.cvd), "cvd_delta": float(bar.cvd_delta)}
        img = render_chart(list(rolling)[-60:])
        model = "anthropic/claude-haiku-4.5"
        bar_ts_ms = int(bar.timestamp.timestamp() * 1000)

        tech_p = build_technical_prompt(features)
        vis_p = build_visual_prompt()
        qab_p = build_qabba_prompt(features)
        try:
            tech = await client.complete(prompt=tech_p, model=model, image_b64=None, agent="technical", bar_ts=bar_ts_ms)
            vis = await client.complete(prompt=vis_p, model=model, image_b64=img, agent="visual", bar_ts=bar_ts_ms)
            qab = await client.complete(prompt=qab_p, model=model, image_b64=None, agent="qabba", bar_ts=bar_ts_ms)
        except RuntimeError as e:
            print(f"bar {i} cache miss; aborting: {e}"); return

        def parse(c: str) -> AgentReport | None:
            parts = c.strip().split(maxsplit=2)
            if len(parts) < 2: return None
            act_s, conf_s = parts[0], parts[1]
            try: conf = float(conf_s)
            except ValueError: return None
            try: act = Action[act_s]
            except KeyError: return None
            return AgentReport(action=act, confidence=conf, rationale=parts[2] if len(parts) > 2 else "")

        state = {"bar_ts": 0, "features": features, "image_b64": img, "model": model,
                 "technical": parse(tech.content),
                 "visual": parse(vis.content),
                 "qabba": parse(qab.content),
                 "decision": None}
        out = await decision(state)
        d = out["decision"]
        tally[d.action.value] += 1
        if d.action is not Action.HOLD:
            nontrivial.append((bar.timestamp, d.action.value, d.confidence, d.rationale))

    print(f"\nDecision tally: {dict(tally)}")
    print(f"\nNon-HOLD decisions: {len(nontrivial)}")
    for ts, act, conf, rat in nontrivial[:20]:
        print(f"  {ts} {act} conf={conf:.3f}  {rat}")

asyncio.run(main())
