"""
Crypto Strategy Parameter Optimizer
=====================================
Systematically tests GRID, DCA, and PLA strategies across multiple crypto
symbols and parameter combinations. Ranks results by a composite score
(Sharpe, return, Sortino, Calmar, drawdown, profit factor) and generates
a self-contained interactive HTML report.

Usage:
    python crypto_optimizer.py                          # default settings
    python crypto_optimizer.py --symbols BTC/USDT ETH/USDT
    python crypto_optimizer.py --strategies GRID DCA
    python crypto_optimizer.py --start 2022-01-01 --end 2024-01-01
    python crypto_optimizer.py --capital 10000 --workers 4

Output:
    optimizer_results/
        results_<timestamp>.csv     — full results table
        report_<timestamp>.html     — interactive leaderboard + charts
"""

from __future__ import annotations

# Project packages live at the repo root (one folder per project); make them importable.
import sys as _sys
from pathlib import Path as _Path
_repo_root = str(_Path(__file__).resolve().parent.parent)
if _repo_root not in _sys.path:
    _sys.path.insert(1, _repo_root)


import argparse
import csv
import itertools
import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
import threading

import numpy as np
import pandas as pd

# ── Windows UTF-8 stdout (handles emojis / arrows in print) ─────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Make sure we can import from backtester package ─────────────────────────
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from backtesting.backend.data.fetcher import DataFetcher
from backtesting.backend.data.validator import DataValidator
from backtesting.backend.engine.simulator import TradeSimulator
from backtesting.backend.engine.metrics import calculate_metrics
from backtesting.backend.strategies.grid import GridStrategy
from backtesting.backend.strategies.dca import DCAStrategy
from backtesting.backend.strategies.pla import PLAStrategy

# ── Logging — quiet: config.py already called basicConfig(INFO); override it ─
# Set noisy sub-loggers to WARNING so they don't pollute the progress output.
for _ns in ("data", "strategies", "engine", "frontend", "root"):
    logging.getLogger(_ns if _ns != "root" else "").setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

logger = logging.getLogger("crypto_optimizer")

# ── Constants ─────────────────────────────────────────────────────────────────
OUTPUT_DIR   = HERE / "optimizer_results"
SOURCE       = "binance"
INTERVAL     = "1d"
CAPITAL      = 10_000.0
FEE_PCT      = 0.001   # 0.1 % Binance maker fee
SLIPPAGE_PCT = 0.001   # 0.1 % conservative slippage

# ── Default symbols ───────────────────────────────────────────────────────────
DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

# ── Default date range ────────────────────────────────────────────────────────
DEFAULT_START = date(2022, 1, 1)
DEFAULT_END   = date(2024, 1, 1)

# ── Composite score weights ───────────────────────────────────────────────────
SCORE_WEIGHTS = {
    "sharpe_ratio":        0.35,
    "total_return_pct":    0.25,
    "sortino_ratio":       0.20,
    "calmar_ratio":        0.10,
    "max_drawdown_pct":    0.10,   # inverted — lower dd = better
}

# ─────────────────────────────────────────────────────────────────────────────
# Parameter grids
# ─────────────────────────────────────────────────────────────────────────────

def _grid_param_combos(lower: float, upper: float) -> list[dict]:
    """
    Build GRID parameter combinations.
    Bounds are auto-detected from price history; other params swept here.
    """
    grid = []
    for num_levels in [3, 5, 7, 10]:
        for spacing in ["linear", "exponential"]:
            for invest in [200, 500, 1_000]:
                grid.append({
                    "lower_bound":          lower,
                    "upper_bound":          upper,
                    "num_levels":           num_levels,
                    "spacing":              spacing,
                    "invest_per_level_usd": invest,
                    "quantity_per_level":   0.0,
                })
    return grid   # 4 × 2 × 3 = 24 combos per symbol


def _dca_param_combos() -> list[dict]:
    """DCA parameter sweep — buy interval, invest size, hold period."""
    grid = []
    for interval_h in [24, 48, 72]:          # daily / every 2d / every 3d
        for invest in [100, 300, 500]:
            for hold_days in [14, 30, 60]:
                for exit_type in ["time", "profit"]:
                    entry: dict = {
                        "buy_interval_hours": interval_h,
                        "invest_per_buy_usd": invest,
                        "buy_quantity":       0.0,
                        "hold_days":          hold_days,
                        "exit_type":          exit_type,
                        "profit_target_pct":  10.0,
                    }
                    grid.append(entry)
                    if exit_type == "profit":
                        # also test with different targets
                        for pt in [5.0, 15.0]:
                            row = dict(entry)
                            row["profit_target_pct"] = pt
                            grid.append(row)
    return grid   # ≈ 3 × 3 × 3 × (1+2) ≈ 81 combos — de-duped below


