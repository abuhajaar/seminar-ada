# English Delivery Script — 30 Minutes (Data-Pipeline-Heavy)

Target: ~150 words/minute spoken; ~22 min speaking + ~3 min demo + transitions = 30 min total.
Indexes against `slide_outline.md` slide indexes.
Tone: conversational-academic. Single thread analogy: **three analysts in a trading room**.

---

## Section 1 — Context, Problem & Hypothesis (00:00 → 04:00)

[SLIDE 1: Title]
[00:00]

Good morning everyone, and thanks for coming. Today's seminar is about two trading bots, side by side on the same data. The title says "Comparative Study: Classical TA against LLM Multi-Agent on BTC/USDT," and the topic falls under Advanced Data Analysis. Before any code, let me set up the problem — what the two bots are, why anyone would build an LLM-based one at all, and what we wanted to find out.

[BULLETS]
- Comparative Study: Classical TA vs LLM Multi-Agent on BTC/USDT
- Seminar topic: Advanced Data Analysis
- Today: problem setup, then the pipeline end-to-end

[NOTE TO PRESENTER] Slow opening. Don't drop the analogy yet — that lands on slide 3.

[SLIDE 2: The Problem]
[00:45]

Crypto markets move twenty-four hours a day, no holidays. No human can sit at a desk and decide every fifteen minutes for five days straight. So people build bots. The classical way — call it the **traditional bot** — uses a fixed rulebook: if EMA-fast crosses above EMA-slow and MACD confirms, buy. Hard-coded logic. Same input, same output. Fast, cheap, predictable, and the industry standard for two decades.

But here is the catch. A rulebook bot only sees what its rules look at. If the rule says "EMA cross," it does not notice the giant red candle pattern next to it. It does not notice buyers hitting the offer ten times in a row. It is blind to anything outside the rule. So the question is: **can we do better by giving the bot eyes?**

[BULLETS]
- Crypto: 24/7, humans can't keep up
- Traditional bot = fixed rulebook, fast, predictable
- Limit: blind to anything outside the rule

[NOTE TO PRESENTER] Pause before "give the bot eyes" — that pivots into the LLM idea.

[SLIDE 3: The Idea — Three Analysts]
[01:50]

Here is the idea. Imagine three analysts in a small trading room. One stares at the indicator panel — EMAs, MACD, the numerical scalars. One reads the candle chart like an x-ray, looking for shapes. The third watches the buy-and-sell flow — who's hitting the bid, who's lifting the offer, in real time. Same fifteen-minute Bitcoin candle, three sets of eyes. Each writes a short note — BUY, SELL, or HOLD — slides it across the desk to the boss, and the boss applies a fixed weighted formula to make the final call.

**That is our LLM bot.** Each analyst is a Large Language Model — same model, different jobs, different views of the same data. The boss is **not** an LLM. The boss is a weighted sum. LLM does the looking, math does the deciding. I'll come back to that split.

[BULLETS]
- 3 LLM analysts: indicators / chart / order-flow
- Each writes BUY, SELL, or HOLD with a confidence score
- The boss = fixed weighted formula, not an LLM
- LLM looks, math decides

[SLIDE 4: Hypothesis & Honest Outcome]
[02:55]

So the hypothesis is simple. Can the three-analyst LLM team — same data as the classical bot — make competitive trading calls? Honest answer up top: **no, not in our test window.** The LLM bot lost money. The classical bot beat it. That is the finding. What makes the study defensible is that we built a byte-level reproducible test bench, and we report what came out — not what we hoped.

Today's job is not to sell you LLMs. Today's job is to walk the pipeline end-to-end and show you where the LLM gave up its edge. Most of the time will sit at the data layer.

[BULLETS]
- Hypothesis: LLM team can match or beat classical TA
- Measured: LLM lost, classical won
- Today: walk the pipeline that produced this answer

[NOTE TO PRESENTER] Pause two seconds after "lost money" — let it land.

