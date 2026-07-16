"""
MACD combination strategies — MACD paired with ADX, Stochastic, CMF volume, or PSAR.

Strategies: MACD_ADX, MACD_STOCH, MACD_VOLUME, MACD_PSAR
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


class MACDADXStrategy(BaseStrategy):
    """MACD + ADX: buy on MACD bullish cross when ADX shows strong trend (> threshold)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "macd_fast":      Param("number", "MACD Fast",      min=2, max=100, step=1,  group="MACD"),
            "macd_slow":      Param("number", "MACD Slow",      min=3, max=200, step=1,  group="MACD"),
            "macd_signal":    Param("number", "MACD Signal",    min=2, max=100, step=1,  group="MACD"),
            "adx_length":     Param("number", "ADX Length",     min=2, max=100, step=1,  group="ADX"),
            "adx_threshold":  Param("number", "ADX Min (trend)",min=10, max=50, step=1,  group="ADX"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "adx_length": 14, "adx_threshold": 20.0,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        m    = compute(df, "macd", fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        adx  = compute(df, "adx",  length=self.adx_length)["adx"]
        diff = m["macd"] - m["macd_signal"]
        prev = diff.shift(1)
        trending = adx > self.adx_threshold
        entry = ((prev <= 0) & (diff > 0)) & trending
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class MACDStochStrategy(BaseStrategy):
    """MACD + Stochastic: buy when MACD turns bullish AND Stoch is below oversold level."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "macd_fast":      Param("number", "MACD Fast",     min=2, max=100, step=1, group="MACD"),
            "macd_slow":      Param("number", "MACD Slow",     min=3, max=200, step=1, group="MACD"),
            "macd_signal":    Param("number", "MACD Signal",   min=2, max=100, step=1, group="MACD"),
            "stoch_k":        Param("number", "Stoch K",       min=2, max=100, step=1, group="Stochastic"),
            "stoch_oversold": Param("number", "Stoch Oversold",min=5, max=50,  step=1, group="Stochastic"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "stoch_k": 14, "stoch_oversold": 30.0,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        m    = compute(df, "macd",  fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        stch = compute(df, "stoch", k=self.stoch_k, d=3, smooth_k=3)
        diff = m["macd"] - m["macd_signal"]
        prev = diff.shift(1)
        entry = ((prev <= 0) & (diff > 0)) & (stch["stoch_k"] < self.stoch_oversold)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class MACDVolumeStrategy(BaseStrategy):
    """MACD + CMF volume: buy on MACD bullish cross confirmed by positive Chaikin Money Flow."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "macd_fast":   Param("number", "MACD Fast",   min=2, max=100, step=1, group="MACD"),
            "macd_slow":   Param("number", "MACD Slow",   min=3, max=200, step=1, group="MACD"),
            "macd_signal": Param("number", "MACD Signal", min=2, max=100, step=1, group="MACD"),
            "cmf_length":  Param("number", "CMF Length",  min=2, max=200, step=1, group="Volume"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "cmf_length": 20,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        m    = compute(df, "macd", fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        cmf  = compute(df, "cmf",  length=self.cmf_length)["cmf"]
        diff = m["macd"] - m["macd_signal"]
        prev = diff.shift(1)
        entry = ((prev <= 0) & (diff > 0)) & (cmf > 0)
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class MACDPSARStrategy(BaseStrategy):
    """MACD + PSAR: buy when MACD bullish AND PSAR is bullish (price above PSAR); sell on either bearish flip."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "macd_fast":   Param("number", "MACD Fast",   min=2,   max=100, step=1,   group="MACD"),
            "macd_slow":   Param("number", "MACD Slow",   min=3,   max=200, step=1,   group="MACD"),
            "macd_signal": Param("number", "MACD Signal", min=2,   max=100, step=1,   group="MACD"),
            "psar_step":   Param("number", "PSAR Step",   min=0.001, max=0.2, step=0.001, group="PSAR"),
            "psar_max":    Param("number", "PSAR Max AF", min=0.05, max=1.0, step=0.05,  group="PSAR"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "psar_step": 0.02, "psar_max": 0.2,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        m     = compute(df, "macd", fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        psar  = compute(df, "psar", step=self.psar_step, max_step=self.psar_max)["psar"]
        close = df["close"].astype(float)
        diff  = m["macd"] - m["macd_signal"]
        prev  = diff.shift(1)
        psar_bull = close > psar
        entry = ((prev <= 0) & (diff > 0)) & psar_bull
        exit_ = ((prev >= 0) & (diff < 0)) | (~psar_bull & psar_bull.shift(1).fillna(False))
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
