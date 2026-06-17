# strategies package
from strategies.grid    import GridStrategy
from strategies.dca     import DCAStrategy
from strategies.pla     import PLAStrategy

# Indicator presets — single indicator
from strategies.rsi         import RSIStrategy
from strategies.macd        import MACDStrategy
from strategies.bollinger   import BollingerStrategy
from strategies.supertrend  import SupertrendStrategy
from strategies.donchian    import DonchianBreakoutStrategy
from strategies.macross     import MACrossStrategy

# Indicator presets — oscillators
from strategies.oscillators import (
    StochCrossStrategy, StochOBOSStrategy,
    CCIReversalStrategy, CCITrendStrategy,
    WilliamsRStrategy, ROCZeroStrategy,
    MomentumZeroStrategy, TSIZeroStrategy,
)

# Indicator presets — trend
from strategies.trend_indicators import (
    ADXTrendStrategy, DICrossStrategy, PSARFlipStrategy,
    AroonCrossStrategy, AroonOBOSStrategy,
)

# Indicator presets — moving average variants
from strategies.ma_variants import (
    SMACrossStrategy, WMACrossStrategy, HMACrossStrategy,
    TripleEMAStrategy, GoldenCrossStrategy,
)

# Indicator presets — volume
from strategies.volume_strats import (
    VWAPCrossStrategy, OBVTrendStrategy,
    MFIOBOSStrategy, CMFZeroStrategy,
)

# Indicator presets — breakout / volatility
from strategies.breakout_strats import (
    KeltnerBreakStrategy, ATRBreakoutStrategy, BBSqueezeStrategy,
)

# Combination (multi-indicator) strategies
from strategies.combos_rsi        import RSIMACDStrategy, RSIBBStrategy, RSIStochStrategy, RSIVolumeStrategy
from strategies.combos_macd       import MACDADXStrategy, MACDStochStrategy, MACDVolumeStrategy, MACDPSARStrategy
from strategies.combos_supertrend import STMACDStrategy, STRSIStrategy, STVolumeStrategy
from strategies.combos_multi      import (
    DCADXStrategy, BBRSIStrategy, VWAPRSIStrategy, VWAPMACDStrategy,
    ADXStochStrategy, KCRSIStrategy, AroonADXStrategy, MFICMFStrategy,
)

# Rule builder
from strategies.custom import CustomStrategy

STRATEGY_REGISTRY = {
    # ── Classic ──────────────────────────────────────────────────────────────
    "GRID": GridStrategy,
    "DCA":  DCAStrategy,
    "PLA":  PLAStrategy,

    # ── Indicator presets (original 6) ───────────────────────────────────────
    "RSI":        RSIStrategy,
    "MACD":       MACDStrategy,
    "BOLLINGER":  BollingerStrategy,
    "SUPERTREND": SupertrendStrategy,
    "DONCHIAN":   DonchianBreakoutStrategy,
    "MACROSS":    MACrossStrategy,

    # ── Oscillators (8) ──────────────────────────────────────────────────────
    "STOCH_CROSS": StochCrossStrategy,
    "STOCH_OBOS":  StochOBOSStrategy,
    "CCI_REV":     CCIReversalStrategy,
    "CCI_TREND":   CCITrendStrategy,
    "WILLIAMS":    WilliamsRStrategy,
    "ROC":         ROCZeroStrategy,
    "MOMENTUM":    MomentumZeroStrategy,
    "TSI":         TSIZeroStrategy,

    # ── Trend indicators (5) ─────────────────────────────────────────────────
    "ADX_TREND":   ADXTrendStrategy,
    "DI_CROSS":    DICrossStrategy,
    "PSAR":        PSARFlipStrategy,
    "AROON_CROSS": AroonCrossStrategy,
    "AROON_OBOS":  AroonOBOSStrategy,

    # ── Moving average variants (5) ──────────────────────────────────────────
    "SMA_CROSS":   SMACrossStrategy,
    "WMA_CROSS":   WMACrossStrategy,
    "HMA_CROSS":   HMACrossStrategy,
    "TRIPLE_EMA":  TripleEMAStrategy,
    "GOLDEN_CROSS":GoldenCrossStrategy,

    # ── Volume strategies (4) ────────────────────────────────────────────────
    "VWAP_CROSS": VWAPCrossStrategy,
    "OBV_TREND":  OBVTrendStrategy,
    "MFI_OBOS":   MFIOBOSStrategy,
    "CMF_ZERO":   CMFZeroStrategy,

    # ── Breakout / volatility (3) ────────────────────────────────────────────
    "KC_BREAK":    KeltnerBreakStrategy,
    "ATR_BREAK":   ATRBreakoutStrategy,
    "BB_SQUEEZE":  BBSqueezeStrategy,

    # ── RSI combos (4) ───────────────────────────────────────────────────────
    "RSI_MACD":   RSIMACDStrategy,
    "RSI_BB":     RSIBBStrategy,
    "RSI_STOCH":  RSIStochStrategy,
    "RSI_VOLUME": RSIVolumeStrategy,

    # ── MACD combos (4) ──────────────────────────────────────────────────────
    "MACD_ADX":    MACDADXStrategy,
    "MACD_STOCH":  MACDStochStrategy,
    "MACD_VOLUME": MACDVolumeStrategy,
    "MACD_PSAR":   MACDPSARStrategy,

    # ── Supertrend combos (3) ────────────────────────────────────────────────
    "ST_MACD":   STMACDStrategy,
    "ST_RSI":    STRSIStrategy,
    "ST_VOLUME": STVolumeStrategy,

    # ── Multi-indicator combos (8) ───────────────────────────────────────────
    "DC_ADX":    DCADXStrategy,
    "BB_RSI":    BBRSIStrategy,
    "VWAP_RSI":  VWAPRSIStrategy,
    "VWAP_MACD": VWAPMACDStrategy,
    "ADX_STOCH": ADXStochStrategy,
    "KC_RSI":    KCRSIStrategy,
    "AROON_ADX": AroonADXStrategy,
    "MFI_CMF":   MFICMFStrategy,

    # ── Rule builder ─────────────────────────────────────────────────────────
    "CUSTOM": CustomStrategy,
}

__all__ = list(STRATEGY_REGISTRY.keys()) + ["STRATEGY_REGISTRY"]
