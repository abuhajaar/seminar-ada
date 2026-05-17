# English Delivery Script — 30 Minutes (Data-Pipeline-Heavy)

Target: ~150 words/minute spoken; ~22 min speaking + ~3 min demo + transitions = 30 min total.
Indexes against `slide_outline.md` slide numbers.

---

## Section 1 — Intro & Problem (00:00 → 03:00)

[SLIDE 1: Title]
[00:00]

Good morning everyone, and thank you for joining today's seminar. The title of this work is "Comparative Study: Classical Technical Analysis versus an LLM Multi-Agent Trading System on BTC/USDT." Because this is an Advanced Data Analysis forum, I am going to spend most of the next thirty minutes inside the data pipeline itself — not on philosophy and not on hype, but on exactly what bytes arrive from the exchange, exactly how those bytes get transformed, exactly what each agent in our system sees, and exactly how a decision becomes a filled trade.

[BULLETS]
- Comparative Study: Classical TA vs LLM Multi-Agent on BTC/USDT
- Seminar focus: Advanced Data Analysis
- The data pipeline is the story today

[NOTE TO PRESENTER] Set the tone: this is a data-engineering talk that happens to be about trading bots, not a trading talk that happens to use data.

[SLIDE 2: Research Question]
[00:50]

The research question is straightforward. Can a Large Language Model multi-agent system, reading the same raw market data as a deterministic technical-analysis rulebook, produce competitive trading decisions? I want to be honest from the first minute: the answer we measured is not the answer most people expect. The LLM bot lost money in our test window. That is the finding. That is what makes this study academically defensible — we built a comparison harness that is byte-deterministic and reproducible, and we report what came out of it.

[BULLETS]
- Same input data, two decision systems
- LLM bot lost money in the test window — that IS the finding
- Today: focus on the pipeline that produced this number

[NOTE TO PRESENTER] Pause for two seconds after "lost money" — let it land. Then move on confidently.

---

## Section 2 — Data Source & Raw API Format (03:00 → 07:00)

[SLIDE 3: Data Sources]
[03:00]

Let us begin where every quantitative study begins: with the source. We pull market data from **Binance Spot**, the largest crypto exchange by volume. The asset is BTC versus USDT, the timeframe is fifteen minutes per bar, and the test window is five days — from April tenth to April fifteenth, 2025. That gives us four hundred and eighty bars total.

We hit two REST endpoints. The first is `GET /api/v3/klines`, which returns candlestick data with one critical extra field — the taker buy volume. I will come back to why that matters in ninety seconds. The second is `GET /api/v3/aggTrades`, which returns every individual trade tick. We actually no longer use the aggTrades endpoint in the hot path because we discovered a sixty-to-two-hundred-times speedup using kline data alone. The code that does the fetching is in `data/downloader.py`, line 42 — it goes through the ccxt library's `publicGetKlines` method.

[BULLETS]
- Binance Spot REST API
- BTC/USDT, 15m, 480 bars (2025-04-10 → 2025-04-15)
- Two endpoints: klines + aggTrades (latter optional)
- ccxt `publicGetKlines`, paginated 1000 rows at a time

[SLIDE 4: Raw Kline Response]
[03:50]

Here is what the raw API response actually looks like, byte-for-byte. Binance returns each candle as a twelve-element JSON array. Element zero is the open timestamp in milliseconds. Then four price strings — open, high, low, close. Then volume, the close timestamp, quote-asset volume, the number of trades, and then the field we care about most: the taker buy base volume. Plus two more fields we ignore.

Two things to notice. First, all the prices and volumes come in as **JSON strings**, not numbers — we cast them to float in `downloader.py` line 113. Second, we keep only seven of the twelve fields: timestamp, OHLCV, and taker buy volume. The rest are discarded at write-time.

[BULLETS]
- 12-element array per candle, prices/volumes as JSON strings
- We keep: timestamp, open, high, low, close, volume, taker_buy_volume
- We discard: close_time, quote_vol, n_trades, taker_buy_quote, ignore

[NOTE TO PRESENTER] Point at the array on the slide; emphasise "this is what the network gives you, this is what we keep."

