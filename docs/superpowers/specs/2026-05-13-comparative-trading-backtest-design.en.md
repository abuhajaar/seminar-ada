# Comparative Crypto Trading Backtest Framework — Design Spec

**Date:** 2026-05-13
**Project:** seminar-ada
**Seminar title:** *Comparative Analysis of Heuristic vs. Cognitive Multi-Agent Systems in Crypto Trading*

---

## 1. Purpose

Design a robust, modular, asynchronous Python backtesting framework that produces a **fair, reproducible head-to-head comparison** between:

- **Traditional Bot** — heuristic indicator-based strategy (RSI, MACD, ADX, EMA, SuperTrend).
- **LLM Multi-Agent Bot** — LangGraph orchestration of 4 specialized agents (Technical, Visual, QABBA, Decision) routed through OpenRouter, combined via a fixed weighted-consensus rule (QABBA 40% / Visual 35% / Technical 25%).

The framework is sized for a university seminar deliverable: defensible methodology, reproducible artifacts, real (not synthesized) data, and a Rich-based TUI that visualizes both bots running in parallel.

---

## 2. Locked decisions (from brainstorming Q1–Q5)

| # | Decision | Choice |
|---|---|---|
| Q1 | Bar timeframe | Configurable (default `1h`); both bots run on the same timeframe → fair comparison. |
| Q2 | LLM reproducibility | Mandatory on-disk JSON cache keyed by `(model, agent, prompt_hash, image_hash, bar_ts)`; `temperature=0`. |
| Q3 | Visual Analyst | Rolling 100-bar PNG window (configurable); default vision model `anthropic/claude-3.5-sonnet`. |
| Q4 | QABBA data | Real CVD computed from Binance `aggTrades`. **No OBI** in backtest. Window kept short (2–4 weeks, default ~3 weeks) to bound download size and LLM cost. |
| Q5 | Execution & rigor | Next-bar open fills, Binance taker fee 0.04% per side + configurable slippage, fixed-fractional 2%-risk sizing off SuperTrend stop, walk-forward over **BTC/USDT, ETH/USDT, SOL/USDT** with mean ± std reporting. |

---

## 3. Architecture overview

```
                  ┌─────────────────────────────────────────┐
                  │              main.py                    │
                  │   (CLI, config load, asyncio runner)    │
                  └────────────────────┬────────────────────┘
                                       │
                       ┌───────────────┴────────────────┐
                       │                                │
                ┌──────▼────────┐                ┌──────▼──────┐
                │ BacktestEngine│◄──── feeds ────│ DataLoader  │
                │ (core/engine) │                │(CSV+parquet)│
                └──────┬────────┘                └─────────────┘
                       │   bar-by-bar (await)
        ┌──────────────┼──────────────┐
        │              │              │
   ┌────▼─────┐   ┌────▼─────┐   ┌────▼─────┐
   │Traditional│  │ LLM Agent │   │   TUI    │
   │ Strategy  │  │  Strategy │   │  (Rich)  │
   └──────────┘   └────┬──────┘   └──────────┘
                       │ LangGraph: Tech ┐
                       │              Visual ┼─► Decision
                       │              QABBA  ┘
                       ▼
               ┌────────────────┐
               │ LLMClient      │
               │ + JSON cache   │
               │ → OpenRouter   │
               └────────────────┘
```

**Key architectural properties:**

- **Single asyncio event loop** drives engine + TUI; LLM calls are `await`ed → TUI never freezes.
- **Strategy interface** is a thin async protocol (`async on_bar(bar, context) -> Signal`). Both bots implement it identically → engine is strategy-agnostic.
- **Portfolio + execution layer is shared infrastructure** (`core/portfolio.py`, `core/broker.py`). Both bots use the same fee/slippage/sizing logic → fair comparison.
- **LLM provider is pluggable**: `LLMClient` protocol with `OpenRouterClient`, `MockClient`, and a `CachedClient` decorator.
- **Reproducibility is a first-class concern**: deterministic indicators, frozen LLM cache, all run artifacts persisted under `results/runs/<timestamp>/`.

