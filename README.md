# seminar-ada

Comparative analysis of heuristic vs cognitive multi-agent crypto trading systems.

## Status

**Sub-plan A complete:** data layer, indicators, config, types.
- Download Binance OHLCV (via ccxt) and aggTrades (via REST), aggregate CVD per bar, stream bars as `core.types.Bar`.
- Vectorized RSI, MACD, ADX, EMA, SuperTrend in `indicators/ta.py`, validated against `pandas-ta`.

Test suite: 32 passing, 1 skipped (live network smoke), 96% line coverage on `core/`, `data/`, `indicators/`.

**Next:** sub-plan B — execution layer (portfolio, broker, metrics) + traditional bot + minimal sync engine.

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
- Sub-plans B/C/D: TBD after A is reviewed.