[SLIDE 5: Why taker_buy_volume Matters]
[04:50]

Why did we obsess over that single field? Because it lets us derive **cumulative volume delta** — CVD — without paying for tick data. CVD is the running balance of aggressive-buy volume minus aggressive-sell volume. It is one of the most commonly cited order-flow indicators in modern quant trading.

The math is a two-line identity. Volume equals taker-buy plus taker-sell. CVD-delta equals taker-buy minus taker-sell. Subtract one from the other: `cvd_delta equals two times taker_buy_volume minus volume`. That is it. We get CVD essentially for free from data we already have. Code reference: `data/cvd.py` line 50, the function `cvd_from_klines`. This change alone gave us a sixty-to-two-hundred-times speedup over downloading aggTrades for every bar.

[BULLETS]
- CVD = cumulative (aggressive-buy − aggressive-sell)
- Identity: cvd_delta = 2 × taker_buy_volume − volume
- 60–200× faster than aggTrades; same numerical result
- `data/cvd.py:50` `cvd_from_klines`

[SLIDE 6: Final Bar Object]
[06:00]

After preprocessing, the engine consumes a stream of Python `Bar` dataclasses. Each `Bar` has nine fields — timestamp, OHLC, volume, taker buy volume, cumulative CVD, and this bar's CVD delta. One `Bar` per fifteen-minute interval. Four hundred and eighty `Bar` objects total. The loader at `data/loader.py` line 19 strictly enforces timestamp alignment between the OHLCV CSV and the CVD parquet — if even one timestamp is out of sync, it raises a `ValueError`. We never silently misalign data.

[BULLETS]
- `Bar(timestamp, OHLC, volume, taker_buy_volume, cvd, cvd_delta)`
- 480 Bars total
- Strict timestamp alignment; misalignment raises ValueError

---

## Section 3 — Preprocessing & Indicator Transformations (07:00 → 12:00)

[SLIDE 7: Warmup Discipline]
[07:00]

Before either strategy emits a single signal, we wait sixty bars. Why sixty? Because the slowest indicator in our stack — MACD with parameters twelve, twenty-six, nine — produces its first non-NaN value at bar thirty-four. SuperTrend needs roughly ten bars of ATR seasoning. EMA-50 obviously needs fifty bars. Sixty gives us a comfortable ceiling above all of those. This constant is enforced in both strategies — `strategies/traditional.py:38` and `strategies/llm_agents/strategy.py:39`. Without this discipline, the LLM would receive prompts containing the literal string `"nan"` and produce garbage output. We learned that the hard way during audit.

[BULLETS]
- WARMUP = 60 bars before any signal
- Slowest indicator: MACD(12,26,9), first valid at bar 34
- Enforced in both strategies
- Pre-fix bug: prompts leaked `"nan"`, audit H1/H3

[SLIDE 8: Indicator Set]
[08:00]

Here is the full indicator inventory. EMAs at periods twenty and fifty for the traditional bot, twelve and twenty-six for the LLM bot. RSI period fourteen. MACD twelve over twenty-six with signal nine. ADX period fourteen as the trend-strength filter. SuperTrend with length ten and multiplier three — used both as a stop-loss level and a regime indicator. And finally, CVD, which only the LLM bot consumes through its QABBA agent.

Notice the EMA divergence. The traditional bot uses 20/50, which is a classic medium-term cross. The LLM bot uses 12/26, which is faster and more reactive — these match the MACD periods. This is a deliberate parameter choice that comes from our spec; the LLM gets faster signals because it is supposed to think harder about them. Whether that was wise is something the data will tell us in twenty minutes.

[BULLETS]
- EMA: 20/50 (Trad), 12/26 (LLM)
- RSI(14), MACD(12,26,9), ADX(14)
- SuperTrend(10, 3) — stop + regime
- CVD — LLM only

[SLIDE 9: SuperTrend Up Close]
[09:30]

SuperTrend deserves its own slide because it does two jobs. The math is simple: take the midpoint of high and low — `hl2` — and add or subtract three times the ATR. That gives you two basic bands, upper and lower. A carry-forward rule keeps the band trailing — it only loosens, never tightens against the trend. The function returns two columns: `st`, the stop-line price, and `dir`, the regime sign. When `dir` equals plus one, the line is **below** price — long-friendly. When `dir` equals minus one, the line is **above** price — short-friendly. We use the line as a stop and the sign as a gate. Code: `indicators/ta.py:124`.

