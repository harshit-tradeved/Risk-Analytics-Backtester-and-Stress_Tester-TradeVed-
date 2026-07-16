"""
RSI combination strategies — RSI paired with MACD, Bollinger, Stochastic, or OBV.

Strategies: RSI_MACD, RSI_BB, RSI_STOCH, RSI_VOLUME
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


class RSIMACDStrategy(BaseStrategy):
    """RSI + MACD: buy when RSI is oversold AND MACD turns bullish; sell on RSI overbought OR MACD bearish cross."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "rsi_length":    Param("number", "RSI Length",    min=2,  max=100, step=1, group="RSI"),
            "rsi_oversold":  Param("number", "RSI Oversold",  min=10, max=50,  step=1, group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought",min=50, max=90,  step=1, group="RSI"),
            "macd_fast":     Param("number", "MACD Fast",     min=2,  max=100, step=1, group="MACD"),
            "macd_slow":     Param("number", "MACD Slow",     min=3,  max=200, step=1, group="MACD"),
            "macd_signal":   Param("number", "MACD Signal",   min=2,  max=100, step=1, group="MACD"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "rsi_length": 14, "rsi_oversold": 35.0, "rsi_overbought": 65.0,
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        rsi = compute(df, "rsi",  length=self.rsi_length)["rsi"]
        m   = compute(df, "macd", fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        diff = m["macd"] - m["macd_signal"]
        prev_diff = diff.shift(1)
        macd_bull = (prev_diff <= 0) & (diff > 0)
        entry = (rsi < self.rsi_oversold) & macd_bull
        exit_ = (rsi > self.rsi_overbought) | ((prev_diff >= 0) & (diff < 0))
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class RSIBBStrategy(BaseStrategy):
    """RSI + Bollinger Bands: buy when RSI oversold AND price touches lower BB; sell on RSI overbought OR upper BB."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "rsi_length":    Param("number", "RSI Length",    min=2,  max=100, step=1,   group="RSI"),
            "rsi_oversold":  Param("number", "RSI Oversold",  min=10, max=50,  step=1,   group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought",min=50, max=90,  step=1,   group="RSI"),
            "bb_length":     Param("number", "BB Length",     min=2,  max=200, step=1,   group="Bollinger"),
            "bb_std":        Param("number", "BB Std Dev",    min=0.5, max=5,  step=0.5, group="Bollinger"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "rsi_length": 14, "rsi_oversold": 35.0, "rsi_overbought": 65.0,
            "bb_length": 20, "bb_std": 2.0,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        rsi   = compute(df, "rsi",    length=self.rsi_length)["rsi"]
        bb    = compute(df, "bbands", length=self.bb_length, std=self.bb_std)
        close = df["close"].astype(float)
        entry = (rsi < self.rsi_oversold)  & (close <= bb["bb_lower"])
        exit_ = (rsi > self.rsi_overbought) | (close >= bb["bb_upper"])
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class RSIStochStrategy(BaseStrategy):
    """RSI + Stochastic agreement: buy when both RSI and Stoch K are oversold; sell when both overbought."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "rsi_length":    Param("number", "RSI Length",    min=2, max=100, step=1, group="RSI"),
            "rsi_oversold":  Param("number", "RSI Oversold",  min=10, max=50, step=1, group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought",min=50, max=90, step=1, group="RSI"),
            "stoch_k":       Param("number", "Stoch K",       min=2, max=100, step=1, group="Stochastic"),
            "stoch_d":       Param("number", "Stoch D",       min=1, max=20,  step=1, group="Stochastic"),
            "stoch_oversold":Param("number", "Stoch Oversold",min=5, max=40,  step=1, group="Stochastic"),
            "stoch_overbought":Param("number","Stoch Overbought",min=60,max=95,step=1,group="Stochastic"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "rsi_length": 14, "rsi_oversold": 35.0, "rsi_overbought": 65.0,
            "stoch_k": 14, "stoch_d": 3, "stoch_oversold": 20.0, "stoch_overbought": 80.0,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        rsi  = compute(df, "rsi",   length=self.rsi_length)["rsi"]
        stch = compute(df, "stoch", k=self.stoch_k, d=self.stoch_d, smooth_k=3)
        k    = stch["stoch_k"]
        entry = (rsi < self.rsi_oversold)   & (k < self.stoch_oversold)
        exit_ = (rsi > self.rsi_overbought)  | (k > self.stoch_overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class RSIVolumeStrategy(BaseStrategy):
    """RSI + OBV: buy when RSI oversold AND OBV is rising (accumulation); sell when RSI overbought."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "rsi_length":    Param("number", "RSI Length",    min=2, max=100, step=1, group="RSI"),
            "rsi_oversold":  Param("number", "RSI Oversold",  min=10, max=50, step=1, group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought",min=50, max=90, step=1, group="RSI"),
            "obv_ema_length":Param("number", "OBV EMA Length",min=2, max=100, step=1, group="Volume"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "rsi_length": 14, "rsi_oversold": 35.0, "rsi_overbought": 65.0,
            "obv_ema_length": 20,
            **_sizing_defaults(),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        rsi      = compute(df, "rsi", length=self.rsi_length)["rsi"]
        obv      = compute(df, "obv")["obv"]
        obv_ema_ = ema(obv, int(self.obv_ema_length))
        obv_bull = obv > obv_ema_
        entry = (rsi < self.rsi_oversold)  & obv_bull
        exit_ = (rsi > self.rsi_overbought) | ~obv_bull
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
