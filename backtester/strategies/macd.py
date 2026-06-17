"""
MACD Strategy — trend/momentum on MACD line vs signal line.

Logic:
  BUY  when the MACD line crosses ABOVE its signal line (bullish cross).
  SELL when the MACD line crosses BELOW its signal line (bearish cross).
Long-only; full-position entry/exit.

Parameters:
  fast / slow / signal : MACD EMA periods (12 / 26 / 9)
  invest_per_trade_usd : USD per entry (0 → fixed units)
  quantity             : fixed units fallback
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from engine.indicators import compute
from strategies.base import BaseStrategy, Param, signals_from_masks


class MACDStrategy(BaseStrategy):
    """MACD crossover: buy bullish cross, sell bearish cross."""

    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast":                 Param("number", "Fast EMA", min=2, max=100, step=1, group="Signal"),
            "slow":                 Param("number", "Slow EMA", min=3, max=200, step=1, group="Signal"),
            "signal":               Param("number", "Signal EMA", min=2, max=100, step=1, group="Signal"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "fast":                 12,
            "slow":                 26,
            "signal":               9,
            "invest_per_trade_usd": 1000.0,
            "quantity":             0.01,
        }

    def _validate_params(self, params: dict):
        if params["fast"] >= params["slow"]:
            raise ValueError("fast must be < slow")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        m = compute(df, "macd", fast=self.fast, slow=self.slow, signal=self.signal)
        diff = m["macd"] - m["macd_signal"]
        prev = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
