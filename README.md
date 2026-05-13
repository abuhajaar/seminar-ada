# seminar-ada

Comparative analysis of heuristic vs cognitive multi-agent crypto trading systems.

## Status

**Sub-plan A complete:** data layer, indicators, config, types.
**Sub-plan B complete:** execution layer (portfolio, broker, metrics) + Traditional bot + sync engine harness.

- Data: download Binance OHLCV (ccxt) + aggTrades (REST), aggregate CVD per bar.
- Indicators: RSI, MACD, ADX, EMA, SuperTrend (vectorized, validated against pandas-ta).
- Execution: shared portfolio + broker with next-bar fills, taker fees, slippage, intra-bar stops.
- Metrics: Total Return, MDD, Win Rate, Profit Factor, Sharpe.
- Traditional bot: indicator-confluence rule with SuperTrend stops + 2%-risk sizing.
- Engine: synchronous single-strategy harness (async dual-strategy + TUI in sub-plan D).

Test suite: 79 passing, 1 skipped (live network smoke), 97% line coverage on `core/`, `data/`, `indicators/`, `strategies/`.

**Next:** sub-plan C — LLM agent subsystem (4 LangGraph nodes + cache + budget guard + MockClient).

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

## Spec

- English: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.en.md`
- Indonesian: `docs/superpowers/specs/2026-05-13-comparative-trading-backtest-design.id.md`

## Plans

- Sub-plan A: `docs/superpowers/plans/2026-05-13-sub-plan-A-data-and-indicators.md` (complete)
- Sub-plan B: `docs/superpowers/plans/2026-05-13-sub-plan-B-execution-and-traditional-bot.md` (complete)
- Sub-plans C/D: TBD.
