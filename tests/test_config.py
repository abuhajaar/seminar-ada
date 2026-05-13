from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest

from core.config import AppConfig, load_config


def test_load_config_from_repo_root(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(dedent("""
        run:
          assets: [BTC/USDT]
          timeframe: 1h
          start: 2025-04-01
          end:   2025-04-21
          initial_balance: 10000
        execution:
          fill: next_bar_open
          taker_fee_bps: 4
          slippage_bps: 2
          risk_pct: 0.02
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
            technical: { model: x/y, temperature: 0 }
            visual:    { model: x/y, temperature: 0, chart_window: 100 }
            qabba:     { model: x/y, temperature: 0, lookback: 50 }
            decision:  { model: x/y, temperature: 0 }
          consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
          consensus_threshold: 0.50
        data:
          source: binance
          qabba_mode: aggtrades
    """))
    cfg = load_config(cfg_path)
    assert isinstance(cfg, AppConfig)
    assert cfg.run.assets == ["BTC/USDT"]
    assert cfg.run.timeframe == "1h"
    assert cfg.run.start == date(2025, 4, 1)
    assert cfg.execution.taker_fee_bps == 4
    assert cfg.indicators.macd == (12, 26, 9)
    assert cfg.indicators.supertrend == (10, 3)
    assert cfg.llm.consensus_weights["qabba"] == 0.40
    assert cfg.data.qabba_mode == "aggtrades"


def test_consensus_weights_must_sum_to_one(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(dedent("""
        run:
          assets: [BTC/USDT]
          timeframe: 1h
          start: 2025-04-01
          end: 2025-04-21
          initial_balance: 10000
        execution: { fill: next_bar_open, taker_fee_bps: 4, slippage_bps: 2, risk_pct: 0.02 }
        indicators:
          rsi: 14
          macd: [12,26,9]
          adx: 14
          ema_fast: 20
          ema_slow: 50
          supertrend: [10,3]
        llm:
          cache_dir: cache/llm
          max_usd: 10
          agents:
            technical: { model: x, temperature: 0 }
            visual:    { model: x, temperature: 0, chart_window: 100 }
            qabba:     { model: x, temperature: 0, lookback: 50 }
            decision:  { model: x, temperature: 0 }
          consensus_weights: { qabba: 0.50, visual: 0.50, technical: 0.50 }
          consensus_threshold: 0.50
        data: { source: binance, qabba_mode: aggtrades }
    """))
    with pytest.raises(ValueError, match="consensus_weights"):
        load_config(cfg_path)


def test_qabba_mode_only_aggtrades(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(dedent("""
        run:
          assets: [BTC/USDT]
          timeframe: 1h
          start: 2025-04-01
          end: 2025-04-21
          initial_balance: 10000
        execution: { fill: next_bar_open, taker_fee_bps: 4, slippage_bps: 2, risk_pct: 0.02 }
        indicators:
          rsi: 14
          macd: [12,26,9]
          adx: 14
          ema_fast: 20
          ema_slow: 50
          supertrend: [10,3]
        llm:
          cache_dir: cache/llm
          max_usd: 10
          agents:
            technical: { model: x, temperature: 0 }
            visual:    { model: x, temperature: 0, chart_window: 100 }
            qabba:     { model: x, temperature: 0, lookback: 50 }
            decision:  { model: x, temperature: 0 }
          consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
          consensus_threshold: 0.50
        data: { source: binance, qabba_mode: kline }
    """))
    with pytest.raises(ValueError, match="qabba_mode"):
        load_config(cfg_path)