[BULLETS]
- `hl2 ± 3 × ATR(10)` with carry-forward
- Returns: `st` (stop line), `dir` (+1 long, −1 short)
- Two jobs: stop level **and** regime gate
- `indicators/ta.py:124`

[SLIDE 10: Transformation Pipeline Diagram]
[10:30]

Putting it all together, here is the end-to-end pipeline. Binance REST returns the twelve-column kline JSON. ccxt paginates it a thousand rows at a time. We write seven columns to an OHLCV CSV. We derive CVD into a parquet file. The loader joins them on timestamp and yields a stream of `Bar` objects. From that stream, two consumers diverge — the traditional rulebook and the LLM feature extractor with its chart renderer. Everything downstream of the `Bar` stream is what makes the two bots different. Everything upstream of it is shared. That separation is intentional — it is what makes the comparison fair.

[BULLETS]
- Shared upstream: REST → OHLCV + CVD → Bar stream
- Diverges only after `Bar`: rules vs features+chart
- Same input, different processing — that's the fair comparison

---

## Section 4 — Traditional Bot: Data → Signal → Trade (12:00 → 16:00)

[SLIDE 11: The Rulebook]
[12:00]

The traditional bot is intentionally simple and intentionally transparent. The decision rule fits on one slide. First filter: ADX above twenty — there must be a trend. Then: if EMA-20 is above EMA-50, and the MACD histogram is positive, and RSI is below seventy, and SuperTrend direction is plus one — go long. Mirror conditions go short. Anything else, hold. This is a "confluence" rule — four indicators must agree. It is one hundred percent deterministic. Same bar, same signal, every time. Code: `strategies/traditional.py:47`.

[BULLETS]
- ADX > 20 filter (trend required)
- BUY: EMA20>EMA50 & MACD_hist>0 & RSI<70 & ST_dir=+1
- SELL: mirror conditions
- 100% deterministic — same bar, same signal

[SLIDE 12: Signal Object]
[13:30]

The strategy emits a `Signal` dataclass with four fields: the action, a confidence number derived from how strong ADX is, a human-readable reasoning string for logging, and crucially — the stop-loss price, which is just the SuperTrend line at this bar. Notice what is missing: there is no position size. The strategy is deliberately **sizing-agnostic**. It says "I want to go long at this price with this stop." The engine decides how big. This separation lets us reuse the same risk-sizing for both bots later.

[BULLETS]
- `Signal(action, confidence, reasoning, stop_loss)`
- stop_loss = SuperTrend line at this bar
- Strategy is sizing-agnostic — engine handles risk

[SLIDE 13: Signal → Trade]
[14:30]

Now the engine. Five steps per bar, in this exact order. Step one — check stops on the freshly-opened bar; if intra-bar low touched our stop on a long, we close at the stop. Step two — fill any order queued by the previous bar; the fill price is **this bar's open** plus or minus slippage. We never fill at the bar where the signal was generated — that would be look-ahead bias. Step three — strategy emits a new signal. Step four — if it is not HOLD, we size the position using `size_position`, which accounts for fees and slippage in the worst-case stop-out loss. Risk per trade is two percent of equity. Step five — mark equity at bar close for the equity curve. This same loop runs for both bots — they only differ in step three. Code: `core/engine.py:175`, sizing at `core/engine_sync.py:29`.

[BULLETS]
- 1) check_stops → 2) fill_pending(next open + slip) → 3) on_bar → 4) size + queue → 5) mark
- Fill at next bar's open — no look-ahead bias
- risk_pct=0.02, fees=4 bps, slippage=2 bps
- Identical loop for both bots — only step 3 differs

---

## Section 5 — LLM Bot: Features → 3 Agents → Consensus → Trade (16:00 → 22:00)

[SLIDE 14: Why Multi-Agent]
[16:00]