def _pla_param_combos() -> list[dict]:
    """PLA parameter sweep — EMA periods, exit type, invest sizes."""
    grid = []
    ema_pairs = [(9, 21), (12, 26), (20, 50)]
    entry_level_sets = [
        [0.0, -1.0, -2.5, -4.0],
        [0.0, -2.0, -4.0, -6.0],
        [0.0, -0.5, -1.5, -3.0],
    ]
    invest_sets = [
        [200, 200, 400, 600],
        [300, 300, 600, 900],
        [500, 500, 1000, 1500],
    ]
    for fast, slow in ema_pairs:
        for levels in entry_level_sets:
            for invest in invest_sets:
                for exit_type, tp in [("crossover", 5.0), ("take_profit", 5.0), ("take_profit", 10.0)]:
                    grid.append({
                        "fast_ema":             fast,
                        "slow_ema":             slow,
                        "entry_levels":         levels,
                        "invest_per_level_usd": invest,
                        "entry_quantities":     [0.001, 0.001, 0.002, 0.003],
                        "exit_type":            exit_type,
                        "take_profit_pct":      tp,
                        "stop_loss_pct":        3.0,
                    })
    return grid   # 3 × 3 × 3 × 3 = 81 combos per symbol


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching + caching
# ─────────────────────────────────────────────────────────────────────────────

_fetcher   = DataFetcher()
_validator = DataValidator()
_data_cache: dict[str, pd.DataFrame] = {}
_cache_lock = threading.Lock()


def _fetch_symbol(symbol: str, start: date, end: date) -> Optional[pd.DataFrame]:
    cache_key = f"{symbol}|{start}|{end}"
    with _cache_lock:
        if cache_key in _data_cache:
            return _data_cache[cache_key]

    try:
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt   = datetime.combine(end,   datetime.max.time())
        df = _fetcher.fetch(symbol, start_dt, end_dt, SOURCE, INTERVAL)
        val = _validator.validate(df)
        if not val.passed:
            logger.warning("Low data quality for %s (score=%s): %s", symbol, val.quality_score, val.issues)
        with _cache_lock:
            _data_cache[cache_key] = df
        return df
    except Exception as exc:
        logger.error("Failed to fetch %s: %s", symbol, exc)
        return None


def _auto_grid_bounds(df: pd.DataFrame) -> tuple[float, float]:
    """Compute GRID lower/upper bounds from price history (+/- 10% padding)."""
    prices = df["close"].astype(float)
    lo_raw = float(prices.min())
    hi_raw = float(prices.max())
    pad    = (hi_raw - lo_raw) * 0.10
    lower  = _round_nice(max(0.0, lo_raw - pad), "floor")
    upper  = _round_nice(hi_raw + pad, "ceil")
    return lower, upper


def _round_nice(value: float, direction: str = "floor") -> float:
    if value <= 0:
        return 0.0
    magnitude = 10 ** (math.floor(math.log10(abs(value))) - 1)
    if direction == "floor":
        return math.floor(value / magnitude) * magnitude
    return math.ceil(value / magnitude) * magnitude


# ─────────────────────────────────────────────────────────────────────────────
# Single run
# ─────────────────────────────────────────────────────────────────────────────

def _run_single(
    symbol:   str,
    strategy: str,
    params:   dict,
    df:       pd.DataFrame,
    run_id:   int,
) -> dict:
    """Run one backtest; return a flat result dict."""
    result: dict = {
        "run_id":   run_id,
        "symbol":   symbol,
        "strategy": strategy,
        "error":    None,
        **{f"param_{k}": v for k, v in params.items()},
    }

    try:
        strategy_cls = {"GRID": GridStrategy, "DCA": DCAStrategy, "PLA": PLAStrategy}[strategy]
        merged = {**strategy_cls.default_params(), **params}
        inst   = strategy_cls(**merged)
        sigs   = inst.generate_signals(df.copy())

        sim = TradeSimulator(
            symbol           = symbol,
            capital          = CAPITAL,
            fee_percent      = FEE_PCT,
            slippage_percent = SLIPPAGE_PCT,
        )
        out = sim.run(sigs)

        met = calculate_metrics(
            trades          = out["trades"],
            equity_curve    = out["equity_curve"],
            timestamps      = out["timestamps"],
            initial_capital = CAPITAL,
        )

        result.update({
            "num_trades":           met["num_trades"],
            "total_return_pct":     met["total_return_pct"],
            "annualised_return_pct": met["annualised_return_pct"],
            "sharpe_ratio":         _cap(met["sharpe_ratio"]),
            "sortino_ratio":        _cap(met["sortino_ratio"]),
            "calmar_ratio":         _cap(met["calmar_ratio"]),
            "max_drawdown_pct":     met["max_drawdown_pct"],
            "win_rate":             met["win_rate"],
            "profit_factor":        _cap(met["profit_factor"], hi=20.0),
            "volatility_pct":       met["volatility_pct"],
            "avg_trade_pnl":        met["avg_trade_pnl"],
            "best_trade":           met["best_trade"],
            "worst_trade":          met["worst_trade"],
            "final_equity":         met["final_equity"],
            "composite_score":      0.0,   # filled later
        })

    except Exception as exc:
        result["error"] = str(exc)
        result.update({
            "num_trades": 0, "total_return_pct": 0.0,
            "annualised_return_pct": 0.0,
            "sharpe_ratio": 0.0, "sortino_ratio": 0.0,
            "calmar_ratio": 0.0, "max_drawdown_pct": 0.0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "volatility_pct": 0.0, "avg_trade_pnl": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
            "final_equity": CAPITAL, "composite_score": 0.0,
        })

    return result


