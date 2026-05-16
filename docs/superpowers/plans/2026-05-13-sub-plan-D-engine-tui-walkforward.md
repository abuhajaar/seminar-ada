# Sub-Plan D: Async Engine, Rich TUI, Walk-Forward Runner + CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble the final deliverable. Wire the completed pieces from sub-plans A/B/C into an asynchronous, dual-strategy backtest engine driven by a single bar stream; render live progress through a Rich TUI; iterate over the three walk-forward assets defined in `config.yaml`; persist `trades.csv`, `equity.csv`, and `summary.json` per run; expose a `main.py` CLI with `--mock`, `--no-tui`, `--assets`, `--start`, `--end`, `--out-dir` flags. After this plan the project is end-to-end runnable with `uv run python main.py --mock` (offline, free, deterministic) or `uv run python main.py` (live OpenRouter).

**Architecture:**
- `core/engine.py` drives a single bar iterator and feeds **two legs** `(Strategy, Broker, Portfolio)` per bar via `asyncio.gather(...)`. Bar-loop order mirrors `engine_sync.run_sync` exactly (stops → fills → signal → mark → record) to preserve parity. The traditional leg returns in microseconds; the LLM leg may await tens of seconds — `asyncio.gather` keeps total wall-clock at `max(t_trad, t_llm) ≈ t_llm`, and event-loop yields during HTTP awaits let the 4 Hz TUI ticker repaint.
- `core/run_state.py` defines a frozen-by-convention `RunState` dataclass — the single source of truth shared between engine (writer) and TUI (reader). No locks: single asyncio loop.
- `core/ui.py` uses Rich `Live` + `Layout` with five regions (header, two body panels, sparklines, footer). It runs as an `asyncio.create_task` ticker at 4 Hz, reading `RunState` snapshots.
- `core/walkforward.py` iterates the engine over each asset in `config.run.assets`, isolating ledger/state per asset, then aggregates summaries.
- `core/persistence.py` writes per-asset `trades.csv` + `equity.csv` (one row per closed trade / per bar) and a `summary.json` (mean ± std across assets, per-bot).
- `main.py` is the CLI: loads `config.yaml`, parses argv, builds the LLM client stack (`MockClient` OR `OpenRouterClient` → `BudgetGuard` → `CachedClient`), constructs both strategies, and dispatches `walkforward.run(...)`.

**Tech Stack:**
- New runtime deps (add to `pyproject.toml`): `rich>=13`, `python-dotenv>=1.0`, `typer>=0.12` (CLI). Already present: everything else.
- All tests use `pytest-asyncio` (already configured `auto` mode). Engine tests use the synthetic-bars fixture pattern from sub-plan B/C.

**Status of prerequisites:**
- Sub-plan A complete: data loader, CVD, indicators (32 tests).
- Sub-plan B complete: `Strategy`/`Context`/`Signal`/`Order`, `Portfolio`, `Broker`, `Metrics`, `engine_sync` (sync parity reference), `TraditionalStrategy` (80 tests, 97% coverage).
- Sub-plan C complete: `LLMClient`/`MockClient`/`OpenRouterClient`, `CachedClient`, `BudgetGuard`, full LangGraph wiring, `LLMAgentStrategy` (179 tests, 96% coverage).
- Repo synced with `origin/master` at `8bb6d0d`. Ruff clean. `cache/llm/` tracked.

---

## Scope checklist (spec sections this plan implements)

- §3: top-level architecture (main.py → engine → strategies + UI + DataLoader).
- §6: `core/engine.py` async dual-strategy bar loop with `asyncio.gather`, next-bar-open fills, no look-ahead.
- §9: `core/ui.py` Rich Live + Layout, 4 Hz refresh, header / two body panels / sparklines / footer.
- §10: `config.yaml` is consumed end-to-end; `.env` loading via `python-dotenv`.
- §11 test rows: "Engine end-to-end" — 50 fixture bars with `MockClient`, deterministic equity.
- §13 implementation order steps 8–12 (engine, ui, main, walk-forward, results export).

Out of scope (intentionally deferred or rejected):
- Live trading mode (§14 YAGNI).
- Web dashboard (§14 YAGNI — Rich TUI only).
- Hyperparameter optimization (§14 YAGNI).
- Live OpenRouter integration test on real BTC bars (§13 step 11 — manual smoke test, not part of pytest CI).
- The full 3-week × 3-asset seminar run (§13 step 12 — performed by the user, not by this plan; we ship the runner, not the artifacts).

---

## File structure produced by this plan