---

## Section 2 — Data Source & Raw Inputs (04:00 → 07:00)

[SLIDE 5: Data Sources]
[04:00]

Okay so before our three analysts can do anything, they need data. And that data has to come from somewhere real. We pull market data from **Binance Spot**, the biggest crypto exchange by volume. Asset is BTC against USDT, timeframe is fifteen minutes per bar, test window is five days — April tenth to April fifteenth, 2025. That gives us four hundred and eighty bars total. Think of those bars as 480 "snapshots" of the market, one every fifteen minutes — that is the raw material our analysts get to chew on.

We use two endpoints. The main one is the klines endpoint — `GET /api/v3/klines` — which gives us candlestick data plus one critical extra field, the taker-buy volume. We'll see why that field is key in a moment. There is also an aggTrades endpoint that gives every single trade tick, but we don't use it in the hot path anymore — kline data alone gave us a sixty-to-two-hundred-times speedup. Fetching code lives at `data/downloader.py:42`, going through ccxt's `publicGetKlines`.

[BULLETS]
- Binance Spot REST API
- BTC/USDT, 15m, 480 bars (2025-04-10 → 2025-04-15)
- Two endpoints: klines (used) + aggTrades (skipped)
- `data/downloader.py:42`, paginated 1000 rows at a time

[SLIDE 6: What Binance Gives Us]
[05:00]

Here is what a raw kline looks like. Binance hands us each candle as a 12-element JSON array. Out of those 12 fields, we keep seven: timestamp, OHLC, volume, and taker-buy volume. The other five — close-time, quote-volume, trade-count, taker-buy-quote, plus an "ignore" slot — we throw away at write time. One thing to flag: every price and volume comes in as a JSON **string**, not a number. So we cast them to float ourselves in `downloader.py:113`. Small detail, but if you miss it your whole pipeline silently breaks.

[BULLETS]
- 12-element JSON array per candle
- Keep 7 fields: timestamp, OHLC, volume, taker_buy_volume
- Cast string → float at `downloader.py:113`

[SLIDE 7: Why taker_buy_volume Is Key]
[05:45]

So why are we obsessing on that one extra field? Because it lets us give our third analyst — the order-flow one — what he needs to do his job, **without paying for expensive tick data**. The metric is called cumulative volume delta, or CVD. Picture it as a running tally: every time aggressive buyers lift the offer, the tally goes up; every time aggressive sellers hit the bid, it goes down. Over time you can see who is winning — buyers or sellers.

The math is a two-line identity. Volume equals taker-buy plus taker-sell. CVD-delta equals taker-buy minus taker-sell. Subtract one from the other and you get: `cvd_delta = 2 × taker_buy_volume − volume`. That is it. We get CVD essentially for free from data we already have. Code lives at `data/cvd.py:50`, the function `cvd_from_klines`. This one shortcut gave us the 60-to-200-times speedup I mentioned. So now our order-flow analyst has his tally, cheap.

[BULLETS]
- CVD = cumulative (aggressive-buy − aggressive-sell)
- Identity: cvd_delta = 2 × taker_buy_volume − volume
- 60–200× faster than aggTrades; same numerical answer
- `data/cvd.py:50` `cvd_from_klines`

[SLIDE 8: Final Bar Object]
[06:30]

After preprocessing, the engine eats a stream of Python `Bar` dataclasses. Think of each `Bar` as one neat line in the trading room's logbook — everything our analysts need to know about one fifteen-minute slice of the market. Nine fields total: timestamp, OHLC, volume, taker-buy volume, cumulative CVD, and the current bar's CVD delta. One `Bar` per fifteen-minute slot. 480 `Bar` objects in total.

The loader at `data/loader.py:19` strictly checks timestamp alignment between the OHLCV CSV and the CVD CSV — if even one timestamp is off, it throws a `ValueError` and the run stops cold. We never silently misalign data. That kind of bug — two different bars accidentally pretending to be the same bar — would poison everything downstream. So we'd much rather crash loudly than quietly give wrong answers.