The LLM bot does not ask a single LLM "should I buy?" That would be naive — language models hallucinate, and you have no way to audit a single opaque answer. Instead, we use three specialised analysts, each with deliberately **disjoint** information. The Technical agent sees only indicator scalars. The QABBA agent sees only order-flow scalars. The Visual agent sees only a candlestick chart image. Then a deterministic decision node performs weighted math on their three votes. The LLM is never asked to combine anything — that is closed-form arithmetic. The topology is built with LangGraph: `START → {technical, visual, qabba} → decision → END`. The three analysts run in parallel. Code: `strategies/llm_agents/graph.py:45`.

[BULLETS]
- 3 agents, disjoint inputs (numbers / numbers / image)
- Decision is **deterministic math**, not LLM
- LangGraph parallel fan-out
- `graph.py:45`

[SLIDE 15: Feature Extraction]
[17:30]

Once past warmup, on every bar we compute the feature dict. EMA-fast, EMA-slow, RSI, MACD histogram, ADX, cumulative CVD, and the current bar's CVD delta. Seven scalars. We also render the last sixty bars as a candlestick PNG using `mplfinance` on the Agg backend — that is matplotlib in headless mode, which gives us byte-stable PNGs within a single environment. The PNG gets base64-encoded and attached to the Visual agent's prompt. Code: `strategies/llm_agents/strategy.py:91`, chart rendering at `chart.py:26`.

[BULLETS]
- 7 scalar features per bar
- + 60-bar candlestick PNG (mplfinance, Agg backend)
- base64-encoded for the Visual agent
- Byte-stable within a single environment → enables cache replay

[SLIDE 16: Per-Agent Prompts]
[19:00]

These are the **actual** prompt templates, taken straight from `prompts.py`. The Technical agent gets: "You are a technical analyst. Given these indicator readings... output one of BUY, SELL, HOLD followed by a confidence in zero-to-one and a one-line rationale. Format: ACTION CONFIDENCE RATIONALE. Features: ema_fast equals such-and-such, ema_slow equals such-and-such, rsi, macd_hist, adx." QABBA gets the same structure but only the CVD readings. Visual gets the role description plus an attached image — no numbers in the text.

Notice three deliberate design choices. One, we constrain the output format aggressively — `ACTION CONFIDENCE RATIONALE` — so a regex parser can extract the answer. Two, we render numbers with a custom formatter that never uses scientific notation, because the regex does not understand `e+06`. Three, we keep prompts terse to stay inside our ten-dollar-per-run budget cap.

[BULLETS]
- 3 prompts, literal templates from `prompts.py`
- Constrained output: `ACTION CONFIDENCE RATIONALE`
- No scientific notation (regex parser limitation)
- Terse → fits inside $10/run budget

[SLIDE 17: Real Cached Responses]
[20:30]

And here is what one bar of real responses looks like — pulled from our committed cache, from a real Claude Haiku 4.5 run. The Technical agent said HOLD with confidence 0.62, explaining that the EMA crossover signals were weak. QABBA said SELL 0.72, flagging a negative CVD delta of about minus fifty-seven units. Visual said SELL 0.72, describing a clear downtrend on the chart. All three responses are JSON objects on disk — content, model, input tokens, output tokens. The first token before the confidence is what our regex parser at `nodes/_parse.py:16` extracts. It is tolerant — it grabs the first BUY-SELL-HOLD token it finds, case-insensitive, with word boundaries.

[BULLETS]
- Real Claude Haiku 4.5 responses on disk (cache replay)
- Three votes for ONE bar: HOLD 0.62, SELL 0.72, SELL 0.72
- Regex parser tolerates noise around the action token

[SLIDE 18: Decision Math]
[21:00]

Now the decision node. This is where you would expect another LLM call — and there is not one. It is closed-form math. The weights come from our config file: QABBA 0.40, Visual 0.35, Technical 0.25. For each side — BUY and SELL — we compute the weighted sum of confidences from analysts voting that side. Threshold is 0.35. A side wins if and only if its score exceeds the threshold **and** strictly exceeds the opposing side; otherwise the decision is HOLD.

