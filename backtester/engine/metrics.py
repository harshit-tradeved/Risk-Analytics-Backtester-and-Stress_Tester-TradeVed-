"""
Metrics Engine — computes all performance statistics from simulator results.

Metrics:
  - Total Return ($ and %)
  - Annualised Return
  - Sharpe Ratio          (annualised, risk-free rate = 0)
  - Sortino Ratio         (annualised, downside deviation)
  - Max Drawdown          (peak-to-trough %)
  - Max Drawdown Duration (days)
  - Calmar Ratio          (annualised return / |max drawdown|)
  - Win Rate              (% of profitable trades)
  - Profit Factor         (gross profit / gross loss)
  - Average Trade P&L
  - Best / Worst Trade
  - Trades per Day
  - Average Trade Duration (hours)
  - Volatility            (annualised)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


def calculate_metrics(
    trades:       list[dict],
    equity_curve: list[float],
    timestamps:   list,
    initial_capital: float = 10_000.0,
) -> dict[str, Any]:
    """
    Compute all performance metrics.

    Args:
        trades:          List of trade dicts from TradeSimulator.run()
        equity_curve:    List of equity values (one per candle)
        timestamps:      Corresponding candle timestamps
        initial_capital: Starting capital

    Returns:
        Dict with all metrics + equity_curve + drawdowns + trades
    """
    if not equity_curve:
        return _empty_metrics(initial_capital)

    eq = np.array(equity_curve, dtype=float)

    # ── Returns ───────────────────────────────────────────────────────────────
    total_return_usd = float(eq[-1] - eq[0])
    total_return_pct = float((eq[-1] - eq[0]) / eq[0]) if eq[0] != 0 else 0.0

    # ── Candle returns ────────────────────────────────────────────────────────
    candle_returns = np.diff(eq) / eq[:-1]
    candle_returns = candle_returns[np.isfinite(candle_returns)]

    # Infer candles-per-day from timestamps
    cpd = _candles_per_day(timestamps)

    # ── Annualised return ─────────────────────────────────────────────────────
    n_days = len(eq) / max(cpd, 1)
    ann_return = (
        float((eq[-1] / eq[0]) ** (TRADING_DAYS_PER_YEAR / max(n_days, 1)) - 1)
        if eq[0] > 0 else 0.0
    )

    # ── Sharpe ────────────────────────────────────────────────────────────────
    mean_ret = float(np.mean(candle_returns)) if len(candle_returns) else 0.0
    std_ret  = float(np.std(candle_returns))  if len(candle_returns) else 0.0
    sharpe   = (mean_ret / std_ret * np.sqrt(TRADING_DAYS_PER_YEAR * cpd)
                if std_ret > 1e-10 else 0.0)

    # ── Sortino ───────────────────────────────────────────────────────────────
    downside = candle_returns[candle_returns < 0]
    down_std = float(np.std(downside)) if len(downside) > 1 else 1e-10
    sortino  = (mean_ret / down_std * np.sqrt(TRADING_DAYS_PER_YEAR * cpd)
                if down_std > 1e-10 else 0.0)

    # ── Drawdown ──────────────────────────────────────────────────────────────
    running_max = np.maximum.accumulate(eq)
    drawdowns   = (eq - running_max) / running_max
    drawdowns   = np.where(running_max == 0, 0, drawdowns)
    max_dd      = float(np.min(drawdowns))

    # Max drawdown duration (consecutive candles below peak)
    dd_duration = _max_dd_duration(drawdowns)

    # ── Calmar ────────────────────────────────────────────────────────────────
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-10 else 0.0

    # ── Volatility ───────────────────────────────────────────────────────────
    volatility = float(std_ret * np.sqrt(TRADING_DAYS_PER_YEAR * cpd)) if std_ret > 0 else 0.0

    # ── Trade-level stats ─────────────────────────────────────────────────────
    trade_stats = _trade_statistics(trades)

    metrics = {
        # Returns
        "total_return_usd":     round(total_return_usd, 4),
        "total_return_pct":     round(total_return_pct * 100, 4),
        "annualised_return_pct": round(ann_return * 100, 4),
        "final_equity":         round(float(eq[-1]), 4),
        "initial_capital":      round(initial_capital, 4),

        # Risk-adjusted
        "sharpe_ratio":         round(sharpe,   4),
        "sortino_ratio":        round(sortino,  4),
        "calmar_ratio":         round(calmar,   4),
        "volatility_pct":       round(volatility * 100, 4),

        # Drawdown
        "max_drawdown_pct":     round(max_dd * 100, 4),
        "max_dd_duration_candles": int(dd_duration),

        # Trade stats
        **trade_stats,

        # Curves (for charting)
        "equity_curve":  [round(float(v), 4) for v in eq],
        "drawdowns":     [round(float(v) * 100, 4) for v in drawdowns],
        "timestamps":    [str(t) for t in timestamps],
        "trades":        trades,
    }

    logger.info(
        "Metrics — return: %.2f%% | sharpe: %.2f | max_dd: %.2f%% | trades: %d",
        metrics["total_return_pct"],
        metrics["sharpe_ratio"],
        metrics["max_drawdown_pct"],
        metrics["num_trades"],
    )
    return metrics


# ── Trade statistics ──────────────────────────────────────────────────────────

def _trade_statistics(trades: list[dict]) -> dict:
    if not trades:
        return {
            "num_trades":          0,
            "win_rate":            0.0,
            "profit_factor":       0.0,
            "avg_trade_pnl":       0.0,
            "best_trade":          0.0,
            "worst_trade":         0.0,
            "gross_profit":        0.0,
            "gross_loss":          0.0,
            "avg_trade_duration":  0.0,
            "trades_per_day":      0.0,
        }

    pnls      = [t["pnl"]     for t in trades]
    pnl_pcts  = [t["pnl_pct"] for t in trades]
    winners   = [p for p in pnls if p > 0]
    losers    = [p for p in pnls if p < 0]   # zero-PnL trades are neither wins nor losses

    gross_profit = sum(winners)
    gross_loss   = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-10 else float("inf")

    # Duration
    durations = []
    for t in trades:
        try:
            entry = pd.Timestamp(t["entry_time"])
            exit_ = pd.Timestamp(t["exit_time"])
            durations.append((exit_ - entry).total_seconds() / 3600)
        except Exception:
            pass

    avg_duration = float(np.mean(durations)) if durations else 0.0

    # Trades per day
    try:
        start = pd.Timestamp(trades[0]["entry_time"])
        end   = pd.Timestamp(trades[-1]["exit_time"])
        days  = max((end - start).days, 1)
        trades_per_day = len(trades) / days
    except Exception:
        trades_per_day = 0.0

    return {
        "num_trades":         len(trades),
        "win_rate":           round(len(winners) / len(trades) * 100, 2),
        "profit_factor":      round(profit_factor, 4),
        "avg_trade_pnl":      round(float(np.mean(pnls)), 4),
        "best_trade":         round(max(pnls), 4),
        "worst_trade":        round(min(pnls), 4),
        "gross_profit":       round(gross_profit, 4),
        "gross_loss":         round(gross_loss, 4),
        "avg_trade_duration": round(avg_duration, 2),
        "trades_per_day":     round(trades_per_day, 4),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _candles_per_day(timestamps: list) -> float:
    """Infer how many candles there are per trading day."""
    if len(timestamps) < 2:
        return 1.0
    try:
        ts = [pd.Timestamp(t) for t in timestamps[:50]]
        diffs = [(ts[i + 1] - ts[i]).total_seconds() for i in range(len(ts) - 1)]
        median_sec = float(np.median(diffs))
        # Allow fractional candles-per-day so weekly (1/7) and monthly (~1/30)
        # data annualise correctly; the old max(1.0, …) floor inflated weekly
        # Sharpe by ~sqrt(7). Floor at monthly to bound pathological gaps.
        return max(1.0 / 31.0, 86_400 / median_sec)
    except Exception:
        return 1.0


def _max_dd_duration(drawdowns: np.ndarray) -> int:
    """Return the longest consecutive stretch below the previous peak (in candles)."""
    max_dur = 0
    cur_dur = 0
    for dd in drawdowns:
        if dd < 0:
            cur_dur += 1
            max_dur  = max(max_dur, cur_dur)
        else:
            cur_dur = 0
    return max_dur


def _empty_metrics(initial_capital: float) -> dict:
    return {
        "total_return_usd": 0.0,   "total_return_pct": 0.0,
        "annualised_return_pct": 0.0, "final_equity": initial_capital,
        "initial_capital": initial_capital,
        "sharpe_ratio": 0.0,       "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,       "volatility_pct": 0.0,
        "max_drawdown_pct": 0.0,   "max_dd_duration_candles": 0,
        "num_trades": 0,           "win_rate": 0.0,
        "profit_factor": 0.0,      "avg_trade_pnl": 0.0,
        "best_trade": 0.0,         "worst_trade": 0.0,
        "gross_profit": 0.0,       "gross_loss": 0.0,
        "avg_trade_duration": 0.0, "trades_per_day": 0.0,
        "equity_curve": [initial_capital],
        "drawdowns": [0.0],
        "timestamps": [],          "trades": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Absolute composite score for the pipeline optimization loop
# ─────────────────────────────────────────────────────────────────────────────
# `_add_composite_scores` in crypto_optimizer.py min-max normalises across a
# BATCH of candidate runs — it needs several rows to compare. The pipeline
# loop only ever has ONE candidate per round, so there's nothing to normalise
# against; instead each metric is clamped against a fixed, reasonable range
# and rescaled to [0, 1]. Same weights as the batch optimizer (Sharpe 35% +
# Return 25% + Sortino 20% + Calmar 10% + MDD 10%), same intent, different
# math because the input shape is different (one row, not many).
SCORE_WEIGHTS = {
    "sharpe_ratio":     0.35,
    "total_return_pct": 0.25,
    "sortino_ratio":    0.20,
    "calmar_ratio":     0.10,
    "max_drawdown_pct": 0.10,
}

_SCORE_RANGES = {
    "sharpe_ratio":     (-3.0, 3.0),
    "total_return_pct": (-50.0, 100.0),
    "sortino_ratio":    (-3.0, 3.0),
    "calmar_ratio":     (-3.0, 3.0),
    "max_drawdown_pct": (0.0, 50.0),   # inverted: lower drawdown = higher score
}


def score_backtest(metrics: dict) -> float:
    """
    Absolute composite score in [0, 1] for a single backtest's metrics dict.
    Missing fields clamp to their range midpoint (score contribution 0.5)
    rather than 0, so an incomplete metrics dict doesn't look catastrophic.
    """
    total = 0.0
    for key, weight in SCORE_WEIGHTS.items():
        lo, hi = _SCORE_RANGES[key]
        val = metrics.get(key)
        if val is None:
            total += weight * 0.5
            continue
        val = max(lo, min(hi, float(val)))
        norm = (val - lo) / (hi - lo)
        if key == "max_drawdown_pct":
            norm = 1.0 - norm
        total += weight * norm
    return round(total, 4)