[BULLETS]
- `Bar(timestamp, OHLC, volume, taker_buy_volume, cvd, cvd_delta)`
- 480 Bars total
- Strict timestamp alignment; misalignment → ValueError

---

## Section 3 — Preprocessing & Indicator Transformations (07:00 → 12:00)

[SLIDE 9: Warmup Discipline]
[07:00]

Now here's a subtle but key rule. Before either strategy emits a single signal, we wait sixty bars. Why sixty? Because the slowest indicator in our stack — MACD with settings twelve, twenty-six, nine — doesn't produce its to start valid value until bar thirty-four. SuperTrend needs about ten bars of ATR seasoning. EMA-50 obviously needs fifty bars. So sixty gives us a comfortable ceiling above all of those.

This constant is enforced in both strategies — `strategies/traditional.py:38` and `strategies/llm_agents/strategy.py:39`. Without it, our LLM analysts would receive prompts containing the literal string `"nan"` — that's "not a number" — and they'd hallucinate confidently about garbage data. We actually learned this the hard way during audit. So now we just wait. The analysts don't even walk into the trading room until they have real figures to look at.

[BULLETS]
- WARMUP = 60 bars before any signal
- Slowest indicator: MACD(12,26,9), earliest valid at bar 34
- Enforced in both strategies
- Pre-fix bug: prompts leaked `"nan"`, audit H1/H3

[SLIDE 10: Indicator Set]
[08:00]

Okay, here's the full indicator inventory. Think of this as the toolkit on every analyst's desk. EMAs at periods twenty and fifty for the traditional bot, twelve and twenty-six for the LLM bot. RSI period fourteen. MACD twelve over twenty-six with signal nine. ADX period fourteen as the trend-strength filter. SuperTrend with length ten and multiplier three — used as both a stop-loss level and a regime indicator. And finally CVD, which only our order-flow analyst — the QABBA agent — gets to see.

Notice the EMA divergence. The traditional bot uses 20/50, which is a classic medium-term cross. The LLM bot uses 12/26, which is faster and more reactive — and these match the MACD periods, so the LLM gets internally consistent signals. This is a deliberate parameter choice. The LLM gets faster signals because it's supposed to think harder about them. Whether that was wise — well, the data will tell us in twenty minutes.

[BULLETS]
- EMA: 20/50 (Trad), 12/26 (LLM)
- RSI(14), MACD(12,26,9), ADX(14)
- SuperTrend(10, 3) — stop + regime
- CVD — LLM only

[SLIDE 11: SuperTrend Up Close]
[09:30]

SuperTrend deserves its own slide because it does two jobs at once — and you'll see it again later, so it pays to see it now. The math is simple: take the midpoint of high and low — that's `hl2` — and add or subtract three times the ATR. That gives you two basic bands, one above price, one below. A carry-ahead rule keeps the band trailing — it only loosens, never tightens against the trend. So if price is moving up, the lower band trails up; if price moves down, the upper band trails down.

The function gives back two columns: `st`, the stop-line price, and `dir`, the regime sign. When `dir` equals plus one, the line is **below** price — that's long-friendly. When `dir` equals minus one, the line is **above** price — that's short-friendly. Think of it like a traffic light that also doubles as a guardrail: it tells you which way you're allowed to go, and where to stop if you go wrong. Code: `indicators/ta.py:124`.

[BULLETS]
- `hl2 ± 3 × ATR(10)` with carry-ahead
- Gives back: `st` (stop line), `dir` (+1 long, −1 short)
- Two jobs: stop level **and** regime gate
- `indicators/ta.py:124`

[SLIDE 12: Transformation Pipeline Diagram]
[10:30]

