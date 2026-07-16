"""
MA Cross Strategy — generic fast/slow moving-average crossover.

Logic:
  BUY  when the fast MA crosses ABOVE the slow MA (golden cross).
  SELL when the fast MA crosses BELOW the slow MA (death cross).
Generalises PLA's entry trigger without the cascading average-down.
Long-only; full-position entry/exit.

Parameters:
  ma_type              : 'ema' | 'sma' | 'wma' | 'hma'
  fast / slow          : fast and slow MA periods (default 20 / 50)
  invest_per_trade_usd : USD per entry (0 → fixed units)
  quantity             : fixed units fallback
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from backtesting.engine.indicators import compute
from backtesting.strategies.base import BaseStrategy, Param, signals_from_masks


class MACrossStrategy(BaseStrategy):
    """Moving-average crossover: buy golden cross, sell death cross."""

    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "ma_type":              Param("select", "MA Type", options=["ema", "sma", "wma", "hma"], group="Signal"),
            "fast":                 Param("number", "Fast Period", min=2, max=200, step=1, group="Signal"),
            "slow":                 Param("number", "Slow Period", min=3, max=400, step=1, group="Signal"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "ma_type":              "ema",
            "fast":                 20,
            "slow":                 50,
            "invest_per_trade_usd": 1000.0,
            "quantity":             0.01,
        }

    def _validate_params(self, params: dict):
        if params["fast"] >= params["slow"]:
            raise ValueError("fast must be < slow")
        if params["ma_type"] not in ("ema", "sma", "wma", "hma"):
            raise ValueError("ma_type must be one of ema/sma/wma/hma")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        key = self.ma_type
        fast = compute(df, key, length=self.fast)[key]
        slow = compute(df, key, length=self.slow)[key]
        diff = fast - slow
        prev = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
