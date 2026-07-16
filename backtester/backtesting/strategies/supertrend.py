"""
Supertrend Strategy — trend following on Supertrend direction flips.

Logic:
  BUY  when Supertrend flips to up-trend (direction -1 → +1).
  SELL when Supertrend flips to down-trend (direction +1 → -1).
Long-only; full-position entry/exit.

Parameters:
  length / multiplier  : ATR period and band multiplier (10 / 3.0)
  invest_per_trade_usd : USD per entry (0 → fixed units)
  quantity             : fixed units fallback
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from backtesting.engine.indicators import compute
from backtesting.strategies.base import BaseStrategy, Param, signals_from_masks


class SupertrendStrategy(BaseStrategy):
    """Supertrend trend-following: buy on up-flip, sell on down-flip."""

    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":               Param("number", "ATR Length", min=2, max=100, step=1, group="Signal"),
            "multiplier":           Param("number", "Multiplier", min=0.5, max=10, step=0.5, group="Signal"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "length":               10,
            "multiplier":           3.0,
            "invest_per_trade_usd": 1000.0,
            "quantity":             0.01,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        st = compute(df, "supertrend", length=self.length, multiplier=self.multiplier)
        d = st["supertrend_dir"]
        prev = d.shift(1)
        entry = (prev < 0) & (d > 0)
        exit_ = (prev > 0) & (d < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
