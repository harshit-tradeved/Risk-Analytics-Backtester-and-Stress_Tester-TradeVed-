"""
Supertrend combination strategies — Supertrend paired with MACD, RSI, or volume.

Strategies: ST_MACD, ST_RSI, ST_VOLUME
"""
from __future__ import annotations
from typing import Any
import pandas as pd
from engine.indicators import compute, ema
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


class STMACDStrategy(BaseStrategy):
    """Supertrend + MACD: buy when Supertrend turns bullish AND MACD histogram is positive."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "st_length":   Param("number", "ST Length",    min=2,   max=100, step=1,   group="Supertrend"),
            "st_mult":     Param("number", "ST Multiplier",min=0.5, max=10,  step=0.5, group="Supertrend"),
            "macd_fast":   Param("number", "MACD Fast",    min=2,   max=100, step=1,   group="MACD"),
            "macd_slow":   Param("number", "MACD Slow",    min=3,   max=200, step=1,   group="MACD"),
            "macd_signal": Param("number", "MACD Signal",  min=2,   max=100, step=1,   group="MACD"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "st_length": 10, "st_mult": 3.0,
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        st   = compute(df, "supertrend", length=self.st_length, multiplier=self.st_mult)
        m    = compute(df, "macd", fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        st_bull = st["supertrend_dir"] == 1
        macd_pos = m["macd_hist"] > 0
        # Entry: ST just turned bullish + MACD positive
        entry = st_bull & ~st_bull.shift(1).fillna(False) & macd_pos
        # Also enter if ST was already bullish and MACD just turned positive
        entry = entry | (st_bull & (m["macd_hist"].shift(1) <= 0) & macd_pos)
        exit_ = ~st_bull & st_bull.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class STRSIStrategy(BaseStrategy):
    """Supertrend + RSI: buy when Supertrend turns bullish AND RSI is not overbought."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "st_length":     Param("number", "ST Length",      min=2,   max=100, step=1,   group="Supertrend"),
            "st_mult":       Param("number", "ST Multiplier",  min=0.5, max=10,  step=0.5, group="Supertrend"),
            "rsi_length":    Param("number", "RSI Length",     min=2,   max=100, step=1,   group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought", min=50,  max=90,  step=1,   group="RSI"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "st_length": 10, "st_mult": 3.0,
            "rsi_length": 14, "rsi_overbought": 70.0,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        st  = compute(df, "supertrend", length=self.st_length, multiplier=self.st_mult)
        rsi = compute(df, "rsi",        length=self.rsi_length)["rsi"]
        st_bull  = st["supertrend_dir"] == 1
        not_ob   = rsi < self.rsi_overbought
        entry = st_bull & not_ob & ~(st_bull.shift(1).fillna(False) & not_ob.shift(1).fillna(True))
        exit_ = ~st_bull & st_bull.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class STVolumeStrategy(BaseStrategy):
    """Supertrend + CMF volume: buy when Supertrend turns bullish AND CMF confirms inflow (> 0)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "st_length":  Param("number", "ST Length",    min=2,   max=100, step=1,   group="Supertrend"),
            "st_mult":    Param("number", "ST Multiplier",min=0.5, max=10,  step=0.5, group="Supertrend"),
            "cmf_length": Param("number", "CMF Length",   min=2,   max=200, step=1,   group="Volume"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "st_length": 10, "st_mult": 3.0,
            "cmf_length": 20,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        st  = compute(df, "supertrend", length=self.st_length, multiplier=self.st_mult)
        cmf = compute(df, "cmf",        length=self.cmf_length)["cmf"]
        st_bull = st["supertrend_dir"] == 1
        flow_in = cmf > 0
        entry = st_bull & flow_in & ~(st_bull.shift(1).fillna(False) & flow_in.shift(1).fillna(True))
        exit_ = ~st_bull & st_bull.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
