from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from core.config import AgentCfg, AppConfig, LlmCfg, load_config


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
          pricing:
            x/y: { in_per_1m: 3.0, out_per_1m: 15.0 }
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
          pricing:
            x: { in_per_1m: 3.0, out_per_1m: 15.0 }
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
          pricing:
            x: { in_per_1m: 3.0, out_per_1m: 15.0 }
        data: { source: binance, qabba_mode: kline }
    """))
    with pytest.raises(ValueError, match="qabba_mode"):
        load_config(cfg_path)


def test_agent_cfg_rejects_nonzero_temperature():
    """Spec Q2 mandates temperature=0 for deterministic backtests."""
    with pytest.raises(ValidationError):
        AgentCfg(model="anthropic/claude-3.5-sonnet", temperature=0.7)


def test_agent_cfg_accepts_zero_temperature():
    a = AgentCfg(model="anthropic/claude-3.5-sonnet", temperature=0.0)
    assert a.temperature == 0.0


def test_llm_cfg_has_mock_and_image_window_defaults():
    cfg = LlmCfg(
        cache_dir="cache/llm",
        max_usd=1.0,
        agents={"technical": AgentCfg(model="x/y", temperature=0)},
        consensus_weights={"qabba": 0.40, "visual": 0.35, "technical": 0.25},
        consensus_threshold=0.50,
        pricing={"x/y": {"in_per_1m": 3.0, "out_per_1m": 15.0}},
    )
    assert cfg.mock is False
    assert cfg.image_window_bars == 60
    assert cfg.expected_output_tokens == 300


_VALID_YAML_WITH_PRICING = dedent("""
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
        technical: { model: anthropic/claude-3.5-sonnet, temperature: 0 }
        visual:    { model: anthropic/claude-3.5-sonnet, temperature: 0, chart_window: 100 }
        qabba:     { model: anthropic/claude-3.5-sonnet, temperature: 0, lookback: 50 }
        decision:  { model: anthropic/claude-3.5-sonnet, temperature: 0 }
      consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
      consensus_threshold: 0.50
      expected_output_tokens: 300
      pricing:
        anthropic/claude-3.5-sonnet:
          in_per_1m: 3.0
          out_per_1m: 15.0
    data:
      source: binance
      qabba_mode: aggtrades
""")


_YAML_MISSING_PRICING = dedent("""
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
        technical: { model: anthropic/claude-3.5-sonnet, temperature: 0 }
        visual:    { model: openai/gpt-4o, temperature: 0, chart_window: 100 }
        qabba:     { model: anthropic/claude-3.5-sonnet, temperature: 0, lookback: 50 }
        decision:  { model: anthropic/claude-3.5-sonnet, temperature: 0 }
      consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
      consensus_threshold: 0.50
      expected_output_tokens: 300
      pricing:
        anthropic/claude-3.5-sonnet:
          in_per_1m: 3.0
          out_per_1m: 15.0
    data:
      source: binance
      qabba_mode: aggtrades
""")


def test_llm_cfg_accepts_pricing_block(tmp_path):
    """Valid config with pricing entries for every agent loads cleanly."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_VALID_YAML_WITH_PRICING, encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.llm.pricing["anthropic/claude-3.5-sonnet"].in_per_1m == 3.0
    assert cfg.llm.expected_output_tokens == 300


def test_llm_cfg_rejects_agent_without_pricing(tmp_path):
    """If an agent uses a model with no pricing entry, load_config raises."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(_YAML_MISSING_PRICING, encoding="utf-8")
    with pytest.raises(ValueError, match="pricing entry"):
        load_config(cfg_path)