def _cap(value: float, lo: float = -20.0, hi: float = 20.0) -> float:
    if not math.isfinite(value):
        return hi if value > 0 else lo
    return max(lo, min(hi, value))


# ─────────────────────────────────────────────────────────────────────────────
# Composite score
# ─────────────────────────────────────────────────────────────────────────────

def _add_composite_scores(rows: list[dict]) -> list[dict]:
    """
    Min-max normalise each metric across all valid rows, then compute
    a weighted composite score.  Rows with 0 trades are excluded from
    normalisation but still get score = 0.
    """
    valid = [r for r in rows if r.get("num_trades", 0) > 0 and not r.get("error")]

    if not valid:
        return rows

    def _norm(col: str, invert: bool = False) -> dict[int, float]:
        vals = [r[col] for r in valid]
        lo, hi = min(vals), max(vals)
        span = hi - lo if (hi - lo) > 1e-10 else 1.0
        out = {}
        for r in valid:
            n = (r[col] - lo) / span
            out[r["run_id"]] = 1.0 - n if invert else n
        return out

    sharpe_n  = _norm("sharpe_ratio")
    ret_n     = _norm("total_return_pct")
    sortino_n = _norm("sortino_ratio")
    calmar_n  = _norm("calmar_ratio")
    mdd_n     = _norm("max_drawdown_pct", invert=True)   # lower dd = higher score

    w = SCORE_WEIGHTS
    for r in rows:
        rid = r["run_id"]
        if rid in sharpe_n:
            r["composite_score"] = round(
                w["sharpe_ratio"]     * sharpe_n[rid]  +
                w["total_return_pct"] * ret_n[rid]     +
                w["sortino_ratio"]    * sortino_n[rid] +
                w["calmar_ratio"]     * calmar_n[rid]  +
                w["max_drawdown_pct"] * mdd_n[rid],
                4,
            )

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_optimizer(
    symbols:    list[str],
    strategies: list[str],
    start:      date,
    end:        date,
    workers:    int = 4,
) -> list[dict]:

    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*70}")
    print("  TradeVed Crypto Parameter Optimizer")
    print(f"{'='*70}")
    print(f"  Symbols   : {', '.join(symbols)}")
    print(f"  Strategies: {', '.join(strategies)}")
    print(f"  Period    : {start} → {end}")
    print(f"  Capital   : ${CAPITAL:,.0f} | Fee: {FEE_PCT*100:.1f}% | Slippage: {SLIPPAGE_PCT*100:.1f}%")
    print(f"  Workers   : {workers}")
    print(f"{'='*70}\n")

    # ── 1. Fetch data ─────────────────────────────────────────────────────────
    print("📥  Fetching price data …")
    data_map: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        print(f"    {sym} … ", end="", flush=True)
        df = _fetch_symbol(sym, start, end)
        if df is not None and not df.empty:
            data_map[sym] = df
            print(f"✓  {len(df)} candles")
        else:
            print("✗  FAILED — skipping")

    if not data_map:
        print("No data fetched. Aborting.")
        sys.exit(1)

    # ── 2. Build task list ────────────────────────────────────────────────────
    print("\n🔧  Building parameter grids …")
    tasks: list[tuple[str, str, dict]] = []   # (symbol, strategy, params)

    for sym, df in data_map.items():
        lower, upper = _auto_grid_bounds(df)

        if "GRID" in strategies:
            combos = _grid_param_combos(lower, upper)
            for c in combos:
                tasks.append((sym, "GRID", c))
            print(f"    {sym} GRID: {len(combos)} combos")

        if "DCA" in strategies:
            combos = _dca_param_combos()
            for c in combos:
                tasks.append((sym, "DCA", c))
            print(f"    {sym} DCA : {len(combos)} combos")

        if "PLA" in strategies:
            combos = _pla_param_combos()
            for c in combos:
                tasks.append((sym, "PLA", c))
            print(f"    {sym} PLA : {len(combos)} combos")

    total = len(tasks)
    print(f"\n  ▶  Total runs: {total}")

    # ── 3. Execute in parallel ────────────────────────────────────────────────
    print(f"\n🚀  Running backtests ({workers} workers) …\n")
    results: list[dict] = []
    completed = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_single, sym, strat, params, data_map[sym], i): i
            for i, (sym, strat, params) in enumerate(tasks)
        }

        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            completed += 1

            # Progress bar every 10 completions
            if completed % 10 == 0 or completed == total:
                elapsed  = time.time() - t0
                pct      = completed / total * 100
                eta_s    = (elapsed / completed) * (total - completed) if completed else 0
                bar_len  = 30
                filled   = int(bar_len * completed / total)
                bar      = "█" * filled + "░" * (bar_len - filled)
                errors   = sum(1 for r in results if r.get("error"))
                print(
                    f"\r  [{bar}] {pct:5.1f}%  {completed}/{total}  "
                    f"ETA {eta_s:.0f}s  errors: {errors}",
                    end="",
                    flush=True,
                )

    elapsed = time.time() - t0
    errors  = sum(1 for r in results if r.get("error"))
    print(f"\n\n  ✅  Done in {elapsed:.1f}s  |  {total - errors} successful  |  {errors} errors\n")

    # ── 4. Score ──────────────────────────────────────────────────────────────
    results = _add_composite_scores(results)
    results.sort(key=lambda r: r.get("composite_score", 0.0), reverse=True)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Save CSV
