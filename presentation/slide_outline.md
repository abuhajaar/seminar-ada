# Slide Outline — 26 Slides, ~30 Minutes (Data-Pipeline-Heavy)

Language-neutral structure. Both `script_en.md` and `script_id.md` index against these slide numbers.

---

## Section 1 — Context, Problem & Hypothesis (4 min)

### Slide 1 — Title
- Comparative Study: Classical TA vs LLM Multi-Agent Trading on BTC/USDT
- Seminar context: Advanced Data Analysis
- Authors / supervisor / date

### Slide 2 — The Problem
- Crypto markets: 24/7, no human can stay sharp that long
- Traditional bot = fixed rulebook: fast, predictable, cheap
- Limitation: blind to anything not encoded in the rule

### Slide 3 — The Idea: Three Analysts in a Trading Room
- 3 LLM analysts, same model, different jobs and different views:
  - Numbers analyst (indicator readouts)
  - Chart analyst (candle picture, x-ray style)
  - Order-flow analyst (buy vs sell pressure)
- Each writes BUY / SELL / HOLD plus a confidence
- A non-LLM boss applies a fixed weighted formula
- LLM does the looking, math does the deciding

### Slide 4 — Hypothesis & Honest Outcome
- Hypothesis: LLM-multi-agent can match or beat classical TA on the same data
- Measured outcome: LLM lost money, classical won
- Honest framing: the answer is what we measured, not what we hoped
- Today's focus: **the data pipeline** — every transformation from API response to filled trade

---

## Section 2 — Data Source & Raw Inputs (3 min)

### Slide 5 — Data Sources
- Exchange: **Binance Spot**
- Symbol: BTC/USDT; Timeframe: 15m; Window: 2025-04-10 → 2025-04-15 (480 bars)
- Endpoints:
  - `GET https://api.binance.com/api/v3/klines` (OHLCV + taker buy volume)
  - `GET https://api.binance.com/api/v3/aggTrades` (skipped — CVD derived from klines for 60–200× speedup)
- Code: `data/downloader.py:42` (`publicGetKlines` via ccxt)

### Slide 6 — What Binance Gives Us (Raw Kline)
- 12-element JSON array per candle; prices/volumes are JSON strings (cast at `downloader.py:113`)
- We keep 7 fields: `timestamp, open, high, low, close, volume, taker_buy_volume`
- We drop 5: `close_time, quote_vol, n_trades, taker_buy_quote, ignore`

### Slide 7 — Why `taker_buy_volume` Matters (CVD Derivation)
- CVD = Cumulative Volume Delta = cumulative (buy aggressor − sell aggressor)
- Identity: `volume = taker_buy + taker_sell` and `cvd_delta = taker_buy − taker_sell`
- Therefore: `cvd_delta = 2 × taker_buy_volume − volume`
- Avoids downloading millions of aggTrades (60–200× faster)
- Code: `data/cvd.py:50` `cvd_from_klines`

### Slide 8 — Final `Bar` Object Schema
- After preprocessing, the engine consumes a stream of `Bar` dataclasses:
  ```python
  Bar(timestamp, open, high, low, close,
      volume, taker_buy_volume, cvd, cvd_delta)
  ```
- One `Bar` per 15-min interval. 480 bars total for the test window.
- `data/loader.py:19` `load_bars()` — strict timestamp alignment between OHLCV CSV and CVD CSV; misalignment raises `ValueError`.

---

## Section 3 — Preprocessing & Indicator Transformations (5 min)

### Slide 9 — Warmup Discipline
- Both strategies require **60 bars** of warmup before any signal is emitted.
- Why: MACD(12,26,9) hist is first non-NaN at bar 34; SuperTrend(10,3) needs ~10 bars of ATR seasoning; EMA(50) needs 50.
- Constant: `WARMUP = 60` (`strategies/traditional.py:38`, `strategies/llm_agents/strategy.py:39`).

### Slide 10 — Indicator Set
| Indicator | Params | Purpose | Used by |
|---|---|---|---|
| EMA | 12, 26 (LLM) / 20, 50 (Trad) | Trend direction | both |
| RSI | 14 | Overbought/oversold | both |
| MACD | 12 / 26 / 9 | Momentum cross | both |
| ADX | 14 | Trend strength filter | both |
| SuperTrend | length=10, multiplier=3 | Trailing stop + regime sign | both |
| CVD | derived from kline | Order-flow pressure | LLM only |

### Slide 11 — SuperTrend Up Close
- Formula: `hl2 ± multiplier × ATR(10)`, with carry-forward trailing rule
- Two outputs:
  - `st` — the stop-line price level
  - `dir` — `+1` (line **below** price, long-friendly regime) or `−1` (line **above** price, short-friendly)