---

## 4. Folder structure

```
seminar-ada/
├── main.py                          # CLI entrypoint, asyncio runner
├── config.yaml                      # All tunables
├── pyproject.toml                   # Deps + tool config (ruff, pytest)
├── .env.example                     # OPENROUTER_API_KEY placeholder
├── README.md
│
├── core/
│   ├── engine.py                    # Async BacktestEngine (bar-by-bar loop)
│   ├── portfolio.py                 # Equity, positions, equity curve
│   ├── broker.py                    # Order fill simulation (next-bar open + slippage + fees)
│   ├── metrics.py                   # Total Return, MDD, Win Rate, Profit Factor, Sharpe
│   ├── ui.py                        # Rich TUI (Layout: header/left/right/footer)
│   └── types.py                     # Bar, Signal, Order, Trade, AgentReport dataclasses
│
├── data/
│   ├── loader.py                    # Load OHLCV CSV + CVD parquet, align timestamps
│   ├── downloader.py                # CCXT OHLCV + Binance aggTrades downloader
│   ├── cvd.py                       # aggTrades → per-bar CVD aggregator
│   └── cache/                       # Downloaded data (gitignored)
│
├── indicators/
│   └── ta.py                        # RSI, MACD, ADX, EMA, SuperTrend (vectorized)
│
├── strategies/
│   ├── base.py                      # Strategy protocol
│   ├── traditional.py               # Heuristic bot
│   └── llm_agents/
│       ├── strategy.py              # LLMAgentStrategy (implements base.Strategy)
│       ├── graph.py                 # LangGraph definition (4 nodes + edges)
│       ├── state.py                 # GraphState TypedDict
│       ├── prompts.py               # System prompts for all 4 agents
│       ├── chart.py                 # mplfinance PNG renderer (100-bar window)
│       └── nodes/
│           ├── technical.py         # Agent 1
│           ├── visual.py            # Agent 2 (vision)
│           ├── qabba.py             # Agent 3 (CVD + taker buy ratio)
│           └── decision.py          # Agent 4 (weighted consensus 40/35/25)
│
├── llm/
│   ├── client.py                    # LLMClient protocol + OpenRouterClient + MockClient
│   ├── cache.py                     # CachedClient decorator (JSON on disk)
│   └── budget.py                    # Token + USD usage tracker
│
├── cache/llm/                       # Per-call JSON cache (commit for seminar reproducibility)
│
├── results/
│   ├── runs/                        # Per-run artifacts (trades.csv, equity.csv, summary.json)
│   └── plots/                       # Equity curves, drawdown, comparison charts
│
└── tests/                           # See §10
```

---

## 5. Core data model (`core/types.py`)

```python
@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float; high: float; low: float; close: float
    volume: float
    taker_buy_volume: float            # Binance kline field, kept for reference
    cvd: float                         # cumulative, from aggTrades
    cvd_delta: float                   # this bar's contribution

class Action(Enum): BUY = "BUY"; SELL = "SELL"; HOLD = "HOLD"

@dataclass
class Signal:
    action: Action
    confidence: float                  # 0–1, used for logging only (sizing is fixed)
    reasoning: str                     # short string surfaced in TUI
    stop_loss: float | None            # SuperTrend stop; None for HOLD

@dataclass
class AgentReport:                     # Output of each LLM analyst node
    action: Action
    confidence: float                  # 0–1
    rationale: str
```

---

## 6. Backtest engine (`core/engine.py`)

