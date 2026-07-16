"""
Market Regime Detection + Per-Regime Metrics
============================================

Classifies each candle as bull / bear / sideways using a moving-average
trend + slope approach, then computes condensed performance metrics for
each regime so retail traders can see whether a strategy worked across
different market conditions or only in one type of environment.

Detection method: MA-trend + slope confirmation (timeframe-aware)
------------------------------------------------------------------
  cpd     = candles per trading day (derived from timestamp spacing)
  long_w  = clamp(len(df)/cpd/5, 10d, 60d) × cpd   # ~1/5 dataset in trading days
  short_w = max(2d, long_w/3) × cpd

  eps = k * rolling_stdev(close_returns)   # volatility-relative threshold

  bull     : close > long_ma AND short_ma > long_ma AND slope > +eps
  bear     : close < long_ma AND short_ma < long_ma AND slope < -eps
  sideways : everything else (chop / transition / warmup)

Why slope confirmation?  Pure MA crossover labels every candle above the
200-day as "bull", even during a flat range.  The slope filter removes
low-momentum periods so the labels match what traders intuitively call
"a trend".
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backtesting.engine.metrics import _candles_per_day, _trade_statistics

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
REGIMES = ("bull", "bear", "sideways")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def classify_regimes(df: pd.DataFrame) -> list[str]:
    """
    Return one regime label per candle aligned 1:1 with the OHLCV DataFrame.

    Args:
        df: OHLCV DataFrame with a 'close' column (from data/fetcher.py).

    Returns:
        list[str] of length len(df), each element is 'bull', 'bear', or
        'sideways'.
    """
    n = len(df)
    if n == 0:
        return []

    close = df["close"].astype(float).values

    # ── Timeframe-aware MA windows (real trading-day units, then → candles) ────
    cpd        = _candles_per_day(df["timestamp"].tolist()) if "timestamp" in df.columns else 1.0
    long_days  = float(np.clip(n / cpd / 5, 10, 60))
    short_days = max(2.0, long_days / 3)
    long_w     = max(2, round(long_days  * cpd))
    short_w    = max(2, round(short_days * cpd))

    logger.debug(
        "Regime detection: n=%d  cpd=%.1f  long_days=%.1f  long_w=%d  short_w=%d",
        n, cpd, long_days, long_w, short_w,
    )

    # ── Moving averages ───────────────────────────────────────────────────────
    close_s  = pd.Series(close)
    long_ma  = close_s.rolling(long_w,  min_periods=long_w).mean().values
    short_ma = close_s.rolling(short_w, min_periods=short_w).mean().values

    # ── Slope: short_ma pct-change over short_w candles ──────────────────────
    short_ma_s = pd.Series(short_ma)
    slope      = short_ma_s.pct_change(periods=short_w).values

    # ── Volatility-relative threshold: eps = 0.3 × rolling stdev of returns ─
    returns = close_s.pct_change().values
    rv      = pd.Series(returns).rolling(short_w, min_periods=2).std().values
    # Use the median realised vol as the scale so a single spike doesn't
    # dominate; multiply by 0.3 so we only block very flat slopes.
    med_rv  = float(np.nanmedian(rv)) if not np.all(np.isnan(rv)) else 1e-4
    eps     = max(0.3 * med_rv, 1e-5)

    labels = []
    for i in range(n):
        c  = close[i]
        lm = long_ma[i]
        sm = short_ma[i]
        sl = slope[i]

        # Warmup: MA not yet defined
        if np.isnan(lm) or np.isnan(sm) or np.isnan(sl):
            labels.append("sideways")
            continue

        if c > lm and sm > lm and sl > eps:
            labels.append("bull")
        elif c < lm and sm < lm and sl < -eps:
            labels.append("bear")
        else:
            labels.append("sideways")

    bull_ct = labels.count("bull")
    bear_ct = labels.count("bear")
    side_ct = labels.count("sideways")
    logger.info(
        "Regime classification: bull=%d (%.0f%%)  bear=%d (%.0f%%)  sideways=%d (%.0f%%)",
        bull_ct, 100 * bull_ct / n,
        bear_ct, 100 * bear_ct / n,
        side_ct, 100 * side_ct / n,
    )
    return labels


def regime_breakdown(
    equity_curve:    list[float],
    timestamps:      list,
    trades:          list[dict],
    regimes:         list[str],
    initial_capital: float = 10_000.0,
) -> dict[str, Any]:
    """
    Compute per-regime performance metrics.

    Args:
        equity_curve:    Portfolio value at each candle (from simulator).
        timestamps:      ISO timestamp strings aligned with equity_curve.
        trades:          Closed trade dicts from simulator.
        regimes:         One label per candle ('bull'/'bear'/'sideways').
        initial_capital: Starting capital (used as baseline for returns).

    Returns:
        dict with keys 'method', 'bull', 'bear', 'sideways' — each value
        is a condensed metrics dict.  Also includes top-level
        'regime_counts' for quick inspection.
    """
    # ── Alignment guard ──────────────────────────────────────────────────────
    # TradeSimulator initialises equity_curve with [initial_capital] then
    # appends one entry per candle, so it always has len(df)+1 elements while
    # classify_regimes() returns exactly len(df) labels.  Drop the synthetic
    # head entry so both arrays are N-length (one element per candle).
    regimes = list(regimes)
    eq_raw  = list(equity_curve)
    if len(eq_raw) == len(regimes) + 1:
        eq_raw = eq_raw[1:]          # drop the prepended initial_capital
    elif len(regimes) > len(eq_raw):
        regimes = regimes[-len(eq_raw):]   # trim leading labels
    elif len(regimes) < len(eq_raw):
        regimes = ["sideways"] * (len(eq_raw) - len(regimes)) + regimes

    n = len(eq_raw)
    if n == 0 or not regimes:
        return _empty_breakdown()

    eq        = np.array(eq_raw, dtype=float)
    # Candle-level returns (n-1 values; index i corresponds to transition i→i+1)
    can_rets  = np.diff(eq) / np.where(eq[:-1] != 0, eq[:-1], 1.0)
    cpd       = _candles_per_day(timestamps)

    # Build a timestamp→candle-index lookup for trade attribution
    ts_to_idx: dict[str, int] = {}
    for i, t in enumerate(timestamps):
        ts_to_idx[str(t)] = i

    result: dict[str, Any] = {
        "method":        "ma_trend_tf_aware",
        "regime_counts": {r: regimes.count(r) for r in REGIMES},
    }

    for regime in REGIMES:
        mask = np.array([r == regime for r in regimes], dtype=bool)  # length n
        n_regime = int(mask.sum())

        if n_regime < 2:
            result[regime] = _empty_regime_stats(n_regime, n)
            continue

        # ── Candle returns WITHIN this regime ─────────────────────────────
        # can_rets[i] = return from candle i to candle i+1.
        # We attribute it to regime if EITHER endpoint is in regime (use
        # the candle's own label for simplicity: mask[:-1] for the start).
        regime_ret_mask = mask[:-1]  # length n-1
        r_rets = can_rets[regime_ret_mask]

        # ── Compounded total return within regime ─────────────────────────
        compound_ret = float(np.prod(1 + r_rets) - 1) if len(r_rets) else 0.0

        # ── Sharpe / Sortino / Volatility ─────────────────────────────────
        mean_r = float(np.mean(r_rets)) if len(r_rets) else 0.0
        std_r  = float(np.std(r_rets))  if len(r_rets) else 0.0
        sharpe = (mean_r / std_r * np.sqrt(TRADING_DAYS_PER_YEAR * cpd)
                  if std_r > 1e-10 else 0.0)

        down   = r_rets[r_rets < 0]
        dstd   = float(np.std(down)) if len(down) > 1 else 1e-10
        sortino = (mean_r / dstd * np.sqrt(TRADING_DAYS_PER_YEAR * cpd)
                   if dstd > 1e-10 else 0.0)

        volatility = float(std_r * np.sqrt(TRADING_DAYS_PER_YEAR * cpd))

        # ── Max drawdown within regime ────────────────────────────────────
        # Rebuild a sub-equity curve from the regime candle returns
        sub_eq = np.cumprod(np.concatenate([[1.0], 1 + r_rets])) * initial_capital
        run_mx = np.maximum.accumulate(sub_eq)
        dd_arr = (sub_eq - run_mx) / np.where(run_mx != 0, run_mx, 1.0)
        max_dd = float(np.min(dd_arr))

        # ── Trade stats — attribute by entry candle ───────────────────────
        regime_trades = _filter_trades_by_regime(trades, regimes, ts_to_idx, regime)
        tstats = _trade_statistics(regime_trades)

        result[regime] = {
            "total_return_pct":  round(compound_ret * 100, 4),
            "sharpe_ratio":      round(sharpe,   4),
            "sortino_ratio":     round(sortino,  4),
            "volatility_pct":    round(volatility * 100, 4),
            "max_drawdown_pct":  round(max_dd * 100, 4),
            "num_candles":       n_regime,
            "pct_of_period":     round(100 * n_regime / n, 2),
            **tstats,
        }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _filter_trades_by_regime(
    trades:    list[dict],
    regimes:   list[str],
    ts_to_idx: dict[str, int],
    target:    str,
) -> list[dict]:
    """Return trades whose entry candle belongs to the target regime."""
    out = []
    for t in trades:
        entry_str = str(t.get("entry_time", ""))
        # Try exact match, then truncate to date if intraday
        idx = ts_to_idx.get(entry_str)
        if idx is None:
            # Fallback: match by date prefix
            for key, i in ts_to_idx.items():
                if key.startswith(entry_str[:10]):
                    idx = i
                    break
        if idx is not None and idx < len(regimes) and regimes[idx] == target:
            out.append(t)
    return out


def _empty_regime_stats(n_candles: int, total_candles: int) -> dict:
    return {
        "total_return_pct": 0.0,
        "sharpe_ratio":     0.0,
        "sortino_ratio":    0.0,
        "volatility_pct":   0.0,
        "max_drawdown_pct": 0.0,
        "num_candles":      n_candles,
        "pct_of_period":    round(100 * n_candles / max(total_candles, 1), 2),
        "num_trades":       0,
        "win_rate":         0.0,
        "profit_factor":    0.0,
        "avg_trade_pnl":    0.0,
        "best_trade":       0.0,
        "worst_trade":      0.0,
        "gross_profit":     0.0,
        "gross_loss":       0.0,
        "avg_trade_duration": 0.0,
        "trades_per_day":   0.0,
    }


def _empty_breakdown() -> dict:
    return {
        "method":        "ma_trend_tf_aware",
        "regime_counts": {"bull": 0, "bear": 0, "sideways": 0},
        "bull":          _empty_regime_stats(0, 1),
        "bear":          _empty_regime_stats(0, 1),
        "sideways":      _empty_regime_stats(0, 1),
    }