Putting it all together, here's the end-to-end pipeline. Binance REST gives us the twelve-column kline JSON. ccxt paginates it a thousand rows at a time. We write seven columns to an OHLCV CSV. We derive CVD into a separate CSV file — same plain-text format, easy to diff, easy to inspect. The loader joins them on timestamp and yields a stream of `Bar` objects. From that stream, two consumers diverge — the traditional rulebook over here, and the LLM feature extractor plus chart renderer over there.

Now here's the key point. Everything **downstream** of the `Bar` stream is what makes the two bots different. Everything **upstream** of it is shared. Same exchange, same bars, same indicators. That separation is intentional — it's what makes the comparison fair. Both bots get the same trading-room window, the same view of the market. What changes is who's sitting at the desk and how they decide.

[BULLETS]
- Shared upstream: REST → OHLCV + CVD → Bar stream
- Diverges only after `Bar`: rules vs features+chart
- Same input, different processing — that's the fair comparison

---

## Section 4 — Traditional Bot: Data → Signal → Trade (12:00 → 16:00)

[SLIDE 13: The Rulebook]
[12:00]

Let's start with the simpler of the two bots — the traditional one. Picture this as a single senior analyst working alone, following a fixed checklist. No discussion, no second opinions, just a rulebook. The whole rule fits on one slide. To start filter: ADX above twenty — there must be a real trend, if not we just sit out. Then: if EMA-20 is above EMA-50, AND the MACD histogram is positive, AND RSI is below seventy, AND SuperTrend direction is plus one — go long. Mirror conditions go short. Anything else, hold.

This is what's called a **confluence rule** — four indicators all have to agree. It's a hundred percent fixed-formula. Same bar, same signal, every single time. If you run it twice on the same data, you get bit-for-bit identical answers. No surprises, no creativity. Code: `strategies/traditional.py:47`.

[BULLETS]
- ADX > 20 filter (trend required)
- BUY: EMA20>EMA50 & MACD_hist>0 & RSI<70 & ST_dir=+1
- SELL: mirror conditions
- 100% fixed-formula — same bar, same signal

[SLIDE 14: Signal Object]
[13:30]

The strategy emits a `Signal` dataclass — basically a structured note. Four fields: the action, a confidence number derived from how strong the ADX reading is, a human-readable reasoning string for logging, and crucially — the stop-loss price, which is just the SuperTrend line at this bar.

Now notice what's **missing**. There's no position size. That's deliberate. The strategy is what we call **sizing-agnostic**. It says "I want to go long at this price with this stop." It doesn't say "buy two BTC." The engine handles position size separately. This separation lets us reuse the exact same risk-sizing logic for both bots later — which means when we compare results, we're comparing the *decision-making*, not the risk-management.

[BULLETS]
- `Signal(action, confidence, reasoning, stop_loss)`
- stop_loss = SuperTrend line at this bar
- Strategy is sizing-agnostic — engine handles risk

[SLIDE 15: Signal → Trade]
[14:30]

Now the engine — this is where signal becomes actual trade. Five steps per bar, in this exact order. Step one — check stops on the freshly-opened bar; if the intra-bar low touched our stop on a long position, we close at the stop. Step two — fill any order that was queued by the previous bar; the fill price is **this bar's open**, plus or minus slippage. Critical point — we never fill at the same bar where the signal was generated. Why? Because that would be look-ahead bias — using data we couldn't possibly have known at signal time. Step three — strategy emits a new signal. Step four — if it's not HOLD, we size the position using `size_position`, which accounts for fees and slippage in the worst-case stop-out loss. Risk per trade is two percent of equity. Step five — mark equity at bar close for the equity curve.

This same five-step loop runs for **both** bots. They only differ in step three — who's making the decision. Everything else is identical. Code: `core/engine.py:175`, sizing at `core/engine_sync.py:29`.

[BULLETS]
- 1) check_stops → 2) fill_pending(next open + slip) → 3) on_bar → 4) size + queue → 5) mark
- Fill at next bar's open — no look-ahead bias
- risk_pct=0.02, fees=4 bps, slippage=2 bps
- Identical loop for both bots — only step 3 differs

