"""
Bollinger Bands Strategy — mean reversion on band touches.

Logic:
  BUY  when close crosses back UP through the lower band (oversold bounce).
  SELL when close crosses UP through the middle band (mean) or hits the upper band.
Long-only; full-position entry/exit.

Parameters:
  length / std         : Bollinger period and std-dev multiplier (20 / 2.0)
  exit_at              : 'mid' | 'upper' — where to take profit
  invest_per_trade_usd : USD per entry (0 → fixed units)
  quantity             : fixed units fallback
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from backtesting.engine.indicators import compute
from backtesting.strategies.base import BaseStrategy, Param, signals_from_masks


class BollingerStrategy(BaseStrategy):
    """Bollinger mean-reversion: buy lower-band bounce, sell at mid/upper band."""

    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":               Param("number", "BB Length", min=2, max=200, step=1, group="Signal"),
            "std":                  Param("number", "Std Dev", min=0.5, max=5, step=0.5, group="Signal"),
            "exit_at":              Param("select", "Exit At", options=["mid", "upper"], group="Exit"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "length":               20,
            "std":                  2.0,
            "exit_at":              "mid",
            "invest_per_trade_usd": 1000.0,
            "quantity":             0.01,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        bb = compute(df, "bbands", length=self.length, std=self.std)
        close = df["close"].astype(float)
        prev_c = close.shift(1)
        # Entry: price was below lower band, now back above it
        entry = (prev_c < bb["bb_lower"].shift(1)) & (close >= bb["bb_lower"])
        exit_band = bb["bb_upper"] if self.exit_at == "upper" else bb["bb_mid"]
        exit_ = (prev_c < exit_band.shift(1)) & (close >= exit_band)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