```python
async def run():
    prev_bar = None
    for bar in data_iter:                       # all bars in window
        ui.update_header(bar)

        # Both strategies see identical bars; awaited concurrently.
        sig_trad, sig_llm = await asyncio.gather(
            traditional.on_bar(bar, ctx_trad),
            llm_agent.on_bar(bar, ctx_llm),
        )

        # Fills happen on NEXT bar's open (no look-ahead).
        broker_trad.queue(sig_trad, bar)
        broker_llm.queue(sig_llm, bar)
        if prev_bar is not None:
            broker_trad.fill_pending(bar)       # uses bar.open
            broker_llm.fill_pending(bar)

        ui.update_panels(portfolio_trad, portfolio_llm, sig_llm.reasoning)
        prev_bar = bar

    metrics_trad = compute_metrics(portfolio_trad)
    metrics_llm  = compute_metrics(portfolio_llm)
    persist_results(...)
```

**Why `asyncio.gather`:** Traditional bot returns in <1 ms (CPU-bound). LLM bot may take 5–30 s per bar (4 agents, network). Gathering means total wall-clock is dominated by the LLM bot; the traditional bot is effectively free, and the TUI keeps repainting because the event loop yields during LLM HTTP awaits.

**No look-ahead invariant:** Indicators at bar `t` are computed from bars `[0..t]` only. Signals at bar `t` are queued and filled at `bar[t+1].open`. Tests (§10) assert this.

---

## 7. LLM Agent subsystem (`strategies/llm_agents/`)

### 7.1 LangGraph topology

```
            ┌─────────────┐
            │   START     │
            └──────┬──────┘
                   │ (fan out in parallel)
       ┌───────────┼───────────┐
       ▼           ▼           ▼
  ┌────────┐  ┌────────┐  ┌────────┐
  │Technical│  │ Visual │  │ QABBA  │
  │ Agent  │  │ Agent  │  │ Agent  │
  └───┬────┘  └───┬────┘  └───┬────┘
      └───────────┼───────────┘
                  ▼
            ┌──────────┐
            │ Decision │  ← weighted consensus
            │  Agent   │
            └────┬─────┘
                 ▼
              END → Signal
```

The three analyst nodes execute concurrently via LangGraph fan-out edges (each is an `await client.chat(...)`). Decision waits for all three. Per-bar LLM cost ≈ `max(t_tech, t_visual, t_qabba) + t_decision` rather than the sum.

### 7.2 Weighted Consensus (Agent 4)

