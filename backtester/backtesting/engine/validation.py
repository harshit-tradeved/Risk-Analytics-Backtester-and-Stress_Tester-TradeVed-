"""
Out-of-Sample Validation Engine
================================

Provides two validation modes so retail traders can see whether a strategy's
backtest results hold on data the strategy never "saw":

  holdout       — simple train/test split.  Run the same user params on both
                  halves.  Fast (2 backtest runs).  Measures consistency, not
                  overfitting (since params are user-set, not fitted).

  walk_forward  — classic gold standard.  For each train window, grid-search
                  the best params by Sharpe, then apply them to the next
                  out-of-sample step.  Roll forward.  The final OOS equity
                  curve is genuinely unseen-data performance.

Both return a `validation` dict that main.py attaches to the API response.
"""
from __future__ import annotations

import itertools
import logging
from typing import Any

import numpy as np
import pandas as pd

from backtesting.engine.metrics import calculate_metrics
from backtesting.engine.simulator import TradeSimulator
from backtesting.strategies import STRATEGY_REGISTRY

# Trading candles per day for common intervals (conservative — biased toward fewer windows)
_INTERVAL_TRADING_CPD: dict[str, float] = {
    "1m":  390,  # 6.5h × 60 (US); NSE ~375
    "5m":  78,
    "15m": 26,   # US; NSE ≈ 25 — close enough
    "30m": 13,
    "1h":  7,    # rounds up from 6.5
    "2h":  3,
    "4h":  2,
    "6h":  1,
    "8h":  1,
    "1d":  1,
    "1w":  0.2,
    "1M":  0.05,
}

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Compact parameter grids for walk-forward optimisation
# ─────────────────────────────────────────────────────────────────────────────
# Deliberately small (≤ 24 combos per strategy) so walk-forward completes
# within a few seconds per window.

def _wf_grid(strategy: str, lower: float = 0, upper: float = 0, capital: float = 10_000, user_params: dict | None = None) -> list[dict]:
    # Invest amounts scale with capital so Indian ₹20L runs don't use ₹200 lots.
    # Fractions: 1%, 3%, 8% of capital per order — small enough to diversify,
    # large enough to clear lot-size minimums on large-capital Indian instruments.
    inv_sm = max(100, capital * 0.01)
    inv_md = max(200, capital * 0.03)
    inv_lg = max(500, capital * 0.08)

    if strategy == "GRID":
        rows = []
        for num_levels in [3, 5, 7]:
            for spacing in ["linear", "exponential"]:
                for invest in [inv_sm, inv_md, inv_lg]:
                    rows.append({
                        "lower_bound":          lower,
                        "upper_bound":          upper,
                        "num_levels":           num_levels,
                        "spacing":              spacing,
                        "invest_per_level_usd": invest,
                        "quantity_per_level":   0.0,
                    })
        return rows  # 18 combos

    if strategy == "DCA":
        # Always include user's actual invest amount so futures/large-lot instruments get at least one valid combo
        user_invest = float((user_params or {}).get("invest_per_buy_usd", 0) or 0)
        invest_set  = sorted({inv_sm, inv_md, inv_lg, user_invest} - {0.0})
        rows = []
        for interval_h in [24, 48, 72]:
            for invest in invest_set:
                for hold_days in [14, 30]:
                    for exit_type, tp in [("time", 5.0), ("profit", 10.0)]:
                        rows.append({
                            "buy_interval_hours": interval_h,
                            "invest_per_buy_usd": invest,
                            "buy_quantity":       0.0,
                            "hold_days":          hold_days,
                            "exit_type":          exit_type,
                            "profit_target_pct":  tp,
                        })
        return rows

    if strategy == "PLA":
        rows = []
        for fast, slow in [(9, 21), (12, 26)]:
            for invest in [inv_sm, inv_md, inv_lg]:
                for exit_type, tp in [("crossover", 5.0), ("take_profit", 5.0), ("take_profit", 10.0)]:
                    rows.append({
                        "fast_ema":             fast,
                        "slow_ema":             slow,
                        "entry_levels":         [0.0, -1.0, -2.5, -4.0],
                        "invest_per_level_usd": [invest, invest, invest * 2, invest * 3],
                        "entry_quantities":     [0.001, 0.001, 0.002, 0.003],
                        "exit_type":            exit_type,
                        "take_profit_pct":      tp,
                        "stop_loss_pct":        3.0,
                    })
        return rows  # 18 combos

    # Indicator presets / CUSTOM: no optimisation grid defined — evaluate the
    # user's own params per window so walk-forward (and WFE) still works instead
    # of silently returning zero windows.
    return [dict(user_params or {})]