- Used as **both** the stop-loss level **and** a regime gate
- Code: `indicators/ta.py:124`

### Slide 12 — Transformation Pipeline Diagram
```
Binance REST  ──►  kline JSON (12-col array)
                    │  ccxt publicGetKlines, 1000-row pages
                    ▼
                  OHLCV CSV (7 cols)              ┐
                                                  ├─ data/loader.py
                  CVD CSV (4 cols, derived) ─────┘
                    │  timestamp-aligned join
                    ▼
                  Bar(...) stream (1 per 15m)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  Traditional rules       LLM features + chart PNG
```

---

## Section 4 — Traditional Bot: Data → Signal → Trade (4 min)

### Slide 13 — The Rulebook (Transparent on Purpose)
```
if ADX(14) > 20:
    if EMA20>EMA50 and MACD_hist>0 and RSI<70 and ST_dir==+1:
        BUY  (stop = SuperTrend line)
    elif EMA20<EMA50 and MACD_hist<0 and RSI>30 and ST_dir==−1:
        SELL (stop = SuperTrend line)
    else: HOLD
else: HOLD
```
- 100% deterministic. Same bar → same signal, every time.
- Code: `strategies/traditional.py:47`

### Slide 14 — Signal Object
```python
Signal(action=Action.BUY,
       confidence=0.42,        # = clip((ADX-20)/30, 0, 1)
       reasoning="BUY: EMA20>EMA50, MACD up 12.3, RSI=58.1, ...",
       stop_loss=83_215.40)    # = SuperTrend line
```
- The strategy is **sizing-agnostic** — it emits price + stop only; the engine handles risk-sizing.

### Slide 15 — Signal → Trade (Engine)
1. `broker.check_stops(bar)` — close at stop if `low ≤ stop` (long) or `high ≥ stop` (short)
2. `broker.fill_pending(bar)` — last bar's order fills at **this bar's open + slippage**
3. `strategy.on_bar(bar, ctx)` — emit new `Signal`
4. `size_position(equity, risk_pct, entry, stop, fees, slippage)` — fixed-fractional, fee-aware (audit H5)
5. Queue `Order` for next bar
- `risk_pct=0.02` → max 2% of equity per trade
- `taker_fee_bps=4`, `slippage_bps=2`
- Code: `core/engine.py:175`, `core/engine_sync.py:29`

---

## Section 5 — LLM Bot: Features → 3 Agents → Consensus → Trade (6 min)

### Slide 16 — Why Multi-Agent (Not Single-LLM)?
- Three specialised analysts with disjoint information:
  - **Technical** — sees indicator scalars only
  - **QABBA** — sees order-flow scalars only
  - **Visual** — sees a candlestick chart image only
- Decision is **deterministic math** on their three votes — the LLM is not asked to "combine" anything.
- Topology: `START → {technical, visual, qabba} → decision → END` (LangGraph, parallel fan-out)
- Code: `strategies/llm_agents/graph.py:45`

### Slide 17 — Feature Extraction (per bar)
- After warmup (60 bars), `LLMAgentStrategy.on_bar` computes:
  ```python
  features = {
      "ema_fast":  EMA(close, 12).iloc[-1],
      "ema_slow":  EMA(close, 26).iloc[-1],
      "rsi":       RSI(close, 14).iloc[-1],
      "macd_hist": MACD(close).hist.iloc[-1],
      "adx":       ADX(high, low, close, 14).iloc[-1],
      "cvd":       bar.cvd,
      "cvd_delta": bar.cvd_delta,
  }
  ```
- Chart PNG: last 60 bars rendered by `mplfinance` (Agg backend), base64-encoded.
- Code: `strategies/llm_agents/strategy.py:91`, `chart.py:26`

### Slide 18 — Per-Agent Prompts (literal templates)
- **Technical** (`prompts.py:34`):
  > "You are a technical analyst. Given these indicator readings, output one of BUY, SELL, HOLD followed by a confidence in [0,1] and a one-line rationale. Format: `<ACTION> <CONFIDENCE> <RATIONALE>`. Features: ema_fast=84321.12 ema_slow=83998.40 rsi=58.1 macd_hist=12.3 adx=24.4"
- **QABBA** (`prompts.py:45`):
  > "You are a quantitative order-flow analyst (QABBA). Given the cumulative volume delta readings... Features: cvd=1234.5 cvd_delta=−56.97"
- **Visual** (`prompts.py:59`):
  > "You are a chart-pattern analyst. Examine the attached candlestick chart and..." (+ PNG attached as `data:image/png;base64,...`)

