"""Pydantic config model + loader for `config.yaml`."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class RunCfg(BaseModel):
    assets: list[str]
    timeframe: str
    start: date
    end: date
    initial_balance: float


class ExecutionCfg(BaseModel):
    fill: Literal["next_bar_open"]
    taker_fee_bps: float
    slippage_bps: float
    risk_pct: float = Field(gt=0, lt=1)


class IndicatorsCfg(BaseModel):
    rsi: int
    macd: tuple[int, int, int]
    adx: int
    ema_fast: int
    ema_slow: int
    supertrend: tuple[int, float]

    @field_validator("macd", mode="before")
    @classmethod
    def _macd_tuple(cls, v):
        return tuple(v)

    @field_validator("supertrend", mode="before")
    @classmethod
    def _st_tuple(cls, v):
        return tuple(v)


class AgentCfg(BaseModel):
    model: str
    temperature: float = 0.0
    chart_window: int | None = None
    lookback: int | None = None

    @field_validator("temperature")
    @classmethod
    def _temperature_must_be_zero(cls, v: float) -> float:
        if v != 0:
            raise ValueError(
                "LLM temperature must be 0 for deterministic backtests (spec Q2)."
            )
        return v


class PricingCfg(BaseModel):
    in_per_1m: float = Field(ge=0)
    out_per_1m: float = Field(ge=0)


class LlmCfg(BaseModel):
    cache_dir: str
    max_usd: float
    mock: bool = False
    image_window_bars: int = 60
    agents: dict[str, AgentCfg]
    consensus_weights: dict[str, float]
    consensus_threshold: float
    pricing: dict[str, PricingCfg]
    expected_output_tokens: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = sum(self.consensus_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"consensus_weights must sum to 1.0, got {total}"
            )
        return self

    @model_validator(mode="after")
    def _every_agent_model_priced(self):
        missing = [
            f"{name} -> {agent.model}"
            for name, agent in self.agents.items()
            if agent.model not in self.pricing
        ]
        if missing:
            raise ValueError(
                "Every agent's model must have a pricing entry. Missing: "
                + ", ".join(missing)
            )
        return self


class DataCfg(BaseModel):
    source: Literal["binance"]
    qabba_mode: Literal["aggtrades"]


class AppConfig(BaseModel):
    run: RunCfg
    execution: ExecutionCfg
    indicators: IndicatorsCfg
    llm: LlmCfg
    data: DataCfg


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())
    return AppConfig.model_validate(raw)
