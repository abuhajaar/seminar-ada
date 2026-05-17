# Seminar Presentation Materials — Advanced Data Analysis Framing

30-minute seminar presentation for the project **"Comparative Study: Classical Technical Analysis vs LLM Multi-Agent Trading on BTC/USDT"**.

The presentation is reframed for an **Advanced Data Analysis** audience: most of the time is spent on the data pipeline itself — where data comes from, what it literally looks like, how it is transformed, what each agent sees, and how a signal becomes a trade.

## Files

| File | Purpose |
|---|---|
| `slide_outline.md` | Slide-by-slide structure (24 slides, language-neutral) |
| `script_en.md` | English delivery script with time anchors and slide markers |
| `script_id.md` | Indonesian script (semi-formal, BI baku + EN technical terms) |
| `demo_cheatsheet.md` | Exact commands for the live cache-replay demo, contingency plan |

## Time Allocation (30 minutes) — Data-Pipeline-Heavy

| # | Section | Slides | Time | Cum. |
|---|---|---|---|---|
| 1 | Intro & problem statement | 1–2 | 3 min | 03:00 |
| 2 | Data source & raw API format | 3–6 | 4 min | 07:00 |
| 3 | Preprocessing & indicator transformations | 7–10 | 5 min | 12:00 |
| 4 | Traditional bot: data → signal → trade | 11–13 | 4 min | 16:00 |
| 5 | LLM bot: features → 3 agents → consensus → trade | 14–19 | 6 min | 22:00 |
| 6 | Live cache-replay demo | 20 | 3 min | 25:00 |
| 7 | Results — comparative finding | 21–23 | 3 min | 28:00 |
| 8 | Honest conclusion + Q&A | 24 | 2 min | 30:00 |

## Delivery Format

Each script section uses:

- `[SLIDE N: title]` — change slide here
- `[XX:XX]` — running clock anchor (target time to be at this point)
- Plain spoken text (delivery-ready, ~150 words/minute)
- `[BULLETS]` — what the slide should display
- `[NOTE TO PRESENTER]` — delivery cues (pause, gesture, switch to terminal)

## Demo Strategy

**Live cache replay** — `main.py` runs against committed LLM cache in `cache/llm/anthropic_claude-haiku-4.5/`. No API calls, no network dependency, completes in ~30 seconds. Looks live, cannot fail. See `demo_cheatsheet.md`.

## Honesty Principle

The LLM bot **lost money** in the test window (−6.20% vs Traditional +3.07%). The script frames this as the **finding**, not a failure to hide. This is what makes the project academically defensible: the comparative measurement framework is the contribution, not "LLM wins".

## Code References (for Q&A)

| Topic | File | Line |
|---|---|---|
| Binance kline endpoint | `data/downloader.py` | 84 |
| OHLCV → Bar streaming | `data/loader.py` | 19 |
| CVD derivation from kline | `data/cvd.py` | 50 |
| SuperTrend math | `indicators/ta.py` | 124 |
| Traditional rules | `strategies/traditional.py` | 47 |
| LLM strategy entry | `strategies/llm_agents/strategy.py` | 81 |
| Technical prompt template | `strategies/llm_agents/prompts.py` | 34 |
| QABBA prompt template | `strategies/llm_agents/prompts.py` | 45 |
| Visual prompt template | `strategies/llm_agents/prompts.py` | 59 |
| Decision math (Q/V/T) | `strategies/llm_agents/nodes/decision.py` | 33 |
| LangGraph wiring | `strategies/llm_agents/graph.py` | 45 |
| Per-bar engine loop | `core/engine.py` | 175 |
| Position sizing | `core/engine_sync.py` | 29 |
| Stop-loss check | `core/broker.py` | 81 |
| Regime gate (C3 fix) | `strategies/llm_agents/strategy.py` | 184 |