# ─────────────────────────────────────────────────────────────────────────────

def _save_csv(results: list[dict], path: Path) -> None:
    if not results:
        return
    keys = [k for k in results[0].keys() if not k.startswith("param_entry_level")
            and not k.startswith("param_invest_per_level") and not k.startswith("param_entry_quant")]
    # Include a readable param summary instead
    rows = []
    for r in results:
        row = {k: r.get(k, "") for k in keys}
        row["params_summary"] = _param_summary(r)
        rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _param_summary(r: dict) -> str:
    """Build a short human-readable param string."""
    strat = r.get("strategy", "")
    parts = []
    if strat == "GRID":
        parts = [
            f"lvl={r.get('param_num_levels', '')}",
            f"spc={str(r.get('param_spacing', ''))[:3]}",
            f"inv={r.get('param_invest_per_level_usd', '')}",
        ]
    elif strat == "DCA":
        parts = [
            f"int={r.get('param_buy_interval_hours', '')}h",
            f"inv={r.get('param_invest_per_buy_usd', '')}",
            f"hold={r.get('param_hold_days', '')}d",
            f"exit={r.get('param_exit_type', '')}",
        ]
    elif strat == "PLA":
        parts = [
            f"f={r.get('param_fast_ema', '')}",
            f"s={r.get('param_slow_ema', '')}",
            f"exit={r.get('param_exit_type', '')}",
            f"tp={r.get('param_take_profit_pct', '')}%",
        ]
    return " | ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# HTML Report
# ─────────────────────────────────────────────────────────────────────────────

def _color_val(val: float, lo: float, hi: float, invert: bool = False) -> str:
    """Return a CSS color string (red→yellow→green gradient)."""
    if hi - lo < 1e-10:
        return "#555"
    t = (val - lo) / (hi - lo)
    if invert:
        t = 1.0 - t
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        r = 220
        g = int(100 + t * 2 * 120)
        b = 60
    else:
        r = int(220 - (t - 0.5) * 2 * 120)
        g = 220
        b = 60
    return f"rgb({r},{g},{b})"


def _fmt(val: Any, decimals: int = 2, suffix: str = "") -> str:
    if val is None or val == "" or (isinstance(val, float) and not math.isfinite(val)):
        return "—"
    return f"{val:.{decimals}f}{suffix}"


