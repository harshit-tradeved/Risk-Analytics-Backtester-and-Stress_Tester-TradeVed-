"""
Donchian Breakout Strategy — channel breakout trend following.

Logic:
  BUY  when close breaks ABOVE the prior N-period high (upper channel).
  SELL when close breaks BELOW the prior M-period low (lower channel exit).
Long-only; full-position entry/exit. Classic Turtle-style breakout.

Parameters:
  entry_length         : breakout lookback for entries (default 20)
  exit_length          : breakdown lookback for exits (default 10)
  invest_per_trade_usd : USD per entry (0 → fixed units)
  quantity             : fixed units fallback
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from backtesting.engine.indicators import compute
from backtesting.strategies.base import BaseStrategy, Param, signals_from_masks


class DonchianBreakoutStrategy(BaseStrategy):
    """Donchian channel breakout: buy N-high breakout, sell M-low breakdown."""

    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "entry_length":         Param("number", "Entry Lookback", min=2, max=200, step=1, group="Signal"),
            "exit_length":          Param("number", "Exit Lookback", min=2, max=200, step=1, group="Signal"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "entry_length":         20,
            "exit_length":          10,
            "invest_per_trade_usd": 1000.0,
            "quantity":             0.01,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        # Prior-period extremes (shift(1) so the current candle's own high/low
        # don't define the channel it must break).
        up = compute(df, "donchian", length=self.entry_length)["dc_upper"].shift(1)
        dn = compute(df, "donchian", length=self.exit_length)["dc_lower"].shift(1)
        entry = close > up
        exit_ = close < dn
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
