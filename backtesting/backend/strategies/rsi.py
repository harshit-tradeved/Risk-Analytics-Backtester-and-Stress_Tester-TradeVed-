"""
RSI Strategy — mean reversion on the Relative Strength Index.

Logic:
  BUY  when RSI crosses up through `oversold` (exiting oversold territory).
  SELL when RSI crosses down through `overbought` (exiting overbought).
Long-only; full-position entry/exit.

Parameters:
  length         : int   — RSI lookback (default 14)
  oversold       : float — buy threshold (default 30)
  overbought     : float — sell threshold (default 70)
  invest_per_trade_usd : float — USD per entry (0 → use fixed units)
  quantity       : float — fixed units fallback
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from backtesting.backend.engine.indicators import compute
from backtesting.backend.strategies.base import BaseStrategy, Param, signals_from_masks


class RSIStrategy(BaseStrategy):
    """RSI mean-reversion: buy exiting oversold, sell exiting overbought."""

    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":               Param("number", "RSI Length", min=2, max=100, step=1, group="Signal"),
            "oversold":             Param("number", "Oversold", min=1, max=50, step=1, group="Signal"),
            "overbought":           Param("number", "Overbought", min=50, max=99, step=1, group="Signal"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "length":               14,
            "oversold":             30.0,
            "overbought":           70.0,
            "invest_per_trade_usd": 1000.0,
            "quantity":             0.01,
        }

    def _validate_params(self, params: dict):
        if params["oversold"] >= params["overbought"]:
            raise ValueError("oversold must be < overbought")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        rsi = compute(df, "rsi", length=self.length)["rsi"]
        prev = rsi.shift(1)
        entry = (prev <= self.oversold) & (rsi > self.oversold)
        exit_ = (prev >= self.overbought) & (rsi < self.overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