On the example from the previous slide: Technical voted HOLD, so it contributes to neither side. QABBA SELL 0.72 contributes 0.40 times 0.72 equals 0.288. Visual SELL 0.72 contributes 0.35 times 0.72 equals 0.252. SELL score totals 0.540 — well above the 0.35 threshold. So the decision is SELL with confidence 0.540. Reproducible, auditable, no hallucination possible at this stage. Code: `strategies/llm_agents/nodes/decision.py:33`.

[BULLETS]
- Weights: Q=0.40, V=0.35, T=0.25; threshold=0.35
- Per side: `Σ wᵢ × confᵢ` over analysts voting that side
- Winner = max(buy, sell) if > threshold and > opposing
- Example: SELL wins 0.540

[SLIDE 19: Regime Gate + Stop Placement]
[21:30]

One more gate before the signal leaves the strategy. If consensus says BUY but SuperTrend direction is minus one — line above price — we override to HOLD. Same in reverse: SELL in an up-regime becomes HOLD. Why? Because the engine has a stop-direction check at `core/engine.py:121` that silently rejects orders with wrong-sided stops. Without this regime gate, we were emitting signals into a void — they showed up in logs but never opened a position. We caught that in a re-audit and fixed it in the C3 patch. After this gate, the LLM bot emits the exact same `Signal` dataclass as the traditional bot — and from there onwards, the trade execution flow is **identical**. Same engine, same broker, same risk sizing, same fees. The only thing that differs between the two bots is what produced the signal.

[BULLETS]
- BUY in down-regime → HOLD; SELL in up-regime → HOLD
- Without this: signals dropped silently by engine H4 gate
- C3 patch at `strategy.py:184`
- From `Signal` onwards: identical execution to traditional

---

## Section 6 — Live Demo (22:00 → 25:00)

[SLIDE 20: Live Cache-Replay]
[22:00]

Let me show this running. The demo is a **cache replay** — we are not calling OpenRouter live during the seminar, because that would risk network issues. Instead, we have committed one thousand two hundred and sixty-three cached LLM responses to disk. The cache key is the tuple of model, agent name, prompt hash, image hash, and bar timestamp in milliseconds. When `main.py` runs, every LLM call hits the cache instead of the network. End-to-end run completes in about thirty seconds.

[NOTE TO PRESENTER] Switch to terminal. Run `.\.venv\Scripts\python.exe main.py`. Talk through the Rich TUI as it updates: per-bar signal, equity curves, trade count, win percentage, max drawdown. Total elapsed about thirty seconds.

[NOTE TO PRESENTER] After completion, mention the run summary lives in `results/runs/<timestamp>/summary.json`. Switch back to slides.

---

## Section 7 — Results (25:00 → 28:00)

[SLIDE 21: Headline Numbers]
[25:00]

Here are the numbers. Traditional bot: plus 3.07 percent return, max drawdown minus 6.46 percent, four trades, fifty percent win rate, profit factor 1.72, Sharpe 0.40. LLM bot: minus 6.20 percent return, max drawdown minus 10.90 percent, ten trades, thirty percent win rate, profit factor 0.41, Sharpe minus 0.71. The LLM lost money. It traded more, won less, and drew down further. Run identifier on disk is `20260516T215247Z`.

[BULLETS]
- Trad: +3.07% / DD −6.46% / 4 trades / PF 1.72
- LLM:  −6.20% / DD −10.90% / 10 trades / PF 0.41
- LLM lost, over-traded, drew down more

[SLIDE 22: Loss Attribution]
[26:00]

Where did the loss come from? Splitting LLM trades by direction: five BUY trades summed to plus twenty-two dollars. Five SELL trades summed to **minus six hundred and forty-two dollars**. The market trended from 80,800 up to 85,500 — a clear uptrend. The LLM repeatedly faded that trend. Meanwhile the traditional bot held one BUY position for two hundred bars and captured plus 4.42 percent. The LLM's average hold time was thirty-seven bars — it over-trades by two and a half times.

[BULLETS]
- LLM BUY: 5 × +$22 total
- LLM SELL: 5 × **−$642 total**
- Market trended +5.8%; LLM faded the trend
- LLM avg hold 37 bars vs Trad 95 bars

[SLIDE 23: Three Honest Hypotheses]
[27:00]

