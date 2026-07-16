"""
Trend indicator strategies — ADX, PSAR, Aroon.

Strategies: ADX_TREND, DI_CROSS, PSAR_FLIP, AROON_CROSS, AROON_OBOS
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from backtesting.engine.indicators import compute
from backtesting.strategies.base import BaseStrategy, Param, signals_from_masks


def _sizing_params():
    return {
        "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                      help="Set 0 to use fixed units."),
        "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                      depends_on={"field": "invest_per_trade_usd", "value": 0}),
    }


def _sizing_defaults():
    return {"invest_per_trade_usd": 1000.0, "quantity": 0.01}


class ADXTrendStrategy(BaseStrategy):
    """ADX Trend: buy when ADX > threshold AND +DI > -DI; sell when ADX weakens or -DI > +DI."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":        Param("number", "ADX Length",     min=2, max=100, step=1,  group="Signal"),
            "adx_threshold": Param("number", "ADX Min (trend)", min=10, max=50, step=1, group="Signal",
                                   help="ADX must exceed this to enter."),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 14, "adx_threshold": 25.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        a    = compute(df, "adx", length=self.length)
        adx  = a["adx"]
        pdi  = a["plus_di"]
        mdi  = a["minus_di"]
        strong = adx > self.adx_threshold
        entry  = strong & (pdi > mdi) & ~(pdi.shift(1) > mdi.shift(1))
        exit_  = (pdi < mdi) & (pdi.shift(1) >= mdi.shift(1))
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class DICrossStrategy(BaseStrategy):
    """+DI/-DI crossover: buy when +DI crosses above -DI, sell when -DI crosses above +DI."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "DI Length", min=2, max=100, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 14, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        a    = compute(df, "adx", length=self.length)
        pdi, mdi = a["plus_di"], a["minus_di"]
        diff = pdi - mdi
        prev = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class PSARFlipStrategy(BaseStrategy):
    """Parabolic SAR flip: buy when price crosses above PSAR (PSAR flips bullish), sell when bearish flip."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "step":     Param("number", "AF Step",    min=0.001, max=0.2, step=0.001, group="Signal"),
            "max_step": Param("number", "AF Max",     min=0.05,  max=1.0, step=0.05,  group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"step": 0.02, "max_step": 0.2, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        psar  = compute(df, "psar", step=self.step, max_step=self.max_step)["psar"]
        close = df["close"].astype(float)
        bull  = close > psar                     # price above PSAR → bullish
        entry = bull  & ~bull.shift(1).fillna(False)
        exit_ = ~bull & bull.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class AroonCrossStrategy(BaseStrategy):
    """Aroon crossover: buy when Aroon-Up crosses above Aroon-Down, sell when opposite."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "Aroon Length", min=2, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 25, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        a    = compute(df, "aroon", length=self.length)
        diff = a["aroon_up"] - a["aroon_down"]
        prev = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class AroonOBOSStrategy(BaseStrategy):
    """Aroon trend strength: buy when Aroon-Up > threshold AND Aroon-Down < (100-threshold)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":    Param("number", "Aroon Length",  min=2,  max=200, step=1,  group="Signal"),
            "threshold": Param("number", "Up Threshold",  min=50, max=95,  step=5,  group="Signal",
                               help="Aroon-Up must exceed this (and Aroon-Down must be below 100-threshold) to enter."),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 25, "threshold": 70.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        a     = compute(df, "aroon", length=self.length)
        up    = a["aroon_up"]
        down  = a["aroon_down"]
        lo    = 100 - self.threshold
        bull  = (up > self.threshold) & (down < lo)
        entry = bull  & ~bull.shift(1).fillna(False)
        exit_ = ~bull & bull.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