def generate_html_report(results: list[dict], path: Path, start: date, end: date) -> None:
    valid = [r for r in results if r.get("num_trades", 0) > 0 and not r.get("error")]
    if not valid:
        print("No valid results to report.")
        return

    # ── Pre-compute stat ranges for coloring ──────────────────────────────────
    def _range(col: str) -> tuple[float, float]:
        vals = [r[col] for r in valid if isinstance(r.get(col), (int, float))]
        return (min(vals), max(vals)) if vals else (0.0, 1.0)

    ret_lo,    ret_hi    = _range("total_return_pct")
    sharpe_lo, sharpe_hi = _range("sharpe_ratio")
    sor_lo,    sor_hi    = _range("sortino_ratio")
    dd_lo,     dd_hi     = _range("max_drawdown_pct")
    cal_lo,    cal_hi    = _range("calmar_ratio")
    pf_lo,     pf_hi     = _range("profit_factor")
    wr_lo,     wr_hi     = _range("win_rate")
    sc_lo,     sc_hi     = _range("composite_score")

    # ── Top performers ────────────────────────────────────────────────────────
    top_overall = valid[:10]

    best_by_strategy: dict[str, dict] = {}
    for strat in ["GRID", "DCA", "PLA"]:
        subset = [r for r in valid if r["strategy"] == strat]
        if subset:
            best_by_strategy[strat] = max(subset, key=lambda x: x["composite_score"])

    best_by_symbol: dict[str, dict] = {}
    symbols_seen = sorted({r["symbol"] for r in valid})
    for sym in symbols_seen:
        subset = [r for r in valid if r["symbol"] == sym]
        if subset:
            best_by_symbol[sym] = max(subset, key=lambda x: x["composite_score"])

    # ── Table rows HTML ───────────────────────────────────────────────────────
    def _row_html(r: dict, rank: int) -> str:
        sc   = r.get("composite_score", 0.0)
        ret  = r.get("total_return_pct", 0.0)
        sh   = r.get("sharpe_ratio", 0.0)
        so   = r.get("sortino_ratio", 0.0)
        dd   = r.get("max_drawdown_pct", 0.0)
        cal  = r.get("calmar_ratio", 0.0)
        pf   = r.get("profit_factor", 0.0)
        wr   = r.get("win_rate", 0.0)
        nt   = r.get("num_trades", 0)
        ann  = r.get("annualised_return_pct", 0.0)
        strat_badge = {
            "GRID": "#3b82f6", "DCA": "#f59e0b", "PLA": "#10b981"
        }.get(r["strategy"], "#888")

        ret_sign = "+" if ret >= 0 else ""
        rank_badge = ""
        if rank == 1:
            rank_badge = " 🥇"
        elif rank == 2:
            rank_badge = " 🥈"
        elif rank == 3:
            rank_badge = " 🥉"

        return f"""
        <tr data-strategy="{r['strategy']}" data-symbol="{r['symbol']}">
          <td class="rank">#{rank}{rank_badge}</td>
          <td><span class="badge" style="background:{strat_badge}">{r['strategy']}</span></td>
          <td class="sym">{r['symbol']}</td>
          <td class="params-cell" title="{_param_summary(r)}">{_param_summary(r)}</td>
          <td style="color:{_color_val(sc, sc_lo, sc_hi)};font-weight:600">{_fmt(sc, 3)}</td>
          <td style="color:{_color_val(ret, ret_lo, ret_hi)}">{ret_sign}{_fmt(ret)}%</td>
          <td style="color:{_color_val(ann, ret_lo, ret_hi)}">{ret_sign}{_fmt(ann)}%</td>
          <td style="color:{_color_val(sh,  sharpe_lo, sharpe_hi)}">{_fmt(sh, 3)}</td>
          <td style="color:{_color_val(so,  sor_lo, sor_hi)}">{_fmt(so, 3)}</td>
          <td style="color:{_color_val(cal, cal_lo, cal_hi)}">{_fmt(cal, 3)}</td>
          <td style="color:{_color_val(dd,  dd_lo, dd_hi, invert=True)}">{_fmt(dd)}%</td>
          <td style="color:{_color_val(pf,  pf_lo, pf_hi)}">{_fmt(pf, 2)}×</td>
          <td style="color:{_color_val(wr,  wr_lo, wr_hi)}">{_fmt(wr)}%</td>
          <td>{nt}</td>
        </tr>"""

    # Only top 200 rows in HTML table (CSV has all)
    display_rows = valid[:200]
    table_rows_html = "\n".join(
        _row_html(r, i + 1) for i, r in enumerate(display_rows)
    )

    # ── Summary cards ─────────────────────────────────────────────────────────
    def _card(title: str, r: dict, color: str) -> str:
        ret  = r.get("total_return_pct", 0.0)
        sign = "+" if ret >= 0 else ""
        return f"""
        <div class="card" style="border-top: 3px solid {color}">
          <div class="card-title">{title}</div>
          <div class="card-sym">{r['symbol']} — {r['strategy']}</div>
          <div class="card-params">{_param_summary(r)}</div>
          <div class="card-metrics">
            <span class="metric-pill">Score: <b>{_fmt(r.get('composite_score',0),3)}</b></span>
            <span class="metric-pill">Return: <b style="color:{_color_val(ret,ret_lo,ret_hi)}">{sign}{_fmt(ret)}%</b></span>
            <span class="metric-pill">Sharpe: <b>{_fmt(r.get('sharpe_ratio',0),3)}</b></span>
            <span class="metric-pill">Sortino: <b>{_fmt(r.get('sortino_ratio',0),3)}</b></span>
            <span class="metric-pill">MDD: <b>{_fmt(r.get('max_drawdown_pct',0))}%</b></span>
            <span class="metric-pill">Trades: <b>{r.get('num_trades',0)}</b></span>
          </div>
        </div>"""

    strat_cards = "\n".join(
        _card(f"🏆 Best {strat}", best_by_strategy[strat], c)
        for strat, c in [("GRID", "#3b82f6"), ("DCA", "#f59e0b"), ("PLA", "#10b981")]
        if strat in best_by_strategy
    )
    sym_cards = "\n".join(
        _card(f"📈 Best {sym}", best_by_symbol[sym], "#a855f7")
        for sym in symbols_seen
        if sym in best_by_symbol
    )

    # ── Score weights info ─────────────────────────────────────────────────────
    weights_html = " | ".join(
        f"<b>{k}</b>: {int(v*100)}%"
        for k, v in SCORE_WEIGHTS.items()
    )

    # ── Stats summary ─────────────────────────────────────────────────────────
    total_runs   = len(results)
    valid_runs   = len(valid)
    error_runs   = sum(1 for r in results if r.get("error"))
    zero_trade   = sum(1 for r in results if r.get("num_trades", 0) == 0 and not r.get("error"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradeVed Crypto Optimizer Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f1117; color: #e2e8f0; font-family: 'Inter', system-ui, sans-serif; }}
  a {{ color: #60a5fa; }}

  /* ── Header ── */
  .header {{ background: linear-gradient(135deg, #1a1f2e 0%, #0f1117 100%);
             border-bottom: 1px solid #2d3748; padding: 28px 40px; }}
  .header h1 {{ font-size: 1.8rem; font-weight: 700; color: #f0f4f8;
                background: linear-gradient(90deg,#60a5fa,#a855f7); -webkit-background-clip:text;
                -webkit-text-fill-color:transparent; }}
  .header .meta {{ margin-top: 6px; color: #94a3b8; font-size: 0.85rem; }}
  .header .stats-row {{ display:flex; gap: 24px; margin-top: 14px; }}
  .stat-chip {{ background: #1e2a3a; padding: 6px 14px; border-radius: 20px;
                font-size: 0.8rem; color: #94a3b8; border: 1px solid #2d3748; }}
  .stat-chip b {{ color: #f0f4f8; }}

  /* ── Layout ── */
  .container {{ max-width: 1600px; margin: 0 auto; padding: 0 20px 40px; }}
  section {{ margin-top: 36px; }}
  h2 {{ font-size: 1.1rem; font-weight: 600; color: #cbd5e1; margin-bottom: 16px;
        display: flex; align-items: center; gap: 8px; }}
  h2::before {{ content: ''; display: inline-block; width: 4px; height: 18px;
                background: #60a5fa; border-radius: 2px; }}

  /* ── Cards ── */
  .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 16px; }}
  .card {{ background: #1a1f2e; border-radius: 10px; padding: 18px;
           border: 1px solid #2d3748; transition: border-color .2s; }}
  .card:hover {{ border-color: #4a5568; }}
  .card-title {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: .05em;
                 color: #64748b; margin-bottom: 4px; }}
  .card-sym {{ font-size: 1rem; font-weight: 700; color: #f0f4f8; }}
  .card-params {{ font-size: 0.75rem; color: #94a3b8; margin: 6px 0 10px;
                  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .card-metrics {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .metric-pill {{ background: #0f1117; border: 1px solid #2d3748; border-radius: 12px;
                  padding: 3px 10px; font-size: 0.75rem; color: #94a3b8; }}

  /* ── Filter bar ── */
  .filter-bar {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:16px; }}
  .filter-bar select, .filter-bar input {{
    background: #1a1f2e; border: 1px solid #2d3748; color: #e2e8f0;
    padding: 7px 12px; border-radius: 6px; font-size: 0.85rem; outline: none;
  }}
  .filter-bar label {{ font-size: 0.85rem; color: #94a3b8; }}
  #count-label {{ font-size: 0.8rem; color: #64748b; margin-left: auto; }}

  /* ── Table ── */
  .table-wrap {{ overflow-x: auto; border-radius: 10px; border: 1px solid #2d3748; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; min-width: 1100px; }}
  thead th {{
    background: #161c2a; color: #94a3b8; font-weight: 600;
    padding: 10px 12px; text-align: right; cursor: pointer;
    border-bottom: 1px solid #2d3748; white-space: nowrap;
    user-select: none; position: sticky; top: 0; z-index: 1;
  }}
  thead th:first-child, thead th:nth-child(2),
  thead th:nth-child(3), thead th:nth-child(4) {{ text-align: left; }}
  thead th:hover {{ color: #60a5fa; }}
  thead th.sort-asc::after  {{ content: " ↑"; color: #60a5fa; }}
  thead th.sort-desc::after {{ content: " ↓"; color: #60a5fa; }}
  tbody tr {{ border-bottom: 1px solid #1e2535; transition: background .1s; }}
  tbody tr:hover {{ background: #1a2233; }}
  td {{ padding: 9px 12px; text-align: right; color: #cbd5e1; }}
  td:first-child, td:nth-child(2),
  td:nth-child(3), td:nth-child(4) {{ text-align: left; }}
  .rank {{ color: #64748b; font-size: 0.78rem; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
            font-size: 0.72rem; font-weight: 700; color: #fff; }}
  .sym {{ font-weight: 600; color: #e2e8f0; }}
  .params-cell {{ max-width: 220px; overflow: hidden; text-overflow: ellipsis;
                  white-space: nowrap; color: #94a3b8; font-size: 0.75rem; }}

  /* ── Weights ── */
  .weights-note {{ background:#161c2a; border:1px solid #2d3748; border-radius:8px;
                   padding:12px 16px; font-size:0.8rem; color:#94a3b8; margin-bottom:20px; }}

  /* ── Footer ── */
  .footer {{ text-align:center; padding:30px; color:#4a5568; font-size:0.78rem; border-top:1px solid #1e2535; margin-top:40px; }}

  @media (max-width:768px) {{
    .header {{ padding: 20px; }}
    .cards-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>TradeVed Crypto Optimizer</h1>
  <div class="meta">Period: <b>{start}</b> → <b>{end}</b> &nbsp;|&nbsp; Capital: <b>${CAPITAL:,.0f}</b>
    &nbsp;|&nbsp; Fee: <b>{FEE_PCT*100:.1f}%</b> &nbsp;|&nbsp;
    Generated: <b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</b>
  </div>
  <div class="stats-row">
    <span class="stat-chip">Total runs: <b>{total_runs}</b></span>
    <span class="stat-chip">Valid: <b>{valid_runs}</b></span>
    <span class="stat-chip">Errors: <b>{error_runs}</b></span>
    <span class="stat-chip">Zero-trade: <b>{zero_trade}</b></span>
    <span class="stat-chip">Symbols: <b>{len(symbols_seen)}</b></span>
  </div>
</div>

<div class="container">

  <!-- ── Best by Strategy ── -->
  <section>
    <h2>Best Parameters by Strategy</h2>
    <div class="cards-grid">{strat_cards}</div>
  </section>

  <!-- ── Best by Symbol ── -->
  <section>
    <h2>Best Configuration by Symbol</h2>
    <div class="cards-grid">{sym_cards}</div>
  </section>

  <!-- ── Full Leaderboard ── -->
  <section>
    <h2>Full Leaderboard (top {min(200,valid_runs)} of {valid_runs} valid runs)</h2>

    <div class="weights-note">
      📊 <b>Composite Score</b> = {weights_html}
      &nbsp;&nbsp;|&nbsp;&nbsp;
      All metrics are min-max normalised across all valid runs. Max drawdown is <i>inverted</i> (lower = better).
    </div>

    <div class="filter-bar">
      <label>Strategy:</label>
      <select id="filter-strategy" onchange="applyFilters()">
        <option value="">All</option>
        <option>GRID</option><option>DCA</option><option>PLA</option>
      </select>
      <label>Symbol:</label>
      <select id="filter-symbol" onchange="applyFilters()">
        <option value="">All</option>
        {"".join(f"<option>{s}</option>" for s in symbols_seen)}
      </select>
      <label>Min trades:</label>
      <input id="filter-trades" type="number" value="1" min="0" style="width:70px" onchange="applyFilters()">
      <label>Min return %:</label>
      <input id="filter-return" type="number" value="" style="width:80px" placeholder="any" onchange="applyFilters()">
      <span id="count-label"></span>
    </div>

    <div class="table-wrap">
      <table id="results-table">
        <thead>
          <tr>
            <th onclick="sortTable(0)">Rank</th>
            <th onclick="sortTable(1)">Strategy</th>
            <th onclick="sortTable(2)">Symbol</th>
            <th onclick="sortTable(3)">Parameters</th>
            <th onclick="sortTable(4)">Score ▼</th>
            <th onclick="sortTable(5)">Return %</th>
            <th onclick="sortTable(6)">Ann. Return %</th>
            <th onclick="sortTable(7)">Sharpe</th>
            <th onclick="sortTable(8)">Sortino</th>
            <th onclick="sortTable(9)">Calmar</th>
            <th onclick="sortTable(10)">Max DD %</th>
            <th onclick="sortTable(11)">Profit Factor</th>
            <th onclick="sortTable(12)">Win Rate %</th>
            <th onclick="sortTable(13)">Trades</th>
          </tr>
        </thead>
        <tbody id="table-body">
{table_rows_html}
        </tbody>
      </table>
    </div>
  </section>

</div>

<div class="footer">
  TradeVed Backtester &nbsp;·&nbsp; Crypto Optimizer &nbsp;·&nbsp;
  {valid_runs} valid runs across {len(symbols_seen)} symbols &nbsp;·&nbsp;
  {start} → {end}
</div>

<script>
// ── Sort ──────────────────────────────────────────────────────────────────────
let sortCol = 4, sortDir = -1;

function sortTable(col) {{
  if (sortCol === col) sortDir *= -1;
  else {{ sortCol = col; sortDir = -1; }}
  document.querySelectorAll('thead th').forEach((th, i) => {{
    th.classList.remove('sort-asc','sort-desc');
    if (i === col) th.classList.add(sortDir === -1 ? 'sort-desc' : 'sort-asc');
  }});
  const tbody = document.getElementById('table-body');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {{
    const av = a.cells[col]?.innerText.replace(/[^0-9.+\\-]/g,'') || '';
    const bv = b.cells[col]?.innerText.replace(/[^0-9.+\\-]/g,'') || '';
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return (an - bn) * sortDir;
    return av.localeCompare(bv) * sortDir;
  }});
  rows.forEach(r => tbody.appendChild(r));
  updateCount();
}}

// ── Filter ─────────────────────────────────────────────────────────────────────
function applyFilters() {{
  const strat   = document.getElementById('filter-strategy').value;
  const sym     = document.getElementById('filter-symbol').value;
  const minT    = parseInt(document.getElementById('filter-trades').value) || 0;
  const minRet  = parseFloat(document.getElementById('filter-return').value);

  document.querySelectorAll('#table-body tr').forEach(row => {{
    const rowStrat = row.dataset.strategy;
    const rowSym   = row.dataset.symbol;
    const trades   = parseInt(row.cells[13]?.innerText) || 0;
    const ret      = parseFloat(row.cells[5]?.innerText.replace('%','')) || 0;

    const show = (
      (!strat  || rowStrat === strat) &&
      (!sym    || rowSym   === sym)   &&
      trades >= minT &&
      (isNaN(minRet) || ret >= minRet)
    );
    row.style.display = show ? '' : 'none';
  }});
  updateCount();
}}

function updateCount() {{
  const visible = document.querySelectorAll('#table-body tr:not([style*="none"])').length;
  document.getElementById('count-label').textContent = `Showing ${{visible}} runs`;
}}

// Init
updateCount();
</script>
</body>
</html>
"""

    path.write_text(html, encoding="utf-8")
    print(f"  📄  HTML report → {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Print console summary
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(results: list[dict]) -> None:
    valid = [r for r in results if r.get("num_trades", 0) > 0 and not r.get("error")]
    if not valid:
        print("No valid results.")
        return

    # ── Top 10 overall ─────────────────────────────────────────────────────────
    print("\n" + "═"*90)
    print("  TOP 10 CONFIGURATIONS — COMPOSITE SCORE")
    print("═"*90)
    print(f"  {'Rank':<5} {'Strategy':<8} {'Symbol':<12} {'Score':>7} {'Return%':>9} "
          f"{'Sharpe':>8} {'Sortino':>8} {'MDD%':>7} {'Trades':>7}  Parameters")
    print("─"*90)
    for i, r in enumerate(valid[:10], 1):
        ret = r.get('total_return_pct', 0)
        sign = "+" if ret >= 0 else ""
        print(
            f"  {i:<5} {r['strategy']:<8} {r['symbol']:<12} "
            f"{r.get('composite_score',0):>7.4f} "
            f"{sign}{ret:>8.2f}% "
            f"{r.get('sharpe_ratio',0):>8.3f} "
            f"{r.get('sortino_ratio',0):>8.3f} "
            f"{r.get('max_drawdown_pct',0):>7.2f}% "
            f"{r.get('num_trades',0):>7}  "
            f"{_param_summary(r)}"
        )

    # ── Best per strategy ──────────────────────────────────────────────────────
    for strat in ["GRID", "DCA", "PLA"]:
        subset = [r for r in valid if r["strategy"] == strat]
        if not subset:
            continue
        best = max(subset, key=lambda x: x["composite_score"])
        ret = best.get("total_return_pct", 0)
        sign = "+" if ret >= 0 else ""
        print(f"\n  🏆 BEST {strat}:")
        print(f"     Symbol  : {best['symbol']}")
        print(f"     Params  : {_param_summary(best)}")
        print(f"     Score   : {best.get('composite_score',0):.4f}")
        print(f"     Return  : {sign}{ret:.2f}%  |  Ann: {sign}{best.get('annualised_return_pct',0):.2f}%")
        print(f"     Sharpe  : {best.get('sharpe_ratio',0):.3f}  |  Sortino: {best.get('sortino_ratio',0):.3f}  |  Calmar: {best.get('calmar_ratio',0):.3f}")
        print(f"     Max DD  : {best.get('max_drawdown_pct',0):.2f}%  |  Win Rate: {best.get('win_rate',0):.1f}%  |  Trades: {best.get('num_trades',0)}")

    print("\n" + "═"*90)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Crypto strategy parameter optimizer",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help=f"Space-separated symbols (default: {' '.join(DEFAULT_SYMBOLS)})",
    )
    p.add_argument(
        "--strategies", nargs="+", default=["GRID", "DCA", "PLA"],
        choices=["GRID", "DCA", "PLA"],
        help="Strategies to test (default: GRID DCA PLA)",
    )
    p.add_argument(
        "--start", type=lambda s: date.fromisoformat(s),
        default=DEFAULT_START, help="Start date YYYY-MM-DD",
    )
    p.add_argument(
        "--end", type=lambda s: date.fromisoformat(s),
        default=DEFAULT_END, help="End date YYYY-MM-DD",
    )
    p.add_argument(
        "--capital", type=float, default=CAPITAL, help="Starting capital in USD",
    )
    p.add_argument(
        "--workers", type=int, default=4, help="Parallel worker threads (default: 4)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # Override globals if capital changed
    global CAPITAL
    CAPITAL = args.capital

    strategies = [s.upper() for s in args.strategies]
    results    = run_optimizer(
        symbols    = args.symbols,
        strategies = strategies,
        start      = args.start,
        end        = args.end,
        workers    = args.workers,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = OUTPUT_DIR / f"results_{ts}.csv"
    html_path = OUTPUT_DIR / f"report_{ts}.html"

    # Save outputs
    print("\n💾  Saving outputs …")
    _save_csv(results, csv_path)
    print(f"  📊  CSV results  → {csv_path}")
    generate_html_report(results, html_path, args.start, args.end)

    _print_summary(results)

    print(f"\n🎉  Open the report:\n    file:///{html_path.as_posix()}\n")


if __name__ == "__main__":
    main()
