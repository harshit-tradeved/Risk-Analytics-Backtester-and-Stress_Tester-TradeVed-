"""
Moving average variant strategies — SMA, WMA, HMA, Triple EMA, Golden Cross.

Strategies: SMA_CROSS, WMA_CROSS, HMA_CROSS, TRIPLE_EMA, GOLDEN_CROSS
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from backtesting.engine.indicators import compute, ema, sma
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


class SMACrossStrategy(BaseStrategy):
    """Simple Moving Average crossover: buy fast SMA crosses above slow SMA."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast": Param("number", "Fast SMA", min=2, max=200, step=1, group="Signal"),
            "slow": Param("number", "Slow SMA", min=3, max=400, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"fast": 10, "slow": 30, **_sizing_defaults()}

    def _validate_params(self, params):
        if params["fast"] >= params["slow"]:
            raise ValueError("fast must be < slow")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        fast_ = compute(df, "sma", length=self.fast)["sma"]
        slow_ = compute(df, "sma", length=self.slow)["sma"]
        diff  = fast_ - slow_
        prev  = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class WMACrossStrategy(BaseStrategy):
    """Weighted Moving Average crossover: buy fast WMA crosses above slow WMA."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast": Param("number", "Fast WMA", min=2, max=200, step=1, group="Signal"),
            "slow": Param("number", "Slow WMA", min=3, max=400, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"fast": 10, "slow": 30, **_sizing_defaults()}

    def _validate_params(self, params):
        if params["fast"] >= params["slow"]:
            raise ValueError("fast must be < slow")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        fast_ = compute(df, "wma", length=self.fast)["wma"]
        slow_ = compute(df, "wma", length=self.slow)["wma"]
        diff  = fast_ - slow_
        prev  = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class HMACrossStrategy(BaseStrategy):
    """Hull Moving Average crossover: buy fast HMA crosses above slow HMA."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast": Param("number", "Fast HMA", min=2, max=200, step=1, group="Signal"),
            "slow": Param("number", "Slow HMA", min=3, max=400, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"fast": 9, "slow": 25, **_sizing_defaults()}

    def _validate_params(self, params):
        if params["fast"] >= params["slow"]:
            raise ValueError("fast must be < slow")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        fast_ = compute(df, "hma", length=self.fast)["hma"]
        slow_ = compute(df, "hma", length=self.slow)["hma"]
        diff  = fast_ - slow_
        prev  = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class TripleEMAStrategy(BaseStrategy):
    """Triple EMA alignment: buy when fast > mid > slow (full bull alignment), sell when fast < slow."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast": Param("number", "Fast EMA",   min=2,  max=100, step=1, group="Signal"),
            "mid":  Param("number", "Mid EMA",    min=5,  max=200, step=1, group="Signal"),
            "slow": Param("number", "Slow EMA",   min=10, max=400, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"fast": 5, "mid": 13, "slow": 34, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        fast_ = ema(close, int(self.fast))
        mid_  = ema(close, int(self.mid))
        slow_ = ema(close, int(self.slow))
        bull  = (fast_ > mid_) & (mid_ > slow_)
        entry = bull & ~bull.shift(1).fillna(False)
        exit_ = (fast_ < slow_) & (fast_.shift(1) >= slow_.shift(1))
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class GoldenCrossStrategy(BaseStrategy):
    """Golden/Death Cross: buy SMA-50 crosses above SMA-200 (Golden), sell crosses below (Death)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast": Param("number", "Fast SMA", min=10, max=100,  step=1, group="Signal"),
            "slow": Param("number", "Slow SMA", min=50, max=400,  step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"fast": 50, "slow": 200, **_sizing_defaults()}

    def _validate_params(self, params):
        if params["fast"] >= params["slow"]:
            raise ValueError("fast must be < slow")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        fast_ = compute(df, "sma", length=self.fast)["sma"]
        slow_ = compute(df, "sma", length=self.slow)["sma"]
        diff  = fast_ - slow_
        prev  = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)   # golden cross
        exit_ = (prev >= 0) & (diff < 0)   # death cross
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