```
core/
├── engine.py            # NEW: async dual-strategy bar loop
├── ui.py                # NEW: Rich Live TUI (4 Hz)
├── run_state.py         # NEW: RunState dataclass — engine↔UI single source of truth
├── walkforward.py       # NEW: iterate engine over config.run.assets
└── persistence.py       # NEW: write trades.csv, equity.csv, summary.json
main.py                  # NEW: Typer CLI; assembles client stack, dispatches walkforward
.env.example             # NEW: OPENROUTER_API_KEY placeholder
tests/
├── test_run_state.py    # NEW: RunState construction, snapshot, equality
├── test_persistence.py  # NEW: round-trip trades/equity/summary; correct schema
├── test_engine.py       # NEW: parity vs engine_sync on synthetic bars; deterministic
├── test_walkforward.py  # NEW: multi-asset isolation; aggregated summary shape
└── test_ui.py           # NEW: layout renders without errors; sparkline tolerance
```

Also modified:
- `pyproject.toml`: add `rich`, `python-dotenv`, `typer`.
- `README.md`: append "Running the backtest" section (EN + ID); document CLI flags.
- `config.yaml`: unchanged (already covers everything sub-plan D needs).

**Not created (already exist from prior sub-plans):**
- `core/types.py`, `core/config.py`, `core/portfolio.py`, `core/broker.py`, `core/metrics.py`, `core/engine_sync.py`.
- `data/loader.py`, `data/downloader.py`, `data/cvd.py`, `data/paths.py`.
- `strategies/base.py`, `strategies/traditional.py`, `strategies/llm_agents/*`.
- `llm/client.py`, `llm/cache.py`, `llm/budget.py`.
- `indicators/ta.py`.

---

## Implementation order

Each task is a single TDD cycle: write failing test → minimum impl to pass → ruff + pytest clean → commit. Two-stage review: self-check then user gate only on BLOCKED. Tasks are ordered so each builds only on its predecessors.

### Task 1 — `core/run_state.py`: shared engine↔UI state container

- [ ] Write `tests/test_run_state.py`: construct `RunState(symbol, timeframe, total_bars)`; assert `current_bar=0`, `bar_ts=None`, empty `trad_curve`/`llm_curve`/`llm_reasoning`. Assert `RunState.snapshot()` returns a dict with all keys used by `core/ui.py` (defined here so UI tests can lock to it).
- [ ] Implement `core/run_state.py` with a single `@dataclass` `RunState` exposing: `symbol`, `timeframe`, `total_bars`, `current_bar`, `bar_ts`, `bar_close`, `trad_equity`, `llm_equity`, `trad_curve: list[float]`, `llm_curve: list[float]`, `trad_trades`, `llm_trades`, `trad_win_pct`, `llm_win_pct`, `trad_mdd`, `llm_mdd`, `last_trad_signal`, `last_trad_rationale`, `llm_reasoning: list[str]` (bounded `deque(maxlen=10)`), `cache_hits`, `cache_misses`, `spend_usd`, `budget_usd`. Add `snapshot()` returning a shallow dict copy for thread-safe UI reads.
- [ ] `uv run pytest tests/test_run_state.py -q` green. `uv run ruff check core/run_state.py tests/test_run_state.py` clean.
- [ ] Commit: `feat(run_state): add RunState dataclass for engine↔UI snapshots`.

### Task 2 — `core/persistence.py`: artifact writers

- [ ] Write `tests/test_persistence.py`: feed a `Portfolio` with 2 closed trades + 5 equity points; call `write_trades(path, portfolio)`, `write_equity(path, portfolio)`, `write_summary(path, {"BTC/USDT": metrics, ...})`. Assert CSV row counts, header names, and that re-reading via `pandas.read_csv` round-trips floats to 1e-8.
- [ ] Implement `core/persistence.py`:
  - `write_trades(path: Path, portfolio: Portfolio) -> None` — columns: `entry_ts, exit_ts, side, entry_price, exit_price, qty, pnl_usd, pnl_pct, bars_held`.
  - `write_equity(path: Path, portfolio: Portfolio) -> None` — columns: `ts, equity, drawdown`.
  - `write_summary(path: Path, metrics_by_asset: dict[str, dict[str, MetricsDict]]) -> None` — JSON with `{asset: {trad: {...}, llm: {...}}}` plus aggregate `{trad: {mean: ..., std: ...}, llm: {...}}` across assets.
  - `make_run_dir(out_root: Path) -> Path` — creates `out_root / "runs" / <UTC-timestamp>` and returns it.