### Slide 19 — Real Cached Responses (one bar)
```json
// technical
{"content": "HOLD 0.62 EMA crossover signals are weak with
  fast EMA below slow EMA, RSI at 44 suggests neutral
  momentum, but ADX of 21.9 indicates insufficient trend
  strength to commit to a directional trade.",
 "input_tokens": 113, "output_tokens": 57}

// qabba
{"content": "SELL 0.72 Negative CVD delta (-56.97) indicates
  recent aggressive selling pressure despite positive
  cumulative position, suggesting momentum reversal risk.",
 "input_tokens": 95, "output_tokens": 37}

// visual
{"content": "SELL 0.72 Price has broken below key support
  levels with increased selling volume spikes around 12:30,
  forming lower lows and lower highs in a clear downtrend.",
 "input_tokens": 448, "output_tokens": 44}
```
- Parser extracts `<ACTION> <CONFIDENCE>` via regex (`nodes/_parse.py:16`).

### Slide 20 — Decision Math (deterministic, no LLM)
- Weights (from `config.yaml`): **QABBA = 0.40, Visual = 0.35, Technical = 0.25**
- Per side: `score(side) = Σ wᵢ × confᵢ` for analysts voting that side
- Threshold = **0.35**
- Rule: side wins iff `score > threshold` **and** strictly greater than the opposing side; otherwise HOLD
- Example above → Tech=HOLD, Q=SELL 0.72, V=SELL 0.72
  - `sell_score = 0.40 × 0.72 + 0.35 × 0.72 = 0.540` → exceeds 0.35 → **SELL**
- Code: `strategies/llm_agents/nodes/decision.py:33`

### Slide 21 — Regime Gate + Stop Placement
- SuperTrend gate (re-audit C3 fix, `strategy.py:184`):
  - If consensus = BUY but `st_dir = −1` (line above price) → emit **HOLD** instead
  - If consensus = SELL but `st_dir = +1` (line below price) → emit **HOLD**
  - Reason: a wrong-sided stop is rejected silently by `core/engine.py:121`, leaking signals into the void
- Otherwise: `stop_loss = SuperTrend line`, sized identically to traditional bot
- From here on, **the trade execution flow is identical** — same `Signal` → same engine → same broker

---

## Section 6 — Live Demo (3 min)

### Slide 22 — Live Cache-Replay
- Run `main.py` against committed LLM cache (1,263 responses, no network, ~30s)
- Cache key = `(model, agent, prompt_hash, image_hash, bar_timestamp_ms)`
- Watch Rich TUI: per-bar signal, equity curves, win%, MDD
- Optional `run.dump_bar_artifacts: true` writes `results/runs/<id>/BTC_USDT/bars/<NNN>/` per candle — prompts, chart PNG, raw analyst replies, decision JSON (for live audit Q&A)
- Switch to terminal; see `demo_cheatsheet.md` for exact commands

---

## Section 7 — Results (3 min)

### Slide 23 — Headline Figures
| Metric | Traditional | LLM |
|---|---|---|
| Return | **+3.07%** | **−6.20%** |
| Max DD | −6.46% | −10.90% |
| Trades | 4 | 10 |
| Win % | 50.0% | 30.0% |
| Profit Factor | 1.72 | 0.41 |
| Sharpe | +0.40 | −0.71 |
- Run: `results/runs/20260516T215247Z/`

### Slide 24 — Loss Attribution
- LLM BUY trades: 5 × +$22 total
- LLM SELL trades: 5 × **−$642 total**
- Market trended **80,800 → 85,500** (uptrend). The LLM repeatedly faded the trend.
- Traditional held one BUY for 200 bars and captured **+4.42%**; LLM avg hold = 37 bars (over-trades by 2.5×).

### Slide 25 — Why? Three Honest Hypotheses
1. **CVD over-weighted (0.40)** — short-term order flow contradicted trend in a way the decision math couldn't override.
2. **SuperTrend(10,3) regime gate too jittery** — flips on intra-bar noise; longer-horizon filter would help.
3. **No fee/slippage in the LLM's reasoning** — the LLM doesn't know trades cost 6 bps; the engine fee-discounted sizing, not the LLM.

---

## Section 8 — Conclusion + Q&A (2 min)

### Slide 26 — Contribution + Open Questions
- **Contribution**: an open, reproducible, byte-deterministic comparison harness (cache replay → same numbers forever)
- LLM losing IS a finding — it scopes where LLMs do and don't help
- Open questions for the room:
  - Would prompt-engineering the regime context change the verdict?
  - Is 15m too noisy a timeframe to compare apples-to-apples?
  - Should the decision node itself be an LLM (with explicit fee/slippage context)?
- Thank you — questions?