Three hypotheses for why this happened, all testable. First — the CVD weight of 0.40 is the largest weight in the decision math, and order flow on a fifteen-minute timeframe is noisy. Short-term selling pressure was over-emphasised. Second — the SuperTrend regime gate at length ten, multiplier three, flips on intra-bar noise. A longer-horizon regime filter — say a daily SuperTrend overlay — would probably remove most of the bad shorts. Third — the LLM does not see fees or slippage in its prompt. It reasons as if trades are free; the engine fee-discounts the sizing, but the LLM never learns from the cost. All three are concrete follow-up experiments.

[BULLETS]
- H1: CVD weight 0.40 too high for 15m timeframe
- H2: SuperTrend(10,3) too jittery — needs longer-horizon filter
- H3: LLM unaware of fee/slippage cost
- All testable in the same harness

---

## Section 8 — Conclusion + Q&A (28:00 → 30:00)

[SLIDE 24: Contribution + Open Questions]
[28:00]

To wrap up. Our contribution is not "LLMs beat technical analysis" — they did not, in our window. Our contribution is a reproducible, byte-deterministic comparison harness. The cached responses on disk mean anyone can re-run our experiment and get the exact same numbers. The decision math is closed-form. The data pipeline is documented end-to-end. The losing LLM result is a finding that scopes where LLMs help and where they hurt.

Open questions I would love the room's input on: Would prompt-engineering explicit regime context — "the market has trended up six percent this week" — change the verdict? Is fifteen-minute too noisy a timeframe to compare deterministic rules and probabilistic LLMs apples-to-apples? Should the **decision node itself** be an LLM, given the right context window? Thank you — I am happy to take questions.

[BULLETS]
- Contribution: reproducible byte-deterministic comparison harness
- LLM loss is a scoping finding, not a failure
- Three open questions for the room
- Thank you

[NOTE TO PRESENTER] Open the floor. Anchor answers in code references — `strategies/llm_agents/strategy.py`, `nodes/decision.py`, `prompts.py` — so questions stay technical.

---

## Q&A Appendix (prepared answers)

**Q1: Why Claude Haiku and not GPT-4 or a local model?**
A: Cost — Haiku 4.5 is roughly twenty times cheaper than Claude Sonnet at one dollar per million input tokens. For a study with this many bars (480 bars × 3 agents = 1,440 LLM calls per run), cost matters. We could swap models trivially — `config.yaml` line 28 — and the cache invalidates on model change.

**Q2: Is 480 bars enough for a statistical conclusion?**
A: No. Honestly stated in the conclusion. The harness is designed for cheap repeats — you can run it across a year of data for under fifty dollars in API spend. The five-day window is a methodology demo, not a definitive verdict.

**Q3: What about overfitting?**
A: The traditional bot has fixed parameters from `config.yaml` — they are not tuned on this window. The LLM bot has the same SuperTrend, same ADX, same MACD. No hyperparameter search was performed. Both bots are out-of-sample on this window.

**Q4: How do you know the cache replay matches the live run?**
A: Cache key includes bar timestamp in milliseconds. Same bar, same prompt, same model → same response. We verified this on a live re-run on `20260516T215247Z` — bit-for-bit identical equity curves.

**Q5: What if the LLM contradicts itself on the same bar across re-runs?**
A: With `temperature=0` in the config and a deterministic prompt builder, OpenRouter responses are stable enough that the cache hits perfectly. We have not seen drift.

**Q6: Why those specific consensus weights — 0.40, 0.35, 0.25?**
A: Spec choice from the original literature we built on. QABBA gets the highest weight because order flow is the most leading indicator in liquid markets. Visual second because chart patterns capture multi-scale context. Technical lowest because the technical agent's information is the most redundant with the SuperTrend gate. Whether this ordering is right is exactly the kind of question Hypothesis 1 in the results section is asking.

**Q7: Could you replace the deterministic decision node with another LLM?**
A: Yes — the architecture allows it. The prompt template at `prompts.py:73` already exists for logging purposes. We chose deterministic math for auditability — when something looks wrong, we can prove what happened. If we let the LLM decide, we lose that property.