- [ ] Tests green. Ruff clean.
- [ ] Commit: `feat(persistence): write trades/equity CSVs and summary JSON per run`.

### Task 3 — `core/engine.py` skeleton: signature + sync parity stub

- [ ] Write `tests/test_engine.py::test_engine_parity_with_engine_sync` — feed 50 synthetic bars to both `engine_sync.run_sync(bars, TraditionalStrategy(), ...)` and `await engine.run_async(bars, TraditionalStrategy(), TraditionalStrategy(), ...)` (LLM leg is a second traditional strategy here — pure determinism check). Assert final equity, trade count, and trade pnls match to 1e-8 across both legs.
- [ ] Implement `core/engine.py::run_async(bars, trad_strategy, llm_strategy, symbol, run_state, *, initial_balance, taker_fee_bps, slippage_bps, risk_pct) -> tuple[Portfolio, Portfolio, MetricsDict, MetricsDict]`. Bar-loop order MUST mirror `engine_sync.run_sync`: for each bar — (1) `broker.check_stops(bar)`, (2) if `prev_bar is not None: broker.fill_pending(bar)`, (3) `sig_trad, sig_llm = await asyncio.gather(trad.generate_signal(...), llm.generate_signal(...))`, (4) size via `_size(equity, risk_pct, entry, stop)` (reuse helper from `engine_sync.py` — extract to a shared `core/_sizing.py` if needed, or import from `engine_sync`), (5) `broker.queue(...)`, (6) `portfolio.mark(bar.timestamp, bar.close)`, (7) update `run_state`. Compute final metrics via `compute_metrics(portfolio)` for both legs.
- [ ] `_sizing` extraction: if I had to import a `_`-prefixed helper from `engine_sync`, rename `_size` → `size_position` in `engine_sync.py` (keep alias for the old name to avoid breaking other code) and re-use from both engines. Verify all existing tests still pass.
- [ ] Test green. Ruff clean.
- [ ] Commit: `feat(engine): add async dual-strategy bar loop with engine_sync parity`.

### Task 4 — `core/engine.py`: `run_state` integration

