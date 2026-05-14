# seminar-ada

Comparative analysis of heuristic vs cognitive multi-agent crypto trading systems.

## Status

**Sub-plans A–D complete.** End-to-end pipeline runs: load Binance bars → dual-strategy async engine → walk-forward over N assets → Rich live TUI → CSV/JSON artifacts per run.

- **Sub-plan A:** data layer, indicators, config, types.
- **Sub-plan B:** execution layer (portfolio, broker, metrics) + Traditional bot + sync engine harness.
- **Sub-plan C:** LLM agent subsystem — 4-node LangGraph (Technical / Visual / QABBA / Decision) with deterministic weighted-consensus guardrail (spec §7.2), bar-keyed JSON cache, per-run USD budget cap, mplfinance chart renderer, `MockClient` + `OpenRouterClient`, and `LLMAgentStrategy` conforming to the `Strategy` protocol.
- **Sub-plan D:** async dual-strategy engine with bit-identical parity vs `engine_sync`, per-bar `RunState` snapshots, Rich live TUI (4 Hz async ticker), multi-asset walk-forward runner, and Typer CLI (`main.py`) assembling the full stack.

Highlights:

- Data: download Binance OHLCV (ccxt) + aggTrades (REST), aggregate CVD per bar.
- Indicators: RSI, MACD, ADX, EMA, SuperTrend (vectorized, validated against pandas-ta).
- Execution: shared portfolio + broker with next-bar fills, taker fees, slippage, intra-bar stops.
- Metrics: Total Return, MDD, Win Rate, Profit Factor, Sharpe.
- Traditional bot: indicator-confluence rule with SuperTrend stops + 2%-risk sizing.
- LLM bot: LangGraph fans out 3 analyst nodes (Technical / Visual / QABBA) in parallel; deterministic Decision node applies `0.40·QABBA + 0.35·Visual + 0.25·Technical` weighted consensus with a strict `>0.50` threshold (HOLD otherwise). Math always wins — LLM disagreement is logged but never overrides.
- Cache: every analyst call is keyed on `(model, agent, prompt_hash, image_hash, bar_ts)`. A pre-warmed cache makes seminar replays free, deterministic, and offline.
- Engine: async dual-strategy bar loop; bit-identical to the sync reference on the same bars.
- TUI: `core/ui.py` builds a Rich layout (header / trad panel / llm panel / footer with cache + spend), driven by a 4 Hz async ticker reading per-bar `RunState` snapshots.
- Walk-forward: iterates the engine over `cfg.run.assets`, isolating state per asset; persists `trades.csv`, `equity.csv`, and an aggregated `summary.json` under `<out-dir>/runs/<UTC-timestamp>/`.

Test suite: **216 passing**, 1 skipped (live network smoke), ruff clean across all modules.

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
identical outputs across runs and bypasses the budget guard. All LLM-touching
tests in the suite currently use it.

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
sama persis pada setiap run dan tidak mengonsumsi budget guard. Seluruh tes
yang menyentuh LLM saat ini menggunakan mode ini.

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

## Running the backtest

Once `config.yaml` is configured and (optionally) historical bars are present
under `--data-root`, drive the full pipeline through the Typer CLI in
`main.py`:

```powershell
# Default: read config.yaml, run walk-forward over cfg.run.assets, live TUI on.
python main.py run

# Offline / deterministic — use MockClient regardless of config.yaml's llm.mock.
python main.py run --mock --no-tui

# Override assets (repeatable OR comma-separated) and date window.
python main.py run --assets BTC/USDT --assets ETH/USDT --start 2024-01-01 --end 2024-03-31
python main.py run --assets "BTC/USDT,ETH/USDT" --mock

# Redirect artifacts and data cache locations.
python main.py run --out-dir results --data-root data
```

CLI flags (see `main.py:115-140`):

- `--config PATH` — path to `config.yaml` (default `config.yaml`).
- `--mock` — force the deterministic `MockClient` (no API key, no spend). Overrides `llm.mock`.
- `--no-tui` — disable the live Rich ticker; useful for CI, headless runs, and `tee`-style logging.
- `--assets` — repeatable or comma-separated symbols (e.g. `BTC/USDT`). Overrides `cfg.run.assets`.
- `--start YYYY-MM-DD`, `--end YYYY-MM-DD` — ISO date overrides for `cfg.run.start` / `cfg.run.end`.
- `--out-dir PATH` — artifact root (default `results`). Each invocation writes to `<out-dir>/runs/<UTC-timestamp>/` with per-asset subdirs.
- `--data-root PATH` — root of the local Binance bar cache (default project `DEFAULT_ROOT`).

Each run writes `trades.csv`, `equity.csv` per asset and an aggregated
`summary.json` at the run root, then prints a Rich summary table to the
terminal.

## Menjalankan backtest (Bahasa Indonesia)

Setelah `config.yaml` siap dan (opsional) bar historis tersedia di
`--data-root`, jalankan pipeline lengkap lewat CLI Typer di `main.py`:

```powershell
# Default: baca config.yaml, walk-forward atas cfg.run.assets, TUI live aktif.
python main.py run

# Offline / deterministik — pakai MockClient terlepas dari nilai llm.mock di config.
python main.py run --mock --no-tui

# Override aset (boleh diulang ATAU dipisah koma) dan rentang tanggal.
python main.py run --assets BTC/USDT --assets ETH/USDT --start 2024-01-01 --end 2024-03-31
python main.py run --assets "BTC/USDT,ETH/USDT" --mock

# Arahkan ulang lokasi artefak dan cache data.
python main.py run --out-dir results --data-root data
```

Flag CLI (lihat `main.py:115-140`):

- `--config PATH` — path ke `config.yaml` (default `config.yaml`).
- `--mock` — paksa `MockClient` deterministik (tanpa API key, tanpa biaya). Menimpa `llm.mock`.
- `--no-tui` — matikan ticker Rich live; berguna untuk CI, run headless, dan logging gaya `tee`.
- `--assets` — simbol yang bisa diulang atau dipisah koma (mis. `BTC/USDT`). Menimpa `cfg.run.assets`.
- `--start YYYY-MM-DD`, `--end YYYY-MM-DD` — override tanggal ISO untuk `cfg.run.start` / `cfg.run.end`.
- `--out-dir PATH` — root artefak (default `results`). Setiap invokasi menulis ke `<out-dir>/runs/<UTC-timestamp>/` dengan subdir per aset.
- `--data-root PATH` — root cache bar Binance lokal (default `DEFAULT_ROOT` proyek).

Setiap run menulis `trades.csv` dan `equity.csv` per aset serta `summary.json`
agregat di root run, lalu mencetak tabel ringkasan Rich ke terminal.

## Spec

- English: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.en.md`
- Indonesian: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.id.md`

## Plans

- Sub-plan A: `docs/superpowers/plans/2026-05-13-sub-plan-A-data-and-indicators.md` (complete)
- Sub-plan B: `docs/superpowers/plans/2026-05-13-sub-plan-B-execution-and-traditional-bot.md` (complete)
- Sub-plan C: `docs/superpowers/plans/2026-05-13-sub-plan-C-llm-agents-and-cache.md` (complete)
- Sub-plan D: `docs/superpowers/plans/2026-05-13-sub-plan-D-engine-tui-walkforward.md` (complete)
