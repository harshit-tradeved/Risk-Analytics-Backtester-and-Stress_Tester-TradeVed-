"""
Multi-indicator combination strategies — various indicator pairings.

Strategies: DC_ADX, BB_RSI, VWAP_RSI, VWAP_MACD, ADX_STOCH, KC_RSI,
            AROON_ADX, MFI_CMF
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


class DCADXStrategy(BaseStrategy):
    """Donchian Channel + ADX: buy Donchian upper breakout only when ADX confirms a strong trend."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "dc_length":     Param("number", "DC Length",      min=2, max=200, step=1, group="Donchian"),
            "adx_length":    Param("number", "ADX Length",     min=2, max=100, step=1, group="ADX"),
            "adx_threshold": Param("number", "ADX Min (trend)",min=10, max=50, step=1, group="ADX"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"dc_length": 20, "adx_length": 14, "adx_threshold": 25.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        dc   = compute(df, "donchian", length=self.dc_length)
        adx  = compute(df, "adx",     length=self.adx_length)["adx"]
        close = df["close"].astype(float)
        trending = adx > self.adx_threshold
        entry = (close >= dc["dc_upper"]) & trending
        exit_ = close <= dc["dc_lower"]
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class BBRSIStrategy(BaseStrategy):
    """Bollinger Bands + RSI: buy when price bounces off lower BB with RSI oversold; sell at upper BB."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "bb_length":     Param("number", "BB Length",     min=2,   max=200, step=1,   group="Bollinger"),
            "bb_std":        Param("number", "BB Std Dev",    min=0.5, max=5,   step=0.5, group="Bollinger"),
            "rsi_length":    Param("number", "RSI Length",    min=2,   max=100, step=1,   group="RSI"),
            "rsi_oversold":  Param("number", "RSI Oversold",  min=10,  max=50,  step=1,   group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought",min=50,  max=90,  step=1,   group="RSI"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"bb_length": 20, "bb_std": 2.0, "rsi_length": 14, "rsi_oversold": 35.0, "rsi_overbought": 65.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        bb    = compute(df, "bbands", length=self.bb_length, std=self.bb_std)
        rsi   = compute(df, "rsi",    length=self.rsi_length)["rsi"]
        close = df["close"].astype(float)
        entry = (close <= bb["bb_lower"]) & (rsi < self.rsi_oversold)
        exit_ = (close >= bb["bb_upper"]) | (rsi > self.rsi_overbought)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class VWAPRSIStrategy(BaseStrategy):
    """VWAP + RSI: buy when price crosses above VWAP AND RSI is not overbought; sell on VWAP cross down."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "vwap_length":   Param("number", "VWAP Length",   min=2, max=200, step=1, group="VWAP"),
            "rsi_length":    Param("number", "RSI Length",    min=2, max=100, step=1, group="RSI"),
            "rsi_overbought":Param("number", "RSI Overbought",min=50, max=90, step=1, group="RSI"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"vwap_length": 14, "rsi_length": 14, "rsi_overbought": 70.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        vwap  = compute(df, "vwap", length=self.vwap_length)["vwap"]
        rsi   = compute(df, "rsi",  length=self.rsi_length)["rsi"]
        close = df["close"].astype(float)
        above = close > vwap
        entry = above & ~above.shift(1).fillna(False) & (rsi < self.rsi_overbought)
        exit_ = ~above & above.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class VWAPMACDStrategy(BaseStrategy):
    """VWAP + MACD: buy on MACD bullish cross when price is above VWAP; sell on bearish MACD cross."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "vwap_length": Param("number", "VWAP Length",  min=2, max=200, step=1, group="VWAP"),
            "macd_fast":   Param("number", "MACD Fast",    min=2, max=100, step=1, group="MACD"),
            "macd_slow":   Param("number", "MACD Slow",    min=3, max=200, step=1, group="MACD"),
            "macd_signal": Param("number", "MACD Signal",  min=2, max=100, step=1, group="MACD"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"vwap_length": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        vwap  = compute(df, "vwap", length=self.vwap_length)["vwap"]
        m     = compute(df, "macd", fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        close = df["close"].astype(float)
        diff  = m["macd"] - m["macd_signal"]
        prev  = diff.shift(1)
        above_vwap = close > vwap
        entry = ((prev <= 0) & (diff > 0)) & above_vwap
        exit_ = (prev >= 0) & (diff < 0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class ADXStochStrategy(BaseStrategy):
    """ADX + Stochastic: buy when trend is strong (ADX > threshold) AND Stoch exits oversold."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "adx_length":     Param("number", "ADX Length",     min=2, max=100, step=1, group="ADX"),
            "adx_threshold":  Param("number", "ADX Min (trend)",min=10, max=50, step=1, group="ADX"),
            "stoch_k":        Param("number", "Stoch K",        min=2, max=100, step=1, group="Stochastic"),
            "stoch_oversold": Param("number", "Stoch Oversold", min=5, max=40,  step=1, group="Stochastic"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"adx_length": 14, "adx_threshold": 25.0, "stoch_k": 14, "stoch_oversold": 25.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        adx_ = compute(df, "adx",   length=self.adx_length)
        stch = compute(df, "stoch", k=self.stoch_k, d=3, smooth_k=3)
        trending = adx_["adx"] > self.adx_threshold
        bull_di  = adx_["plus_di"] > adx_["minus_di"]
        k_prev   = stch["stoch_k"].shift(1)
        entry    = trending & bull_di & (k_prev <= self.stoch_oversold) & (stch["stoch_k"] > self.stoch_oversold)
        exit_    = ~bull_di & bull_di.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class KCRSIStrategy(BaseStrategy):
    """Keltner Channel + RSI: buy on Keltner upper breakout when RSI confirms momentum; sell below lower KC."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "kc_length":  Param("number", "KC Length",     min=2,   max=200, step=1,   group="Keltner"),
            "kc_mult":    Param("number", "KC Multiplier", min=0.5, max=5,   step=0.5, group="Keltner"),
            "rsi_length": Param("number", "RSI Length",    min=2,   max=100, step=1,   group="RSI"),
            "rsi_min":    Param("number", "RSI Min (momentum)",min=40, max=70, step=1,  group="RSI"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"kc_length": 20, "kc_mult": 2.0, "rsi_length": 14, "rsi_min": 50.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        kc    = compute(df, "keltner", length=self.kc_length, multiplier=self.kc_mult)
        rsi   = compute(df, "rsi",     length=self.rsi_length)["rsi"]
        close = df["close"].astype(float)
        entry = (close > kc["kc_upper"]) & (rsi > self.rsi_min)
        exit_ = close < kc["kc_lower"]
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class AroonADXStrategy(BaseStrategy):
    """Aroon + ADX: buy when Aroon confirms an uptrend AND ADX shows the trend is strong."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "aroon_length":  Param("number", "Aroon Length",   min=2, max=200, step=1, group="Aroon"),
            "aroon_thresh":  Param("number", "Aroon Up Min",   min=50, max=95, step=5, group="Aroon"),
            "adx_length":    Param("number", "ADX Length",     min=2, max=100, step=1, group="ADX"),
            "adx_threshold": Param("number", "ADX Min (trend)",min=10, max=50, step=1, group="ADX"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"aroon_length": 25, "aroon_thresh": 70.0, "adx_length": 14, "adx_threshold": 20.0, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        ar   = compute(df, "aroon", length=self.aroon_length)
        adx  = compute(df, "adx",   length=self.adx_length)["adx"]
        lo   = 100 - self.aroon_thresh
        bull = (ar["aroon_up"] > self.aroon_thresh) & (ar["aroon_down"] < lo) & (adx > self.adx_threshold)
        entry = bull  & ~bull.shift(1).fillna(False)
        exit_ = ~bull & bull.shift(1).fillna(False)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))


class MFICMFStrategy(BaseStrategy):
    """MFI + CMF dual volume: buy when both MFI exits oversold AND CMF turns positive (dual money-flow agreement)."""
    CATEGORY = "indicator"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "mfi_length":   Param("number", "MFI Length",   min=2, max=100, step=1, group="Volume"),
            "mfi_oversold": Param("number", "MFI Oversold", min=5, max=40,  step=1, group="Volume"),
            "cmf_length":   Param("number", "CMF Length",   min=2, max=200, step=1, group="Volume"),
            **_sizing_params(),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {"mfi_length": 14, "mfi_oversold": 25.0, "cmf_length": 20, **_sizing_defaults()}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        mfi  = compute(df, "mfi", length=self.mfi_length)["mfi"]
        cmf  = compute(df, "cmf", length=self.cmf_length)["cmf"]
        mfi_prev = mfi.shift(1)
        entry = (mfi_prev <= self.mfi_oversold) & (mfi > self.mfi_oversold) & (cmf > 0)
        exit_ = (cmf < 0) & cmf.shift(1).fillna(0).ge(0)
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
