"""
Volume-based strategies — VWAP, OBV, MFI, CMF.

Strategies: VWAP_CROSS, OBV_TREND, MFI_OBOS, CMF_ZERO
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from backtesting.engine.indicators import compute, ema
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


class VWAPCrossStrategy(BaseStrategy):
    """VWAP Cross: buy when price crosses above VWAP, sell when price crosses below VWAP."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "VWAP Length", min=2, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 14, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        vwap  = compute(df, "vwap", length=self.length)["vwap"]
        close = df["close"].astype(float)
        diff  = close - vwap
        prev  = diff.shift(1)
        entry = (prev <= 0) & (diff > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class OBVTrendStrategy(BaseStrategy):
    """OBV Trend: buy when OBV crosses above its EMA (rising accumulation), sell when below."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "ema_length": Param("number", "OBV EMA Length", min=2, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"ema_length": 20, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        obv      = compute(df, "obv")["obv"]
        obv_ema  = ema(obv, int(self.ema_length))
        diff     = obv - obv_ema
        prev     = diff.shift(1)
        entry    = (prev <= 0) & (diff > 0)
        exit_    = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class MFIOBOSStrategy(BaseStrategy):
    """Money Flow Index overbought/oversold: buy exiting oversold (<20), sell exiting overbought (>80)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length":     Param("number", "MFI Length",  min=2, max=100, step=1, group="Signal"),
            "oversold":   Param("number", "Oversold",    min=1, max=40,  step=1, group="Signal"),
            "overbought": Param("number", "Overbought",  min=60, max=99, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 14, "oversold": 20.0, "overbought": 80.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        mfi  = compute(df, "mfi", length=self.length)["mfi"]
        prev = mfi.shift(1)
        entry = (prev <= self.oversold)  & (mfi > self.oversold)
        exit_ = (prev >= self.overbought) & (mfi < self.overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class CMFZeroStrategy(BaseStrategy):
    """Chaikin Money Flow zero-cross: buy CMF crosses above zero (money inflow), sell when below."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "length": Param("number", "CMF Length", min=2, max=200, step=1, group="Signal"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"length": 20, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        cmf  = compute(df, "cmf", length=self.length)["cmf"]
        prev = cmf.shift(1)
        entry = (prev <= 0) & (cmf > 0)
        exit_ = (prev >= 0) & (cmf < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