---

## Section 5 — LLM Bot: Features → 3 Agents → Consensus → Trade (16:00 → 22:00)

[SLIDE 16: Why Multi-Agent]
[16:00]

Okay, now we get to the heart of the talk — the three-analyst trading room. Here's the thing: we did **not** just ask a single LLM "hey, should I buy?" That would be naive. Language models hallucinate, and worse, you have no way to audit a single opaque answer. If it's wrong, you don't even know *why* it's wrong.

So instead, we hire three specialised analysts, each with deliberately **disjoint** data. The Technical agent sees only indicator scalars — figures on a screen. The QABBA agent sees only order-flow scalars — the buyers-and-sellers tally. The Visual agent sees only a candlestick chart image — no figures, just the picture. Then a fixed-formula decision node — the boss — performs weighted math on their three votes. The LLM is never asked to combine anything itself — that part is closed-form arithmetic, no room for hallucination. The whole thing is wired up with LangGraph: `START → {technical, visual, qabba} → decision → END`. The three analysts run in parallel, like a real team conferring on the same bar. Code: `strategies/llm_agents/graph.py:45`.

[BULLETS]
- 3 agents, disjoint inputs (indicator scalars / order-flow scalars / chart image)
- Decision is **fixed-formula math**, not LLM
- LangGraph parallel fan-out
- `graph.py:45`

[SLIDE 17: Feature Extraction]
[17:30]

Once we're past the warmup, on every single bar we compute the feature dict. Seven scalars: EMA-fast, EMA-slow, RSI, MACD histogram, ADX, cumulative CVD, and this bar's CVD delta. Each analyst gets only the slice that's relevant to them.

We also render the last sixty bars as a candlestick PNG using `mplfinance` on the Agg backend — that's matplotlib running in headless mode, which gives us byte-stable PNGs within a single environment. That PNG gets base64-encoded and stapled to the Visual agent's prompt — basically slid across the desk to him with his note. The byte-stability is key because it's what enables our cache replay later — same candle picture, same hash, cache hit. Code: `strategies/llm_agents/strategy.py:91`, chart rendering at `chart.py:26`.

[BULLETS]
- 7 scalar features per bar
- + 60-bar candlestick PNG (mplfinance, Agg backend)
- base64-encoded for the Visual agent
- Byte-stable within a single environment → enables cache replay

[SLIDE 18: Per-Agent Prompts]
[19:00]

These are the **actual** prompt templates, taken straight from `prompts.py` — not paraphrased. The Technical agent gets: "You are a technical analyst. Given these indicator readings... output one of BUY, SELL, HOLD followed by a confidence in zero-to-one and a one-line rationale. Shape: ACTION CONFIDENCE RATIONALE. Features: ema_fast equals such-and-such, ema_slow equals such-and-such, rsi, macd_hist, adx." QABBA gets the exact same structure but only the CVD readings — that's all his desk has. Visual gets the role description plus the attached image — and notably, no figures in the text at all. He has to read the picture.

Three deliberate design choices here. One — we constrain the output shape aggressively, `ACTION CONFIDENCE RATIONALE`, so a regex extractor can extract the answer cleanly. Two — we render figures with a custom formatter that never uses scientific notation, because the regex doesn't see `e+06`. Three — we keep the prompts terse, partly for clarity, partly to stay inside our ten-dollar-per-run budget cap. Every token costs money at scale.

[BULLETS]
- 3 prompts, literal templates from `prompts.py`
- Constrained output: `ACTION CONFIDENCE RATIONALE`
- No scientific notation (regex extractor limitation)
- Terse → fits inside $10/run budget

[SLIDE 19: Real Cached Responses]
[20:30]

