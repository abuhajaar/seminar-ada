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


class LlmCfg(BaseModel):
    cache_dir: str
    max_usd: float
    agents: dict[str, AgentCfg]
    consensus_weights: dict[str, float]
    consensus_threshold: float

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = sum(self.consensus_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"consensus_weights must sum to 1.0, got {total}"
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
