"""
Oscillator strategies — momentum oscillators beyond RSI/MACD.

Strategies: STOCH_CROSS, STOCH_OBOS, CCI_REV, CCI_TREND,
            WILLIAMS, ROC, MOMENTUM, TSI
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from engine.indicators import compute
from strategies.base import BaseStrategy, Param, signals_from_masks


def _sizing_params():
    return {
        "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                      help="Set 0 to use fixed units."),
        "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                      depends_on={"field": "invest_per_trade_usd", "value": 0}),
    }


def _sizing_defaults():
    return {"invest_per_trade_usd": 1000.0, "quantity": 0.01}


class StochCrossStrategy(BaseStrategy):
    """Stochastic K/D cross: buy when K crosses above D, sell when K crosses below."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "k":     Param("number", "K Period",      min=2, max=100, step=1, group="Signal"),
            "d":     Param("number", "D Period",      min=1, max=50,  step=1, group="Signal"),
            "smooth_k": Param("number", "Smooth K",   min=1, max=20,  step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"k": 14, "d": 3, "smooth_k": 3, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        s = compute(df, "stoch", k=self.k, d=self.d, smooth_k=self.smooth_k)
        diff  = s["stoch_k"] - s["stoch_d"]
        prev  = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class StochOBOSStrategy(BaseStrategy):
    """Stochastic overbought/oversold: buy K exits oversold, sell K exits overbought."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "k":         Param("number", "K Period",   min=2, max=100, step=1, group="Signal"),
            "d":         Param("number", "D Period",   min=1, max=50,  step=1, group="Signal"),
            "smooth_k":  Param("number", "Smooth K",   min=1, max=20,  step=1, group="Signal"),
            "oversold":  Param("number", "Oversold",   min=1, max=40,  step=1, group="Signal"),
            "overbought":Param("number", "Overbought", min=60, max=99, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"k": 14, "d": 3, "smooth_k": 3, "oversold": 20.0, "overbought": 80.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        s    = compute(df, "stoch", k=self.k, d=self.d, smooth_k=self.smooth_k)
        k    = s["stoch_k"]
        prev = k.shift(1)
        entry = (prev <= self.oversold)  & (k > self.oversold)
        exit_ = (prev >= self.overbought) & (k < self.overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class CCIReversalStrategy(BaseStrategy):
    """CCI mean-reversion: buy exiting oversold (<-100), sell exiting overbought (>+100)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":    Param("number", "CCI Length",  min=2, max=200, step=1, group="Signal"),
            "oversold":  Param("number", "Oversold",    min=-300, max=-50, step=5, group="Signal"),
            "overbought":Param("number", "Overbought",  min=50, max=300,  step=5, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 20, "oversold": -100.0, "overbought": 100.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        cci  = compute(df, "cci", length=self.length)["cci"]
        prev = cci.shift(1)
        entry = (prev <= self.oversold)  & (cci > self.oversold)
        exit_ = (prev >= self.overbought) & (cci < self.overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class CCITrendStrategy(BaseStrategy):
    """CCI trend-following: buy CCI crosses above zero, sell CCI crosses below zero."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "CCI Length", min=2, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 20, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        cci  = compute(df, "cci", length=self.length)["cci"]
        prev = cci.shift(1)
        entry = (prev <= 0) & (cci > 0)
        exit_ = (prev >= 0) & (cci < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class WilliamsRStrategy(BaseStrategy):
    """Williams %R: buy exiting oversold (< -80), sell exiting overbought (> -20)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":    Param("number", "Lookback", min=2, max=100, step=1, group="Signal"),
            "oversold":  Param("number", "Oversold",  min=-99, max=-60, step=1, group="Signal"),
            "overbought":Param("number", "Overbought",min=-40, max=-1,  step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 14, "oversold": -80.0, "overbought": -20.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        wr   = compute(df, "willr", length=self.length)["willr"]
        prev = wr.shift(1)
        entry = (prev <= self.oversold)  & (wr > self.oversold)
        exit_ = (prev >= self.overbought) & (wr < self.overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class ROCZeroStrategy(BaseStrategy):
    """Rate of Change zero-cross: buy ROC turns positive, sell ROC turns negative."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "ROC Length", min=1, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 12, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        roc  = compute(df, "roc", length=self.length)["roc"]
        prev = roc.shift(1)
        entry = (prev <= 0) & (roc > 0)
        exit_ = (prev >= 0) & (roc < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class MomentumZeroStrategy(BaseStrategy):
    """Momentum zero-cross: buy when price momentum turns positive, sell when negative."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "Momentum Length", min=1, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 10, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        mom  = compute(df, "mom", length=self.length)["mom"]
        prev = mom.shift(1)
        entry = (prev <= 0) & (mom > 0)
        exit_ = (prev >= 0) & (mom < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class TSIZeroStrategy(BaseStrategy):
    """True Strength Index zero-cross: buy TSI turns positive, sell turns negative."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast": Param("number", "Fast Period", min=2, max=100, step=1, group="Signal"),
            "slow": Param("number", "Slow Period", min=3, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"fast": 13, "slow": 25, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        tsi  = compute(df, "tsi", fast=self.fast, slow=self.slow)["tsi"]
        prev = tsi.shift(1)
        entry = (prev <= 0) & (tsi > 0)
        exit_ = (prev >= 0) & (tsi < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