Now this slide — pay attention — this is what one bar of real responses actually looks like. Pulled directly from our committed cache, from a real Claude Haiku 4.5 run. The Technical agent — looking at his figures — said HOLD with confidence 0.62, explaining the EMA crossover signals were weak. QABBA — looking at his order-flow tally — said SELL 0.72, flagging a negative CVD delta of about minus fifty-seven units. The Visual agent — staring at the candle picture — said SELL 0.72, describing a clear downtrend on the picture. All three responses are JSON objects on disk — content, model, input tokens, output tokens.

The leading token before the confidence is what our regex extractor at `nodes/_parse.py:16` pulls out. It's deliberately tolerant — grabs the leading BUY-SELL-HOLD token it finds, case-insensitive, with word boundaries — so the analysts can be a little messy in their prose and we still get a clean vote.

[BULLETS]
- Real Claude Haiku 4.5 responses on disk (cache replay)
- Three votes for ONE bar: HOLD 0.62, SELL 0.72, SELL 0.72
- Regex extractor tolerates noise around the action token

[SLIDE 20: Decision Math]
[21:00]

Now the boss makes a call. And here's the thing — you'd probably expect another LLM call here, right? The chairman weighing the analysts' opinions? Nope. There's no LLM here at all. It's plain closed-form math. The weights come from our config file: QABBA 0.40, Visual 0.35, Technical 0.25 — buy-sell flow weighted highest because it tends to lead, technical lowest because it overlaps with our SuperTrend gate. For each side — BUY and SELL — we sum the weighted confidences from the analysts voting that side. The threshold is 0.35. A side wins if and only if its score crosses the threshold **and** strictly exceeds the opposing side. If not, HOLD.

Let's run the example from the previous slide right here. Technical voted HOLD, so he contributes to neither side. QABBA voted SELL 0.72 — that's 0.40 times 0.72 equals 0.288. Visual voted SELL 0.72 — that's 0.35 times 0.72 equals 0.252. SELL score totals 0.540 — well above the 0.35 threshold. So the boss's decision is SELL with confidence 0.540. Reproducible, auditable, zero hallucination at this stage. Code: `strategies/llm_agents/nodes/decision.py:33`.

[BULLETS]
- Weights: Q=0.40, V=0.35, T=0.25; threshold=0.35
- Per side: `Σ wᵢ × confᵢ` over analysts voting that side
- Winner = max(buy, sell) if > threshold and > opposing
- Example: SELL wins 0.540

[SLIDE 21: Regime Gate + Stop Placement]
[21:30]

One more checkpoint before the signal leaves the trading room. Think of this as the risk manager standing at the door. If the consensus says BUY but SuperTrend's regime says we're in a downtrend — line above price — the risk manager overrides to HOLD. Same in reverse: SELL in an uptrend becomes HOLD. Why bother? Because the engine has a stop-direction check at `core/engine.py:121` that **silently** rejects orders with wrong-sided stops. Before this gate existed, we were emitting signals into a void — they showed up in the logs but never actually opened a position. We caught that in a re-audit and patched it as the C3 fix.

After this gate, the LLM bot emits the exact same `Signal` dataclass as the traditional bot. And from that point onwards, the trade execution flow is **identical**. Same engine, same broker, same risk sizing, same fees. The only thing that differs between the two bots is what produced the signal — a confluence rule against three analysts plus a boss. Everything after the `Signal` is shared.

[BULLETS]
- BUY in down-regime → HOLD; SELL in up-regime → HOLD
- Without this: signals dropped silently by engine H4 gate
- C3 patch at `strategy.py:184`
- From `Signal` onwards: identical execution to traditional

---

## Section 6 — Live Demo (22:00 → 25:00)

[SLIDE 22: Live Cache-Replay]
[22:00]

Alright, let me show this running. The demo is a **cache replay** — and that's key. We are **not** calling OpenRouter live during the seminar, because that would risk network hiccups eating my talk time. Instead, we've committed one thousand two hundred and sixty-three cached LLM responses to disk. Think of it as the recorded transcript of every analyst meeting from the test window — we hit "play" instead of asking them all over again.