- [ ] Extend `tests/test_engine.py` with `test_engine_updates_run_state`: pass a fresh `RunState`, drive 50 bars, assert `current_bar == 50`, `trad_curve` has 50 entries, `llm_curve` has 50 entries, final `trad_equity == portfolio_trad.equity(last_close)`, and `last_trad_signal` matches the final emitted signal (`"BUY"|"SELL"|"HOLD"`).
- [ ] Implement: inside the bar loop, after `portfolio.mark(...)`, write to `run_state`:
  - `current_bar`, `bar_ts`, `bar_close`.
  - `trad_equity`, `llm_equity`, append to `trad_curve`/`llm_curve` (cap at last 500 points to bound memory for very long runs).
  - `trad_trades = len(portfolio_trad.closed_trades)`, `llm_trades = len(portfolio_llm.closed_trades)`.
  - `trad_win_pct`, `llm_win_pct` from running metric (closed trades only; HOLD until ≥1 trade).
  - `trad_mdd`, `llm_mdd` from `compute_metrics` partial (only call every 10 bars to avoid recomputing; or implement rolling MDD).
  - `last_trad_signal`, `last_trad_rationale` (from `Signal.reasoning`), `llm_reasoning.append(sig_llm.reasoning)`.
  - `cache_hits`, `cache_misses`, `spend_usd` if `llm_strategy` exposes them (sub-plan C's `LLMAgentStrategy` should — verify; if not, accept that these stay at 0 here and the budget guard counters are surfaced in main.py instead).
- [ ] Test green. Ruff clean.
- [ ] Commit: `feat(engine): write per-bar RunState snapshots for live TUI`.

### Task 5 — `core/walkforward.py`: multi-asset runner

- [ ] Write `tests/test_walkforward.py::test_walkforward_isolates_assets` — provide a fake `bars_loader(symbol)` returning different deterministic synthetic bar sets per symbol; run `walkforward.run(["A/USDT", "B/USDT"], bars_loader, build_strategies, cfg, run_state_factory)`; assert it returns `{"A/USDT": {"trad": metrics, "llm": metrics}, "B/USDT": {...}}` and that the portfolios are independent (e.g., final equities differ).
- [ ] Implement `core/walkforward.run(assets, bars_loader, build_strategies, cfg, *, run_state_factory=None, on_progress=None) -> dict[str, dict[str, MetricsDict]]`. For each asset: create fresh `RunState`, fresh `TraditionalStrategy()` + fresh `LLMAgentStrategy()` (via `build_strategies(symbol)` to keep client stack identical but state reset), call `engine.run_async(...)`, persist artifacts via `core/persistence.py` if `cfg.run.out_dir` set. Catch `BudgetExceededError` per-asset: log, mark that asset's LLM metrics as `{"status": "budget_exceeded", "spend_usd": ...}`, continue with remaining assets.
- [ ] Test green. Ruff clean.
- [ ] Commit: `feat(walkforward): iterate engine over configured assets with isolation`.

### Task 6 — `core/ui.py`: layout components (no Live yet)

- [ ] Write `tests/test_ui.py::test_layout_renders` — build a `Layout` via `ui.build_layout(run_state)` with a populated `RunState` (10 bars, 2 trades, some reasoning lines); assert each region (header / trad / llm / footer) returns a non-empty `rich.Console.render_str` output; assert sparkline length matches `min(50, len(curve))`. No Live, no async — pure rendering test.
- [ ] Implement `core/ui.py::build_layout(run_state) -> rich.layout.Layout` and helper `render_panels(run_state) -> dict[str, RenderableType]`:
  - `_header(rs)` → Rich `Panel` showing `f"{rs.symbol}  {rs.timeframe}  |  Bar {rs.current_bar}/{rs.total_bars}  |  {rs.bar_ts}  |  ${rs.bar_close:,.2f}"`.
  - `_bot_panel(name, equity, trades, win_pct, mdd, curve, last_signal, rationale)` → Rich `Panel` with table-like text.
  - `_sparkline(values, width=50)` → unicode bar chars `▁▂▃▄▅▆▇█` mapped from min..max.
  - `_footer(rs)` → `f"cache hit {hit_pct}%  spend ${rs.spend_usd:.2f}/${rs.budget_usd:.2f}"`.
- [ ] Test green. Ruff clean.
- [ ] Commit: `feat(ui): add Rich layout components for dual-bot panel`.

### Task 7 — `core/ui.py`: live ticker

- [ ] Write `tests/test_ui.py::test_live_ticker_redraws` — use `rich.console.Console(record=True)` and `rich.live.Live(...)` with `auto_refresh=False`; drive `ui.start_live(run_state, console, interval=0.01)` as an `asyncio.create_task`, mutate `run_state.current_bar` in a loop, call `ui.stop_live()`, then assert `console.export_text()` mentions the final bar number. Tolerate timing — just confirm the ticker is wired and reads `RunState` repeatedly.
- [ ] Implement `core/ui.py::start_live(run_state, console=None, interval=0.25) -> asyncio.Task` and `stop_live()`. Internally, `asyncio.create_task` of an async function that loops `while not stop_event.is_set(): live.update(build_layout(run_state.snapshot())); await asyncio.sleep(interval)`. Manage a module-level `_stop_event` and `_live_task` so `stop_live()` cancels cleanly.
- [ ] Test green. Ruff clean.
- [ ] Commit: `feat(ui): add 4Hz async live ticker reading RunState snapshots`.

### Task 8 — `main.py`: CLI assembly

- [ ] Write `tests/test_main.py::test_cli_mock_smoke` — invoke `main.app` via Typer's `CliRunner` with `--mock --no-tui --assets BTC/USDT --start 2025-04-01 --end 2025-04-02 --out-dir tmp/`. Use a tiny prebuilt fixture CSV (commit a small `tests/fixtures/bars_btc_2bars.csv`) and monkeypatch `data.loader.load_bars` to read it. Assert exit code 0 and that `tmp/runs/<ts>/BTC_USDT/summary.json` exists with both `trad` and `llm` keys.
- [ ] Implement `main.py` using `typer`:
  - `main app = typer.Typer()` with one command (default).
  - Flags: `--config Path = Path("config.yaml")`, `--mock bool = False`, `--no-tui bool = False`, `--assets list[str] = None` (overrides `cfg.run.assets`), `--start str = None`, `--end str = None`, `--out-dir Path = Path("results")`.
  - Load `.env` via `dotenv.load_dotenv()` (silent if missing).
  - Load `cfg = AppConfig.from_yaml(config)`.
  - Build client stack: `inner = MockClient() if mock else OpenRouterClient(api_key=os.environ["OPENROUTER_API_KEY"])`; wrap `BudgetGuard(inner, max_usd=cfg.llm.max_usd)`; wrap `CachedClient(..., cache_dir=cfg.llm.cache_dir)`.
  - `build_strategies(symbol) -> (TraditionalStrategy, LLMAgentStrategy)` factory closing over `client` + `cfg`.
  - `bars_loader(symbol) -> Iterator[Bar]` closing over `start`/`end`/`timeframe`/`data_root`.
  - If `--no-tui`: just call `await walkforward.run(...)`. Else: start TUI ticker, run, stop ticker, print final summary table to console.
  - Always print final `summary.json` location.
- [ ] Test green. Ruff clean. `uv run python main.py --mock --no-tui --assets BTC/USDT --start 2025-04-01 --end 2025-04-02` manually executes without traceback (smoke).
- [ ] Commit: `feat(main): add Typer CLI assembling client stack and walk-forward runner`.

### Task 9 — `.env.example` + README sections (EN + ID)

- [ ] No tests — documentation task. Verify by render-only.
- [ ] Create `.env.example`:
  ```
  # OpenRouter API key — sign up at https://openrouter.ai
  # Leave blank and pass --mock to run offline with cached / canned responses.
  OPENROUTER_API_KEY=
  ```
- [ ] Update `README.md`: add a "Running the backtest" section in BOTH English and Indonesian (EN above ID per project convention), documenting:
  - `cp .env.example .env` + add `OPENROUTER_API_KEY`.
  - `uv run python main.py --mock` for offline / free / deterministic seminar replay.
  - `uv run python main.py` for live OpenRouter.
  - All CLI flags with one-line descriptions.
  - Output layout: `results/runs/<UTC-timestamp>/<ASSET>/{trades.csv,equity.csv,summary.json}`.
- [ ] Ruff clean on any `.py` files touched (none expected).
- [ ] Commit: `docs: add .env.example and bilingual run instructions`.

### Task 10 — Final verification

- [ ] `uv run pytest -q` — full suite passes (target: 179 + new ≈ 195 tests, all green).
- [ ] `uv run pytest --cov=core --cov=llm --cov=strategies --cov=indicators --cov=data --cov-report=term` — coverage ≥ 90% overall, ≥ 80% on `core/engine.py` and `core/ui.py` specifically.
- [ ] `uv run ruff check .` — clean on all `.py` files.
- [ ] `uv run python main.py --mock --no-tui --assets BTC/USDT --start 2025-04-01 --end 2025-04-02 --out-dir /tmp/seminar-smoke` — exits 0, produces summary.json.
- [ ] `uv run python main.py --mock` — runs full 3-week × 3-asset mock walk-forward end-to-end with live TUI; observe no freezes, footer ticks, ends with summary table printed.
- [ ] Update `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.id.md` if any EN spec language drifted (translate any changes — should be none in this sub-plan).
- [ ] `git push origin master` — final ship.
- [ ] Commit (if any verification fixups): `chore: post-implementation verification fixes`.

---

## Risks & mitigations specific to this sub-plan

| Risk | Mitigation |
|---|---|
| `asyncio.gather` does not actually yield to the TUI between LLM awaits | The ticker is `asyncio.create_task` not a thread; LLM strategy uses `httpx.AsyncClient` (already async in sub-plan C). Test 7 confirms ticker repaints during awaits. |
| Bar-loop ordering drifts from `engine_sync.run_sync` and breaks parity | Task 3 explicitly tests bit-identical results on the same bars with two `TraditionalStrategy` legs. If parity fails, the engine is wrong — not the test. |
| `RunState` mutation race between engine and UI | Single asyncio loop, no threads, no locks needed. UI reads `run_state.snapshot()` (a shallow dict copy) so any list growth mid-frame is harmless. |
| LLM strategy can't be instantiated multiple times (one per asset) in walkforward | `build_strategies(symbol)` factory pattern; client stack is shared (cache is keyed correctly per spec Q2), strategy state is fresh. Verified in test 5. |
| Typer + asyncio interop awkward | Use `asyncio.run(...)` inside the sync Typer command body; or `typer-async` adapter. Standard pattern, well-documented. |
| Budget exhausted mid-walk-forward kills the run | Task 5 catches `BudgetExceededError` per-asset and continues; summary reports partial results. The mock path bypasses entirely. |

---

## Definition of done

- [ ] All 10 tasks complete with green tests + ruff clean.
- [ ] Final pytest count ≥ 195 tests, ≥ 90% overall coverage.
- [ ] `uv run python main.py --mock` runs to completion with TUI and produces `results/runs/<ts>/<ASSET>/{trades.csv, equity.csv, summary.json}` for all 3 assets.
- [ ] README has bilingual "Running the backtest" sections.
- [ ] Repo pushed to `origin/master`.
- [ ] No new TODOs / deferred debt items added without being recorded in the plan or in a follow-up issue.