# ─────────────────────────────────────────────────────────────────────────────
# Core: run a single segment (df slice → signals → simulate → metrics)
# ─────────────────────────────────────────────────────────────────────────────

def _segment_metrics(
    df:              pd.DataFrame,
    strategy_cls,
    strategy_params: dict,
    sim_kwargs:      dict,
    capital:         float,
) -> dict[str, Any] | None:
    """
    Run strategy → simulator → metrics on `df` and return the metrics dict.
    Returns None if something fails (e.g. 0 trades), so callers can skip.
    """
    try:
        # Auto-compute GRID bounds from this slice if needed or if user bounds don't overlap data
        if strategy_cls.__name__ == "GridStrategy":
            lo = float(strategy_params.get("lower_bound", 0) or 0)
            hi = float(strategy_params.get("upper_bound", 0) or 0)
            prices = df["close"].astype(float)
            lo_raw, hi_raw = float(prices.min()), float(prices.max())
            if lo >= hi or lo > hi_raw or hi < lo_raw:
                pad = (hi_raw - lo_raw) * 0.10
                strategy_params = dict(strategy_params)
                # No absolute 1.0 clamp — it inverted bounds for sub-$1 assets
                strategy_params["lower_bound"] = max(lo_raw * 0.5, lo_raw - pad)
                strategy_params["upper_bound"] = hi_raw + pad

        strat   = strategy_cls(**{**strategy_cls.default_params(), **strategy_params})
        signals = strat.generate_signals(df)
        sim     = TradeSimulator(**sim_kwargs)
        out     = sim.run(signals)

        if not out["equity_curve"]:
            return None

        metrics = calculate_metrics(
            trades          = out["trades"],
            equity_curve    = out["equity_curve"],
            timestamps      = out["timestamps"],
            initial_capital = capital,
        )
        metrics["_equity_curve_raw"] = out["equity_curve"]
        metrics["_timestamps_raw"]   = out["timestamps"]
        return metrics

    except Exception as exc:
        logger.debug("Segment failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Holdout split
# ─────────────────────────────────────────────────────────────────────────────

def run_holdout(
    df:              pd.DataFrame,
    strategy_name:   str,
    strategy_params: dict,
    sim_kwargs:      dict,
    capital:         float,
    train_ratio:     float = 0.7,
) -> dict[str, Any]:
    """
    Split df into train (in-sample) and test (out-of-sample) portions.
    Run the SAME strategy params on both halves.

    For GRID, bounds are auto-computed on train only and re-applied to test
    (honest OOS: bounds are "fitted" on train, then used as-is on test).

    Returns:
        {
          mode, train_ratio, split_date,
          in_sample:      {metrics + num_candles},
          out_of_sample:  {metrics + num_candles},
          verdict:        "stable" | "degraded" | "failed"
        }
    """
    n = len(df)
    split_idx = max(1, min(n - 1, int(n * train_ratio)))
    df_train = df.iloc[:split_idx].reset_index(drop=True)
    df_test  = df.iloc[split_idx:].reset_index(drop=True)

    split_date = str(df.iloc[split_idx]["timestamp"])[:10]
    logger.info(
        "Holdout split: train=%d candles (%.0f%%)  test=%d candles  split_date=%s",
        len(df_train), 100 * train_ratio, len(df_test), split_date,
    )

    # For GRID: compute bounds on train, carry to test; also override if user bounds don't overlap data
    train_params = dict(strategy_params)
    if strategy_name == "GRID":
        lo = float(train_params.get("lower_bound", 0) or 0)
        hi = float(train_params.get("upper_bound", 0) or 0)
        prices = df_train["close"].astype(float)
        lo_raw, hi_raw = float(prices.min()), float(prices.max())
        if lo >= hi or lo > hi_raw or hi < lo_raw:
            pad = (hi_raw - lo_raw) * 0.10
            train_params["lower_bound"] = max(lo_raw * 0.5, lo_raw - pad)
            train_params["upper_bound"] = hi_raw + pad

    strategy_cls = STRATEGY_REGISTRY[strategy_name]

    in_m  = _segment_metrics(df_train, strategy_cls, train_params, sim_kwargs, capital)
    out_m = _segment_metrics(df_test,  strategy_cls, train_params, sim_kwargs, capital)

    def _clean(m):
        if m is None:
            return {"num_trades": 0, "sharpe_ratio": 0.0, "total_return_pct": 0.0,
                    "max_drawdown_pct": 0.0, "win_rate": 0.0,
                    "annualised_return_pct": 0.0, "sortino_ratio": 0.0,
                    "calmar_ratio": 0.0, "volatility_pct": 0.0, "final_equity": capital}
        drop = {"equity_curve", "drawdowns", "timestamps", "trades",
                "_equity_curve_raw", "_timestamps_raw"}
        return {k: v for k, v in m.items() if k not in drop}

    in_clean  = _clean(in_m)
    out_clean = _clean(out_m)

    # Verdict: did OOS hold up?
    verdict = _holdout_verdict(in_m, out_m)

    stitched_eq = []
    stitched_ts = []
    stitched_dd = []
    if in_m is not None and out_m is not None:
        in_eq = in_m["_equity_curve_raw"]
        out_eq = out_m["_equity_curve_raw"]
        factor = in_eq[-1] / out_eq[0] if out_eq[0] > 0 else 1.0
        stitched_eq = in_eq + [v * factor for v in out_eq[1:]]
        stitched_ts = in_m["_timestamps_raw"] + out_m["_timestamps_raw"]

        # calculate drawdowns
        eq_arr = np.array(stitched_eq, dtype=float)
        running_max = np.maximum.accumulate(eq_arr)
        dd_arr = (eq_arr - running_max) / running_max
        dd_arr = np.where(running_max == 0, 0, dd_arr)
        stitched_dd = dd_arr.tolist()

    return {
        "mode":          "holdout",
        "train_ratio":   train_ratio,
        "split_date":    split_date,
        "in_sample":     {**in_clean,  "num_candles": len(df_train)},
        "out_of_sample": {**out_clean, "num_candles": len(df_test)},
        "verdict":       verdict,
        # The stitched chart ratio-scales the OOS segment to continue from the
        # IS final equity; per-segment metrics above use the unscaled curves
        # (each segment is traded from initial capital).
        "validation_curve_note": "OOS segment ratio-scaled for chart continuity; metrics use unscaled per-segment curves.",
        "validation_equity_curve": stitched_eq,
        "validation_timestamps": stitched_ts,
        "validation_drawdowns": stitched_dd,
    }



def _holdout_verdict(in_m, out_m) -> str:
    """Classify whether OOS held up vs in-sample."""
    if in_m is None or out_m is None:
        return "insufficient_data"

    in_sharpe  = in_m.get("sharpe_ratio", 0) or 0
    out_sharpe = out_m.get("sharpe_ratio", 0) or 0
    out_ret    = out_m.get("total_return_pct", 0) or 0

    if out_ret < 0:
        return "failed"      # OOS actually lost money
    if in_sharpe > 0.1 and out_sharpe < in_sharpe * 0.5:
        return "degraded"    # Sharpe dropped >50%
    return "stable"          # OOS looks consistent


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────────────────────────────────────

def run_walk_forward(
    df:              pd.DataFrame,
    strategy_name:   str,
    strategy_params: dict,
    sim_kwargs:      dict,
    capital:         float,
    window:          int = 252,
    step:            int = 63,
    interval:        str = "1d",
) -> dict[str, Any]:
    """
    Classic walk-forward: grid-search on each train window, apply best params
    to the next out-of-sample step.  Roll forward until df is exhausted.

    Returns:
        {
          mode, window, step,
          windows: [ {period, train_period, best_params_summary,
                      return_pct, sharpe, max_dd_pct, num_trades}, ... ],
          out_of_sample: {aggregated metrics across all test segments}
        }
    """
    n = len(df)

    # Scale window/step from trading-day units to candles for intraday data.
    # window/step defaults (252/63) mean "1yr IS / 1qtr OOS" in trading-day terms.
    # For intraday intervals, multiply by candles-per-trading-day to preserve
    # that semantic meaning and keep the window count in a sane range.
    cpd = _INTERVAL_TRADING_CPD.get(interval, 1.0)
    if cpd > 1.0:
        window = min(int(window * cpd), int(n * 0.75))
        step   = max(1, int(step   * cpd))
        logger.info(
            "Walk-forward: interval=%s (cpd=%.1f) → scaled window=%d step=%d",
            interval, cpd, window, step,
        )

    # Proportional fallback: if the scaled window+step exceeds the dataset or would
    # yield < 2 windows, use 60% train / 20% step so WFE is always computable.
    natural_windows = max(0, (n - window) // step) if step > 0 else 0
    if n < window + step or natural_windows < 2:
        window = int(n * 0.60)
        step   = max(1, int(n * 0.20))
        logger.info(
            "Walk-forward: short dataset (%d candles) → proportional window=%d step=%d",
            n, window, step,
        )

    if n < window + step:
        logger.warning(
            "Walk-forward: not enough data (%d candles, need at least %d). "
            "Returning empty.", n, window + step,
        )
        return _empty_walk_forward(window, step)

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    windows_out  = []

    # Track training window and test segment curves for walk-forward validation curve stitching
    first_success_train_eq = []
    first_success_train_ts = []
    test_segments = []

    # Collect all OOS equity points (stitched together)
    all_oos_eq: list[float] = [capital]
    all_oos_ts: list[str]   = []
    all_oos_trades: list[dict] = []

    start = 0
    win_num = 0
    while start + window + step <= n:
        train_end  = start + window
        test_end   = min(train_end + step, n)
        df_train   = df.iloc[start:train_end].reset_index(drop=True)
        df_test    = df.iloc[train_end:test_end].reset_index(drop=True)

        train_start_date = str(df.iloc[start]["timestamp"])[:10]
        train_end_date   = str(df.iloc[train_end - 1]["timestamp"])[:10]
        test_start_date  = str(df.iloc[train_end]["timestamp"])[:10]
        test_end_date    = str(df.iloc[test_end - 1]["timestamp"])[:10]

        # ── Grid-search on train window ───────────────────────────────────
        lo = hi = 0.0
        if strategy_name == "GRID":
            prices  = df_train["close"].astype(float)
            lo_raw, hi_raw = float(prices.min()), float(prices.max())
            pad = (hi_raw - lo_raw) * 0.10
            lo  = max(lo_raw * 0.5, lo_raw - pad)
            hi  = hi_raw + pad

        combos = _wf_grid(strategy_name, lower=lo, upper=hi, capital=capital, user_params=strategy_params)
        best_params  = None
        best_sharpe  = -np.inf
        best_metrics = None

        for combo in combos:
            m = _segment_metrics(df_train, strategy_cls, combo, sim_kwargs, capital)
            if m is None:
                continue
            if m["sharpe_ratio"] > best_sharpe:
                best_sharpe  = m["sharpe_ratio"]
                best_params  = combo
                best_metrics = m

        if best_params is None:
            logger.debug("Walk-forward window %d: no valid train combo", win_num)
            start += step
            win_num += 1
            continue

        if not first_success_train_eq and best_metrics is not None:
            first_success_train_eq = best_metrics.get("_equity_curve_raw", [])
            first_success_train_ts = best_metrics.get("_timestamps_raw", [])


        # ── Apply best params to OOS test slice ───────────────────────────
        oos_m = _segment_metrics(df_test, strategy_cls, best_params, sim_kwargs, capital)

        if oos_m is not None:
            # Stitch: adjust OOS equity by last known OOS equity level
            base = all_oos_eq[-1]
            oos_raw = oos_m.get("_equity_curve_raw", [])
            oos_ts = oos_m.get("_timestamps_raw", [])
            test_segments.append((oos_raw, oos_ts))
            if oos_raw and oos_raw[0] > 0:
                factor = base / oos_raw[0]
                all_oos_eq.extend([v * factor for v in oos_raw[1:]])
            all_oos_ts.extend(oos_m.get("_timestamps_raw", []))
            # Offset trade times to distinguish windows (keep as-is; already ISO)
            all_oos_trades.extend(oos_m.get("trades", []))

            windows_out.append({
                "window_num":       win_num + 1,
                "train_period":     f"{train_start_date} → {train_end_date}",
                "test_period":      f"{test_start_date} → {test_end_date}",
                "best_params":      _params_summary(strategy_name, best_params),
                "train_sharpe":     round(best_sharpe, 3),
                "return_pct":       round(oos_m.get("total_return_pct", 0), 3),
                "sharpe":           round(oos_m.get("sharpe_ratio", 0), 3),
                "max_dd_pct":       round(oos_m.get("max_drawdown_pct", 0), 3),
                "num_trades":       oos_m.get("num_trades", 0),
                "win_rate":         round(oos_m.get("win_rate", 0), 2),
            })
        else:
            windows_out.append({
                "window_num":   win_num + 1,
                "train_period": f"{train_start_date} → {train_end_date}",
                "test_period":  f"{test_start_date} → {test_end_date}",
                "best_params":  _params_summary(strategy_name, best_params),
                "train_sharpe": round(best_sharpe, 3),
                "return_pct":   0.0, "sharpe": 0.0, "max_dd_pct": 0.0,
                "num_trades":   0, "win_rate": 0.0,
            })

        start  += step
        win_num += 1

    # ── Aggregate OOS metrics across all test windows ─────────────────────
    if len(all_oos_eq) > 1:
        agg_metrics = calculate_metrics(
            trades          = all_oos_trades,
            equity_curve    = all_oos_eq,
            timestamps      = all_oos_ts if all_oos_ts else list(range(len(all_oos_eq))),
            initial_capital = capital,
        )
        agg_clean = {k: v for k, v in agg_metrics.items()
                     if k not in {"equity_curve", "drawdowns", "timestamps", "trades"}}
    else:
        agg_clean = {
            "num_trades": 0, "sharpe_ratio": 0.0, "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "win_rate": 0.0,
            "annualised_return_pct": 0.0, "sortino_ratio": 0.0,
        }

    logger.info(
        "Walk-forward: %d windows completed  OOS return=%.2f%%  OOS Sharpe=%.2f",
        len(windows_out),
        agg_clean.get("total_return_pct", 0),
        agg_clean.get("sharpe_ratio", 0),
    )

    val_eq = []
    val_ts = []
    val_dd = []
    if first_success_train_eq:
        val_eq = list(first_success_train_eq)
        val_ts = list(first_success_train_ts)
        for oos_raw, oos_ts in test_segments:
            if oos_raw:
                base = val_eq[-1]
                factor = base / oos_raw[0] if oos_raw[0] > 0 else 1.0
                val_eq.extend([v * factor for v in oos_raw[1:]])
                val_ts.extend(oos_ts)

        # calculate drawdowns
        val_eq_arr = np.array(val_eq, dtype=float)
        val_running_max = np.maximum.accumulate(val_eq_arr)
        val_dd_arr = (val_eq_arr - val_running_max) / val_running_max
        val_dd_arr = np.where(val_running_max == 0, 0, val_dd_arr)
        val_dd = val_dd_arr.tolist()

    return {
        "mode":          "walk_forward",
        "window":        window,
        "step":          step,
        "num_windows":   len(windows_out),
        "windows":       windows_out,
        "out_of_sample": agg_clean,
        "validation_curve_note": "OOS segments ratio-scaled for chart continuity; metrics use unscaled per-segment curves.",
        "validation_equity_curve": val_eq,
        "validation_timestamps": val_ts,
        "validation_drawdowns": val_dd,
    }



# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _params_summary(strategy: str, params: dict) -> str:
    if strategy == "GRID":
        return (f"levels={params.get('num_levels')}  "
                f"spacing={params.get('spacing')}  "
                f"invest={params.get('invest_per_level_usd')}")
    if strategy == "DCA":
        return (f"interval={params.get('buy_interval_hours')}h  "
                f"invest={params.get('invest_per_buy_usd')}  "
                f"hold={params.get('hold_days')}d  "
                f"exit={params.get('exit_type')}")
    if strategy == "PLA":
        inv = params.get("invest_per_level_usd")
        base = inv[0] if isinstance(inv, list) else inv
        return (f"ema={params.get('fast_ema')}/{params.get('slow_ema')}  "
                f"invest={base}  "
                f"exit={params.get('exit_type')}  "
                f"tp={params.get('take_profit_pct')}%")
    return str(params)


def _empty_walk_forward(window: int, step: int) -> dict:
    return {
        "mode":          "walk_forward",
        "window":        window,
        "step":          step,
        "num_windows":   0,
        "windows":       [],
        "out_of_sample": {
            "num_trades": 0, "sharpe_ratio": 0.0, "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "win_rate": 0.0,
            "annualised_return_pct": 0.0, "sortino_ratio": 0.0,
            "note": "Not enough data for walk-forward (need window + step candles minimum)",
        },
        "validation_equity_curve": [],
        "validation_timestamps": [],
        "validation_drawdowns": [],
    }


# Public alias — orchestrator/pipeline.py runs single backtests (loop rounds,
# retry-symbol) through this rather than reaching into the "private" helper
# directly. Mirrors the existing `run_single_backtest = _single_backtest`
# alias pattern in engine/stress.py.
run_segment_backtest = _segment_metrics
