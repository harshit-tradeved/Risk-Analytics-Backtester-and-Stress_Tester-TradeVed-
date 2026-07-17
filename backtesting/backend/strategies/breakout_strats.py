"""
Breakout / volatility strategies — Keltner breakout, ATR breakout, Bollinger squeeze.

Strategies: KC_BREAK, ATR_BREAK, BB_SQUEEZE
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from backtesting.backend.engine.indicators import compute, sma
from backtesting.backend.strategies.base import BaseStrategy, Param, signals_from_masks


def _sizing_params():
    return {
        "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                      help="Set 0 to use fixed units."),
        "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                      depends_on={"field": "invest_per_trade_usd", "value": 0}),
    }


def _sizing_defaults():
    return {"invest_per_trade_usd": 1000.0, "quantity": 0.01}


class KeltnerBreakStrategy(BaseStrategy):
    """Keltner Channel breakout: buy when price closes above upper channel, sell below lower."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":     Param("number", "KC Length",     min=2, max=200, step=1,   group="Signal"),
            "multiplier": Param("number", "ATR Multiplier", min=0.5, max=5, step=0.5, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 20, "multiplier": 2.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        kc    = compute(df, "keltner", length=self.length, multiplier=self.multiplier)
        close = df["close"].astype(float)
        entry = close > kc["kc_upper"]
        exit_ = close < kc["kc_lower"]
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class ATRBreakoutStrategy(BaseStrategy):
    """ATR Breakout: buy when price moves N×ATR above the rolling high, sell on N×ATR reversal."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "atr_length":    Param("number", "ATR Length",       min=2,  max=100, step=1,   group="Signal"),
            "lookback":      Param("number", "High Lookback",     min=2,  max=100, step=1,   group="Signal"),
            "atr_multiplier":Param("number", "ATR Multiplier",    min=0.5, max=5,  step=0.5, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"atr_length": 14, "lookback": 20, "atr_multiplier": 1.5, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        atr   = compute(df, "atr", length=self.atr_length)["atr"]
        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        roll_high = high.rolling(int(self.lookback), min_periods=int(self.lookback)).max()
        breakout_level = roll_high + self.atr_multiplier * atr
        entry = close > breakout_level
        # Exit: close falls below the rolling high (failed breakout)
        exit_ = close < roll_high.shift(1)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class BBSqueezeStrategy(BaseStrategy):
    """Bollinger Squeeze: buy when BB width expands after a squeeze (BB inside Keltner), sell when width contracts again."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":      Param("number", "BB/KC Length",   min=2, max=200, step=1,   group="Signal"),
            "bb_std":      Param("number", "BB Std Dev",     min=0.5, max=5, step=0.5,  group="Signal"),
            "kc_mult":     Param("number", "KC Multiplier",  min=0.5, max=5, step=0.5,  group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 20, "bb_std": 2.0, "kc_mult": 1.5, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        bb   = compute(df, "bbands",  length=self.length, std=self.bb_std)
        kc   = compute(df, "keltner", length=self.length, multiplier=self.kc_mult)
        # Squeeze: BB entirely inside Keltner Channel
        squeeze = (bb["bb_lower"] > kc["kc_lower"]) & (bb["bb_upper"] < kc["kc_upper"])
        # Release: BB width expands past Keltner width (squeeze ends and momentum fires)
        bb_w = bb["bb_upper"] - bb["bb_lower"]
        kc_w = kc["kc_upper"] - kc["kc_lower"]
        expanding = bb_w > kc_w
        # Buy when squeeze releases upward: price above midline and expansion just started
        close = df["close"].astype(float)
        mid   = bb["bb_mid"]
        was_squeeze = squeeze.shift(1).fillna(False)
        entry = was_squeeze & expanding & (close > mid)
        exit_ = was_squeeze & expanding & (close < mid)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
