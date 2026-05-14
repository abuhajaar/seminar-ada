# seminar-ada

Comparative analysis of heuristic vs cognitive multi-agent crypto trading systems.

## Status

**Sub-plan A complete:** data layer, indicators, config, types.
**Sub-plan B complete:** execution layer (portfolio, broker, metrics) + Traditional bot + sync engine harness.
**Sub-plan C complete:** LLM agent subsystem — 4-node LangGraph (Technical / Visual / QABBA / Decision) with deterministic weighted-consensus guardrail (spec §7.2), bar-keyed JSON cache, per-run USD budget cap, mplfinance chart renderer, `MockClient` + `OpenRouterClient` implementations, and `LLMAgentStrategy` conforming to the existing `Strategy` protocol.

- Data: download Binance OHLCV (ccxt) + aggTrades (REST), aggregate CVD per bar.
- Indicators: RSI, MACD, ADX, EMA, SuperTrend (vectorized, validated against pandas-ta).
- Execution: shared portfolio + broker with next-bar fills, taker fees, slippage, intra-bar stops.
- Metrics: Total Return, MDD, Win Rate, Profit Factor, Sharpe.
- Traditional bot: indicator-confluence rule with SuperTrend stops + 2%-risk sizing.
- LLM bot: LangGraph fans out 3 analyst nodes (Technical reads indicators, Visual reads a mplfinance PNG, QABBA reads CVD) in parallel; deterministic Decision node applies `0.40·QABBA + 0.35·Visual + 0.25·Technical` weighted consensus with a strict `>0.50` threshold (HOLD otherwise). Math always wins — LLM disagreement is logged but never overrides.
- Cache: every analyst call is keyed on `(model, agent, prompt_hash, image_hash, bar_ts)`. A pre-warmed cache makes seminar replays free, deterministic, and offline.
- Budget guard: per-run USD cap with pre-call estimate; refuses next call once exhausted (`BudgetExceededError`).
- Engine: synchronous single-strategy harness (async dual-strategy + TUI in sub-plan D).

Test suite: **179 passing**, 1 skipped (live network smoke), ruff clean across all modules.

**Next:** sub-plan D — async engine + Rich TUI + walk-forward over multiple assets.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -v
```

To run the optional live network smoke test:

```powershell
$env:RUN_LIVE_TESTS = "1"
pytest tests/test_live_smoke.py -v
$env:RUN_LIVE_TESTS = $null
```

## LLM bot — running modes

### Mock mode (no API key, no cost) — recommended for development and CI

```powershell
# config.yaml: set llm.mock: true
pytest -v
```

`MockClient` is a deterministic stand-in keyed off prompt features. It produces
identical outputs across runs and bypasses the budget guard. All 179 tests
currently use it.

### OpenRouter mode (real LLM calls)

```powershell
$env:OPENROUTER_API_KEY = "sk-or-..."
# config.yaml: set llm.mock: false, choose llm.model, set llm.max_usd cap
```

The strategy will wrap `OpenRouterClient` in `CachedClient`, so each unique
`(model, agent, prompt_hash, image_hash, bar_ts)` tuple is fetched at most
once per run — repeated backtests over the same bars are free after the first
pass. Cache files are committed to `cache/llm/` so the seminar machine can
replay without any API key.

### Budget cap (spec §9)

`config.yaml` → `llm.max_usd`. The `BudgetGuard` runs a pre-call cost estimate;
the next call is refused (raises `BudgetExceededError`) when the running total
would exceed the cap. `MockClient` bypasses the guard entirely.

## LLM bot — mode operasional (Bahasa Indonesia)

### Mode mock (tanpa API key, gratis) — direkomendasikan untuk pengembangan dan CI

`MockClient` adalah pengganti LLM yang deterministik berbasis fitur prompt. Output-nya
sama persis pada setiap run dan tidak mengonsumsi budget guard. Seluruh 179 tes saat
ini menggunakan mode ini.

### Mode OpenRouter (panggilan LLM nyata)

Strategi akan membungkus `OpenRouterClient` di dalam `CachedClient`, sehingga
setiap tuple unik `(model, agent, prompt_hash, image_hash, bar_ts)` hanya
diambil sekali per run — pengulangan backtest pada bar yang sama gratis
setelah pass pertama. File cache di-commit ke `cache/llm/` agar mesin seminar
bisa melakukan replay tanpa API key apa pun.

### Batas budget (spec §9)

`config.yaml` → `llm.max_usd`. `BudgetGuard` melakukan estimasi biaya sebelum
setiap panggilan; panggilan berikutnya ditolak (`BudgetExceededError`) jika
total berjalan akan melebihi batas. `MockClient` melewati guard sepenuhnya.

## Spec

- English: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.en.md`
- Indonesian: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.id.md`

## Plans

- Sub-plan A: `docs/superpowers/plans/2026-05-13-sub-plan-A-data-and-indicators.md` (complete)
- Sub-plan B: `docs/superpowers/plans/2026-05-13-sub-plan-B-execution-and-traditional-bot.md` (complete)
- Sub-plan C: `docs/superpowers/plans/2026-05-13-sub-plan-C-llm-agents-and-cache.md` (complete)
- Sub-plan D: TBD (async engine + Rich TUI + walk-forward).