The cache key is a tuple — model, agent name, prompt hash, image hash, and bar timestamp in milliseconds. So every LLM call `main.py` makes hits the cache instead of the network. End-to-end run completes in about thirty seconds.

One more thing — for live audit questions, we can flip `run.dump_bar_artifacts: true` in `config.yaml`, and every single candle leaves a folder behind under `results\runs\<id>\BTC_USDT\bars\<NNN>\`. Inside each folder: the exact indicator scalars the traditional bot saw, the exact prompts each LLM analyst received, the chart PNG that went to the visual agent, the raw text replies, and the final decision JSON. So if someone in the room asks "what did the chart analyst actually see at bar 217?" — we can open that folder and show them, byte-for-byte.

[NOTE TO PRESENTER] Switch to terminal. Run `.\.venv\Scripts\python.exe main.py`. Talk through the Rich TUI as it updates: per-bar signal, equity curves, trade count, win percentage, max drawdown. Total elapsed about thirty seconds.

[NOTE TO PRESENTER] After completion, mention the run summary lives in `results/runs/<timestamp>/summary.json`. Switch back to slides.

---

## Section 7 — Results (25:00 → 28:00)

[SLIDE 23: Headline Figures]
[25:00]

Okay, the tally. Traditional bot — the solo senior analyst — pulled plus 3.07 percent return, max drawdown minus 6.46 percent, four trades, fifty percent win rate, profit factor 1.72, Sharpe 0.40. LLM bot — the three-analyst trading room — pulled minus 6.20 percent return, max drawdown minus 10.90 percent, ten trades, thirty percent win rate, profit factor 0.41, Sharpe minus 0.71. The LLM lost money. It traded more, won less, and drew down further. Run identifier on disk: `20260516T215247Z` — anyone in the room can re-run it themselves and get the exact same figures.

[BULLETS]
- Trad: +3.07% / DD −6.46% / 4 trades / PF 1.72
- LLM:  −6.20% / DD −10.90% / 10 trades / PF 0.41
- LLM lost, over-traded, drew down more

[SLIDE 24: Loss Attribution]
[26:00]

So where did the loss actually come from? Let's split the LLM's trades by direction. Five BUY trades summed to plus twenty-two USD — basically flat. Five SELL trades summed to **minus six hundred and forty-two USD**. That's almost the whole loss right there, in the shorts. Meanwhile the market trended from 80,800 up to 85,500 — a clear five-and-a-half percent uptrend. So our three-analyst room kept fading a real uptrend. They were too eager to sell.

By contrast, the traditional senior analyst held one BUY position for two hundred bars and captured plus 4.42 percent. The LLM's average hold time was thirty-seven bars — it over-trades by roughly two and a half times. So the LLM was both wrong about direction *and* impatient with the time horizon.

[BULLETS]
- LLM BUY: 5 × +$22 total
- LLM SELL: 5 × **−$642 total**
- Market trended +5.8%; LLM faded the trend
- LLM avg hold 37 bars vs Trad 96 bars

[SLIDE 25: Three Honest Hypotheses]
[27:00]

Three honest hypotheses for why this happened — all testable in the same test bench. One — the CVD weight of 0.40 is the largest weight in the decision math, and buy-sell flow on a fifteen-minute timeframe is noisy. We probably overweighted short-term selling pressure. Second — SuperTrend at length ten, multiplier three, flips on intra-bar noise. A longer-horizon regime filter — say a daily SuperTrend overlay sitting above the fifteen-minute one — would probably remove most of the bad shorts. Third — and this one is interesting — the LLM has no idea trades cost money. It reasons as if every trade is free. The engine fee-discounts the sizing, but the LLM never *learns* from the cost. It just keeps trading. All three are concrete follow-up experiments — and the cached-replay test bench makes them cheap to run.

[BULLETS]
- H1: CVD weight 0.40 too high for 15m timeframe
- H2: SuperTrend(10,3) too jittery — needs longer-horizon filter
- H3: LLM unaware of fee/slippage cost
- All testable in the same test bench

---

## Section 8 — Conclusion + Q&A (28:00 → 30:00)

[SLIDE 26: Contribution + Open Questions]
[28:00]

To wrap up. Our contribution is **not** "LLMs beat technical analysis" — they didn't, at least in our window. Our contribution is a reproducible, byte-fixed-formula comparison test bench. The cached responses on disk mean anyone here can re-run our experiment and get the exact same figures. The decision math is closed-form. The data pipeline is documented end-to-end. The losing LLM result is a finding that scopes where LLMs help — and where they hurt.

Three open questions I'd love this room's input on. One — would prompt-engineering explicit regime context, telling each analyst "the market has trended up six percent this week," change the final call? Second — is fifteen-minute too noisy a timeframe to compare fixed-formula rules against probabilistic LLMs apples-to-apples? Third — should the **decision node itself** be an LLM, given the right context window? Thanks — I'm happy to take questions.

[BULLETS]
- Contribution: reproducible byte-fixed-formula comparison test bench
- LLM loss is a scoping finding, not a failure
- Three open questions for the room
- Thank you

[NOTE TO PRESENTER] Open the floor. Anchor answers in code references — `strategies/llm_agents/strategy.py`, `nodes/decision.py`, `prompts.py` — so questions stay technical.

---

## Q&A Appendix (prepared answers)

**Q1: Why Claude Haiku and not GPT-4 or a local model?**
A: Honestly? Cost. Haiku 4.5 is about twenty times cheaper than Claude Sonnet at one dollar per million input tokens. For a study with this many bars — 480 bars times 3 agents equals 1,440 LLM calls per run — cost is key a lot. We can swap models trivially though, it's `config.yaml` line 28, and the cache invalidates automatically when the model changes.

**Q2: Is 480 bars enough for a statistical conclusion?**
A: No, honestly. And we say so in the conclusion. The test bench is designed for cheap repeats — you can run it across a year of data for under fifty USD in API spend. The five-day window is a methodology demo, not a definitive final call on LLM trading.

**Q3: What about overfitting?**
A: The traditional bot has fixed settings straight from `config.yaml` — they're not tuned on this window. The LLM bot uses the same SuperTrend, same ADX, same MACD. No hyperparameter search was performed. Both bots are out-of-sample on this window.

**Q4: How do you know the cache replay matches the live run?**
A: The cache key includes the bar timestamp in milliseconds. Same bar, same prompt, same model → same response. We verified this on a live re-run of `20260516T215247Z` — bit-for-bit identical equity curves. So the replay you saw in the demo is faithful to what the bot would actually do live.

**Q5: What if the LLM contradicts itself on the same bar across re-runs?**
A: With `temperature=0` in the config and a fixed-formula prompt builder, OpenRouter responses are stable enough that the cache hits perfectly. We haven't seen any drift in practice.

**Q6: Why those specific consensus weights — 0.40, 0.35, 0.25?**
A: It's a spec choice from the literature we built on. QABBA gets the highest weight because buy-sell flow tends to be the most leading indicator in liquid markets — it tells you *who's actually trading* before price has moved much. Visual second because candle picture patterns capture multi-scale context that scalar indicators miss. Technical lowest because the technical analyst's data overlaps the most with our SuperTrend gate — he's partly saying what the gate already knows. Whether this ordering is right is exactly what Hypothesis 1 in the results section is asking.

**Q7: Could you replace the fixed-formula decision node with another LLM?**
A: Yes — the architecture allows it. The prompt template at `prompts.py:73` already exists for logging purposes. We chose fixed-formula math for auditability — when something looks wrong, we can prove exactly what happened. If we let an LLM be the boss too, we lose that property. We thought that tradeoff wasn't worth it for an academic comparison study, but for production it might be different.