The Decision Agent receives the three `AgentReport`s plus a system prompt that hard-codes the policy. The same calculation is **also performed deterministically in Python** as a guardrail; if the LLM disagrees with the math, we log the disagreement and use the math. This is documented behavior (the LLM's role is rationale generation, not arithmetic).

```
buy_score  = 0.40 * I[QABBA=BUY]   * QABBA.conf
           + 0.35 * I[Visual=BUY]  * Visual.conf
           + 0.25 * I[Tech=BUY]    * Tech.conf

sell_score = 0.40 * I[QABBA=SELL]  * QABBA.conf
           + 0.35 * I[Visual=SELL] * Visual.conf
           + 0.25 * I[Tech=SELL]   * Tech.conf

if buy_score  > 0.50 and buy_score  > sell_score: BUY
if sell_score > 0.50 and sell_score > buy_score:  SELL
else:                                              HOLD
```

(`I[...]` is the indicator function: 1 if true, 0 otherwise. `*.conf` is the agent's self-reported confidence in `[0, 1]`.)

### 7.3 Agent inputs and outputs

| Agent | Input | Output (JSON) |
|---|---|---|
| Technical | Indicator dict at bar `t` (RSI, MACD hist, ADX, EMA20, EMA50, SuperTrend) | `{action, confidence, rationale}` |
| Visual | 100-bar PNG (base64) rendered via mplfinance | `{action, confidence, rationale, patterns_detected, key_levels}` |
| QABBA | 50-bar windows of `cvd`, `cvd_delta`, `taker_buy_ratio`, recent large trades | `{action, confidence, rationale, flow_regime}` |
| Decision | The three reports above + the consensus formula | `{action, confidence, rationale}` |

All prompts enforce JSON mode + `temperature=0`. Pydantic validates responses; one repair retry on malformed JSON; on second failure → emit `HOLD` and log.

---

## 8. LLM client + cache (`llm/`)

```python
class LLMClient(Protocol):
    async def chat(self, messages, *, model, response_format=None, image=None) -> Response: ...

class CachedClient:
    """Decorator: hits cache before calling underlying client."""
    def __init__(self, inner: LLMClient, cache_dir: Path): ...

    async def chat(self, messages, *, model, **kw):
        key = sha256(json.dumps({
            "model": model,
            "messages": messages,
            "image_hash": sha256(kw.get("image") or b"").hexdigest(),
            "response_format": kw.get("response_format"),
        }, sort_keys=True))
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return Response(**json.loads(path.read_text()))
        resp = await self.inner.chat(messages, model=model, **kw)
        path.write_text(json.dumps(asdict(resp)))
        return resp
```

- `--mock` CLI flag swaps `OpenRouterClient` for `MockClient` returning canned reports — engine, TUI, and tests run with zero API calls.
- Budget guard wraps the client to track `prompt_tokens`, `completion_tokens`, and USD from OpenRouter response metadata; aborts the run if `llm.max_usd` exceeded.

---

## 9. TUI layout (`core/ui.py`)

```
┌─────────────────────────────────────────────────────────────────────┐
│ BTC/USDT  1h  |  Bar 412/720  |  2025-04-12 14:00 UTC  |  $63,142   │  Header
├──────────────────────────────────┬──────────────────────────────────┤
│ TRADITIONAL BOT                  │ MULTI-AGENT LLM BOT              │
│ Balance:    $10,420              │ Balance:    $10,310              │
│ Equity:     $10,512              │ Equity:     $10,290              │
│ Trades:     14   Win%: 57%       │ Trades:      6   Win%: 67%       │
│ MDD:        -4.2%                │ MDD:        -2.1%                │
│ ▁▂▂▃▃▄▅▆▇█ (sparkline)           │ ▁▂▃▃▃▄▄▅▆▆ (sparkline)           │
│                                  │                                  │
│ Last signal: HOLD                │ Reasoning Log:                   │
│   EMA20<EMA50, ADX=22            │  T:HOLD(0.4) V:BUY(0.6)          │
│                                  │  Q:BUY(0.8) → BUY (score 0.62)   │
│                                  │  "CVD trending up, bull flag…"   │
├──────────────────────────────────┴──────────────────────────────────┤
│ [12:01] OpenRouter OK  cache hit 87%  spend $0.42/$5.00  RPS 2.1   │  Footer
└─────────────────────────────────────────────────────────────────────┘
```

Implementation: Rich `Live` + `Layout` regions, fed from a shared `RunState` object that strategies + engine write to. No locks — single-threaded asyncio. Refresh ticker at 4 Hz via `asyncio.create_task`.

---

## 10. Configuration (`config.yaml`)

```yaml
run:
  assets: [BTC/USDT, ETH/USDT, SOL/USDT]   # walk-forward across these
  timeframe: 1h
  start: 2025-04-01
  end:   2025-04-21                         # ~3 weeks (Q4 decision)
  initial_balance: 10000

execution:
  fill: next_bar_open
  taker_fee_bps: 4                          # 0.04% per side
  slippage_bps: 2                           # 0.02% flat
  risk_pct: 0.02                            # 2% per trade, sized off SuperTrend stop

indicators:
  rsi: 14
  macd: [12, 26, 9]
  adx: 14
  ema_fast: 20
  ema_slow: 50
  supertrend: [10, 3]

llm:
  cache_dir: cache/llm
  max_usd: 10.00
  agents:
    technical: { model: anthropic/claude-3.5-sonnet, temperature: 0 }
    visual:    { model: anthropic/claude-3.5-sonnet, temperature: 0, chart_window: 100 }
    qabba:     { model: anthropic/claude-3.5-sonnet, temperature: 0, lookback: 50 }
    decision:  { model: anthropic/claude-3.5-sonnet, temperature: 0 }
  consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
  consensus_threshold: 0.50

data:
  source: binance
  qabba_mode: aggtrades                     # only mode supported per Q4
```

`OPENROUTER_API_KEY` lives in `.env`, loaded via `python-dotenv`. `.env.example` ships with placeholder.

---

## 11. Test strategy

| Layer | Test | Why |
|---|---|---|
| Indicators | RSI/MACD/SuperTrend on a fixture vs `ta-lib` reference values | Catch off-by-one in rolling windows |
| Broker | Fee + slippage math on synthetic orders; next-bar fill semantics | Fairness of comparison hinges on this |
| Metrics | MDD on hand-crafted equity curve; Profit Factor with zero-loss edge case | Edge cases bite |
| LLM cache | Identical inputs → same key; image hash stability | Reproducibility guarantee |
| Engine end-to-end | Run on 50 fixture bars with `MockClient`; assert deterministic equity | Smoke test for the whole loop |
| Traditional strategy | Canned bars where conditions are/aren't met | Document the heuristic |

Target: ~70% line coverage on `core/`, `indicators/`, `llm/cache.py`. LLM nodes themselves are integration-tested via the Mock client.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| OpenRouter rate-limits / outages mid-run | `tenacity` retry with exponential backoff; cache means re-runs are free |
| Vision tokens blow up budget | Budget guard aborts; 100-bar PNGs at moderate DPI ≈ ~50 KB |
| aggTrades download fails / partial | `downloader.py` is idempotent, resumable, validates row counts vs Binance reported volume |
| LLM returns malformed JSON | Pydantic validation + 1 repair retry; second failure → HOLD + log |
| Engine + TUI interleaving glitches | Single asyncio loop, no threads; TUI redraw on a 4 Hz `asyncio.create_task` ticker |
| Comparison unfair due to rare LLM trades | Walk-forward over 3 assets gives N≈30–60 trades per bot total → enough for descriptive stats |
| Look-ahead bias from indicators | All indicators computed using only data up to bar `t`; assertions in tests |

---

## 13. Implementation order

1. Scaffold folders + `pyproject.toml` + `.env.example` + `config.yaml`.
2. `core/types.py`, `data/loader.py`, `data/downloader.py`, `data/cvd.py` + tests.
3. `indicators/ta.py` + tests against TA-Lib reference.
4. `core/portfolio.py`, `core/broker.py`, `core/metrics.py` + tests.
5. `strategies/base.py`, `strategies/traditional.py` + tests.
6. `llm/client.py`, `llm/cache.py`, `llm/budget.py` + `MockClient` + tests.
7. `strategies/llm_agents/` (chart, prompts, 4 nodes, graph, strategy) — using `MockClient` first.
8. `core/engine.py` end-to-end with mock LLM — verify TUI doesn't freeze.
9. `core/ui.py` real Rich layout.
10. `main.py` CLI + walk-forward runner.
11. Live OpenRouter integration test on 1 day of BTC.
12. Full 3-week × 3-asset seminar run; export `results/runs/<timestamp>/`.

---

## 14. Out of scope (YAGNI)

- Live trading mode (backtest only — separate project).
- Web dashboard (Rich TUI is the UI).
- Multi-timeframe analysis inside one run (timeframe is a config knob).
- Hyperparameter optimization / strategy tuning (not the seminar's question).
- Database — flat files (CSV/parquet/JSON) are sufficient.
- OBI synthesis (Q4 decision: real or nothing).
- LLM-decided position sizing (Q5 decision: identical sizing for fair comparison).

---

## 15. Open notes for the paper

- The 40% weight on QABBA must be justified in the methodology section, since QABBA in this build sees CVD + taker-buy flow (not full L2 OBI). Recommend phrasing as "trade-flow microstructure weight" rather than "order-book weight".
- The deterministic Python cross-check on the consensus formula should be disclosed: the LLM Decision Agent's role is rationale, not arithmetic.
- Reproducibility: commit the `cache/llm/` directory alongside the seminar run results so reviewers can re-run and get bit-identical metrics.
