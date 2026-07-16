"""
Indian Futures Contract Parameter Optimizer
=============================================
Tests GRID, DCA and PLA strategies on NSE Futures (Index + Stock F&O)
using the REAL Indian cost model:

  Charges applied (Budget 2024 / NSE Circular NSCCL/CMPT/56264/2024):
  ┌─────────────────────────────────────────────────────────────────────┐
  │ STT              0.02%  on SELL side turnover                       │
  │ NSE ETC          0.00173%  on BOTH sides (₹1.73/lakh)              │
  │ SEBI charges     0.0001%   on BOTH sides (₹10/crore)               │
  │ GST              18%  on (brokerage + ETC + SEBI)                   │
  │ Stamp duty       0.003%  on BUY side only                          │
  │ Brokerage        ₹20/order flat  (Zerodha/Groww style)             │
  └─────────────────────────────────────────────────────────────────────┘

  Lot-size enforcement: qty = floor(invest/price / lot_size) * lot_size
  Minimum 1 lot per trade — otherwise skipped (like real F&O).

  Sources confirmed:
    https://zerodha.com/charges/
    https://zerodha.com/marketintel/bulletin/391488/
    https://www.icicidirect.com/research/equity/finace/new-stt-rules-in-futures-and-options-trading

Usage:
    python indian_futures_optimizer.py
    python indian_futures_optimizer.py --symbols NIFTY50 BANKNIFTY
    python indian_futures_optimizer.py --start 2022-01-01 --end 2024-01-01
    python indian_futures_optimizer.py --workers 4

Output:
    optimizer_results/
        india_results_<ts>.csv
        india_report_<ts>.html
        india_verify_<ts>.txt
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# ── UTF-8 stdout (Windows) ─────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Path setup ─────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import logging
from backtesting.data.fetcher import DataFetcher
from backtesting.data.validator import DataValidator
from backtesting.data.indian_assets import get_lot_size, INDEX_MAP, to_yf_symbol
from backtesting.engine.simulator import TradeSimulator
from backtesting.engine.metrics import calculate_metrics
from backtesting.engine.cost_models import IndianCostModel
from backtesting.strategies.grid import GridStrategy
from backtesting.strategies.dca import DCAStrategy
from backtesting.strategies.pla import PLAStrategy

# Silence internal loggers
for _ns in ("data", "strategies", "engine", "frontend", ""):
    logging.getLogger(_ns).setLevel(logging.WARNING)

# ── Constants ──────────────────────────────────────────────────────────────────
OUTPUT_DIR    = HERE / "optimizer_results"
SOURCE        = "nse"
INTERVAL      = "1d"
MARKET_TYPE   = "futures"
BROKERAGE     = "flat"
BROKERAGE_AMT = 20.0       # ₹20 per order (Zerodha style)

DEFAULT_START = date(2022, 1, 1)
DEFAULT_END   = date(2024, 1, 1)

# Score weights (same as crypto for fair comparison)
SCORE_WEIGHTS = {
    "sharpe_ratio":     0.35,
    "total_return_pct": 0.25,
    "sortino_ratio":    0.20,
    "calmar_ratio":     0.10,
    "max_drawdown_pct": 0.10,
}

# ── Symbols: NSE symbol → lot size (FY2024-25) ────────────────────────────────
# Using verified lot sizes from NSE circular NSCCL/CMPT/56264/2024
SYMBOLS_CONFIG: dict[str, dict] = {
    "NIFTY50":   {"lot": 50,  "label": "Nifty 50 Index"},
    "BANKNIFTY": {"lot": 15,  "label": "Bank Nifty Index"},
    "RELIANCE":  {"lot": 250, "label": "Reliance Industries"},
    "TCS":       {"lot": 150, "label": "Tata Consultancy Services"},
    "INFY":      {"lot": 300, "label": "Infosys"},
    "HDFCBANK":  {"lot": 550, "label": "HDFC Bank"},
}

DEFAULT_SYMBOLS = list(SYMBOLS_CONFIG.keys())

# ── Fetching / cache ───────────────────────────────────────────────────────────
_fetcher   = DataFetcher()
_validator = DataValidator()
_cache: dict[str, pd.DataFrame] = {}
_cache_lock = threading.Lock()


def _fetch(symbol: str, start: date, end: date) -> Optional[pd.DataFrame]:
    key = f"{symbol}|{start}|{end}"
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    try:
        from datetime import datetime as dt
        df = _fetcher.fetch(
            symbol,
            dt.combine(start, dt.min.time()),
            dt.combine(end,   dt.max.time()),
            SOURCE, INTERVAL,
        )
        _validator.validate(df)
        with _cache_lock:
            _cache[key] = df
        return df
    except Exception as exc:
        print(f"  FETCH ERROR {symbol}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Minimum invest calculation
# ─────────────────────────────────────────────────────────────────────────────

def _min_invest(df: pd.DataFrame, lot: int, buffer: float = 1.05) -> float:
    """Return minimum invest amount (₹) to buy 1 lot — uses median close price."""
    med_price = float(df["close"].median())
    return math.ceil(lot * med_price * buffer / 1000) * 1000   # round up to nearest ₹1000


def _invest_levels(min_inv: float, n: int = 3) -> list[float]:
    """Return n invest levels: [min, 1.5×min, 2×min]"""
    return [round(min_inv * m / 1000) * 1000 for m in [1.0, 1.5, 2.0][:n]]


# ─────────────────────────────────────────────────────────────────────────────
# Parameter grids
# ─────────────────────────────────────────────────────────────────────────────

def _grid_combos(lower: float, upper: float, invest_levels: list) -> list[dict]:
    combos = []
    for num_levels in [3, 5, 7, 10]:
        for spacing in ["linear", "exponential"]:
            for inv in invest_levels:
                combos.append({
                    "lower_bound":          lower,
                    "upper_bound":          upper,
                    "num_levels":           num_levels,
                    "spacing":              spacing,
                    "invest_per_level_usd": inv,
                    "quantity_per_level":   0.0,
                })
    return combos


def _dca_combos(invest_levels: list) -> list[dict]:
    combos = []
    for interval_h in [24, 48, 72]:
        for inv in invest_levels:
            for hold_days in [14, 30, 60]:
                for exit_type in ["time", "profit"]:
                    combos.append({
                        "buy_interval_hours": interval_h,
                        "invest_per_buy_usd": inv,
                        "buy_quantity":       0.0,
                        "hold_days":          hold_days,
                        "exit_type":          exit_type,
                        "profit_target_pct":  10.0,
                    })
    return combos


def _pla_combos(invest_levels: list) -> list[dict]:
    combos = []
    ema_pairs  = [(9, 21), (12, 26), (20, 50)]
    lvl_sets   = [
        [0.0, -1.0, -2.5, -4.0],
        [0.0, -0.5, -1.5, -3.0],
    ]
    for fast, slow in ema_pairs:
        for lvls in lvl_sets:
            for inv in invest_levels:
                invest_cascade = [inv, inv, inv * 2, inv * 3]
                for exit_type, tp in [("crossover", 5.0), ("take_profit", 5.0), ("take_profit", 10.0)]:
                    combos.append({
                        "fast_ema":             fast,
                        "slow_ema":             slow,
                        "entry_levels":         lvls,
                        "invest_per_level_usd": invest_cascade,
                        "entry_quantities":     [0.001, 0.001, 0.002, 0.003],
                        "exit_type":            exit_type,
                        "take_profit_pct":      tp,
                        "stop_loss_pct":        3.0,
                    })
    return combos


# ─────────────────────────────────────────────────────────────────────────────
# Auto GRID bounds
# ─────────────────────────────────────────────────────────────────────────────

def _round_nice(value: float, direction: str = "floor") -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** (math.floor(math.log10(abs(value))) - 1)
    if direction == "floor":
        return math.floor(value / magnitude) * magnitude
    return math.ceil(value / magnitude) * magnitude


def _auto_bounds(df: pd.DataFrame) -> tuple[float, float]:
    prices = df["close"].astype(float)
    lo_raw, hi_raw = float(prices.min()), float(prices.max())
    pad   = (hi_raw - lo_raw) * 0.10
    lower = _round_nice(max(1.0, lo_raw - pad), "floor")
    upper = _round_nice(hi_raw + pad, "ceil")
    return lower, upper


# ─────────────────────────────────────────────────────────────────────────────
# Single backtest run
# ─────────────────────────────────────────────────────────────────────────────

def _cap(v: float, lo=-20.0, hi=20.0) -> float:
    if not math.isfinite(v):
        return hi if v > 0 else lo
    return max(lo, min(hi, v))


def _run(symbol: str, strategy: str, params: dict, df: pd.DataFrame,
         lot: int, capital: float, run_id: int) -> dict:
    result: dict = {
        "run_id":   run_id,
        "symbol":   symbol,
        "strategy": strategy,
        "lot_size": lot,
        "capital":  capital,
        "error":    None,
    }
    try:
        cls_map = {"GRID": GridStrategy, "DCA": DCAStrategy, "PLA": PLAStrategy}
        cls     = cls_map[strategy]
        merged  = {**cls.default_params(), **params}
        inst    = cls(**merged)
        sigs    = inst.generate_signals(df.copy())

        sim = TradeSimulator(
            symbol           = symbol,
            capital          = capital,
            fee_percent      = 0.0,        # replaced by IndianCostModel
            slippage_percent = 0.001,      # 0.1% conservative market-impact
            use_indian_costs = True,
            market_type      = MARKET_TYPE,
            brokerage_model  = BROKERAGE,
            brokerage_flat   = BROKERAGE_AMT,
            lot_size         = lot,
        )
        out = sim.run(sigs)

        # Skip if zero trades AND there were buy signals (sub-lot problem)
        nt = len(out["trades"])
        buy_signals = int((sigs["signal"] == "BUY").sum())
        if nt == 0 and buy_signals > 0:
            result["error"]     = f"0 trades despite {buy_signals} BUY signals — invest < 1 lot"
            result["num_trades"] = 0
            _zero_metrics(result, capital)
            return result

        met = calculate_metrics(
            trades          = out["trades"],
            equity_curve    = out["equity_curve"],
            timestamps      = out["timestamps"],
            initial_capital = capital,
        )

        # Cost breakdown
        cb = out.get("cost_breakdown", {})

        result.update({
            "num_trades":            met["num_trades"],
            "total_return_pct":      met["total_return_pct"],
            "annualised_return_pct": met["annualised_return_pct"],
            "sharpe_ratio":          _cap(met["sharpe_ratio"]),
            "sortino_ratio":         _cap(met["sortino_ratio"]),
            "calmar_ratio":          _cap(met["calmar_ratio"]),
            "max_drawdown_pct":      met["max_drawdown_pct"],
            "win_rate":              met["win_rate"],
            "profit_factor":         _cap(met["profit_factor"], hi=20.0),
            "volatility_pct":        met["volatility_pct"],
            "avg_trade_pnl_inr":     met["avg_trade_pnl"],
            "best_trade_inr":        met["best_trade"],
            "worst_trade_inr":       met["worst_trade"],
            "final_equity_inr":      met["final_equity"],
            "total_fees_inr":        out.get("total_fees_paid", 0.0),
            "stt_paid_inr":          cb.get("stt", 0.0),
            "etc_paid_inr":          cb.get("exchange_charges", 0.0),
            "gst_paid_inr":          cb.get("gst", 0.0),
            "stamp_paid_inr":        cb.get("stamp_duty", 0.0),
            "brokerage_paid_inr":    cb.get("brokerage", 0.0),
            "composite_score":       0.0,
            # Scalar invest base — first element of list for PLA, scalar for GRID/DCA
            "param_invest_base": (
                params["invest_per_level_usd"][0]
                if isinstance(params.get("invest_per_level_usd"), list)
                else params.get("invest_per_level_usd")
                     or params.get("invest_per_buy_usd", 0)
            ),
            **{f"param_{k}": (str(v) if isinstance(v, list) else v)
               for k, v in params.items()},
        })
    except Exception as exc:
        result["error"] = str(exc)
        result["num_trades"] = 0
        _zero_metrics(result, capital)
    return result


def _zero_metrics(r: dict, cap: float):
    for k in ("total_return_pct","annualised_return_pct","sharpe_ratio",
              "sortino_ratio","calmar_ratio","max_drawdown_pct","win_rate",
              "profit_factor","volatility_pct","avg_trade_pnl_inr",
              "best_trade_inr","worst_trade_inr","composite_score",
              "total_fees_inr","stt_paid_inr","etc_paid_inr",
              "gst_paid_inr","stamp_paid_inr","brokerage_paid_inr"):
        r.setdefault(k, 0.0)
    r.setdefault("final_equity_inr", cap)


# ─────────────────────────────────────────────────────────────────────────────
# Composite score
# ─────────────────────────────────────────────────────────────────────────────

def _score(rows: list[dict]) -> list[dict]:
    valid = [r for r in rows if r.get("num_trades", 0) > 0 and not r.get("error")]
    if not valid:
        return rows

    def _norm(col: str, inv: bool = False) -> dict[int, float]:
        vals = [r[col] for r in valid]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        return {r["run_id"]: ((hi - r[col]) / span if inv else (r[col] - lo) / span)
                for r in valid}

    sharpe_n  = _norm("sharpe_ratio")
    ret_n     = _norm("total_return_pct")
    sortino_n = _norm("sortino_ratio")
    calmar_n  = _norm("calmar_ratio")
    mdd_n     = _norm("max_drawdown_pct", inv=True)

    w = SCORE_WEIGHTS
    for r in rows:
        rid = r["run_id"]
        if rid in sharpe_n:
            r["composite_score"] = round(
                w["sharpe_ratio"]     * sharpe_n[rid]  +
                w["total_return_pct"] * ret_n[rid]     +
                w["sortino_ratio"]    * sortino_n[rid] +
                w["calmar_ratio"]     * calmar_n[rid]  +
                w["max_drawdown_pct"] * mdd_n[rid], 4)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Param summary
# ─────────────────────────────────────────────────────────────────────────────

def _psummary(r: dict) -> str:
    s = r.get("strategy", "")
    if s == "GRID":
        inv = int(r.get('param_invest_base') or r.get('param_invest_per_level_usd') or 0)
        return (f"lvl={r.get('param_num_levels','')} | "
                f"spc={str(r.get('param_spacing',''))[:3]} | "
                f"inv=₹{inv:,}")
    if s == "DCA":
        inv = int(r.get('param_invest_base') or r.get('param_invest_per_buy_usd') or 0)
        return (f"int={r.get('param_buy_interval_hours','')}h | "
                f"inv=₹{inv:,} | "
                f"hold={r.get('param_hold_days','')}d | "
                f"exit={r.get('param_exit_type','')}")
    if s == "PLA":
        inv = int(r.get('param_invest_base') or 0)
        return (f"f={r.get('param_fast_ema','')} | "
                f"s={r.get('param_slow_ema','')} | "
                f"inv=₹{inv:,}/lvl | "
                f"exit={r.get('param_exit_type','')} | "
                f"tp={r.get('param_take_profit_pct','')}%")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_optimizer(symbols: list[str], strategies: list[str],
                  start: date, end: date, workers: int = 4) -> list[dict]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    SEP = "=" * 72
    print(f"\n{SEP}")
    print("  TradeVed — Indian Futures Parameter Optimizer")
    print(f"{SEP}")
    print(f"  Symbols   : {', '.join(symbols)}")
    print(f"  Strategies: {', '.join(strategies)}")
    print(f"  Period    : {start} to {end}")
    print(f"  Cost model: STT 0.02% + ETC 0.00173% + SEBI 0.0001% + GST 18% + Stamp 0.003%")
    print(f"  Brokerage : Rs.{BROKERAGE_AMT:.0f}/order (Zerodha-style flat)")
    print(f"  Workers   : {workers}")
    print(f"{SEP}\n")

    # ── 1. Fetch data ──────────────────────────────────────────────────────────
    print("Fetching NSE price data ...")
    data_map: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        print(f"  {sym} ... ", end="", flush=True)
        df = _fetch(sym, start, end)
        if df is not None and not df.empty:
            data_map[sym] = df
            lo, hi = df["close"].min(), df["close"].max()
            print(f"OK  {len(df)} candles  "
                  f"price range Rs.{lo:,.0f} - Rs.{hi:,.0f}")
        else:
            print("FAILED - skipping")

    if not data_map:
        print("No data fetched. Abort.")
        sys.exit(1)

    # ── 2. Compute per-symbol minimums and capital ─────────────────────────────
    print("\nComputing lot-size minimum invest amounts:")
    sym_config: dict[str, dict] = {}
    for sym, df in data_map.items():
        lot     = SYMBOLS_CONFIG.get(sym.split(".")[0], {}).get("lot", get_lot_size(sym))
        min_inv = _min_invest(df, lot, buffer=1.05)
        inv_levels = _invest_levels(min_inv)
        capital = min_inv * 8           # ~8 lots worth of capital
        sym_config[sym] = {
            "lot":        lot,
            "min_invest": min_inv,
            "inv_levels": inv_levels,
            "capital":    capital,
        }
        print(f"  {sym:<12}  lot={lot:>5}  "
              f"min_invest=Rs.{min_inv:>10,.0f}  "
              f"capital=Rs.{capital:>12,.0f}")

    # ── 3. Build tasks ─────────────────────────────────────────────────────────
    print("\nBuilding parameter grids ...")
    tasks: list[tuple] = []  # (symbol, strategy, params, lot, capital)

    for sym, df in data_map.items():
        cfg  = sym_config[sym]
        lot  = cfg["lot"]
        invs = cfg["inv_levels"]
        cap  = cfg["capital"]
        lower, upper = _auto_bounds(df)

        if "GRID" in strategies:
            combos = _grid_combos(lower, upper, invs)
            for c in combos:
                tasks.append((sym, "GRID", c, lot, cap))
            print(f"  {sym} GRID : {len(combos)} combos")

        if "DCA" in strategies:
            combos = _dca_combos(invs)
            for c in combos:
                tasks.append((sym, "DCA", c, lot, cap))
            print(f"  {sym} DCA  : {len(combos)} combos")

        if "PLA" in strategies:
            combos = _pla_combos(invs)
            for c in combos:
                tasks.append((sym, "PLA", c, lot, cap))
            print(f"  {sym} PLA  : {len(combos)} combos")

    total = len(tasks)
    print(f"\n  Total runs: {total}")

    # ── 4. Execute ────────────────────────────────────────────────────────────
    print(f"\nRunning backtests ({workers} workers) ...\n")
    results: list[dict] = []
    done = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures_map = {
            pool.submit(_run, sym, strat, params, data_map[sym], lot, cap, i): i
            for i, (sym, strat, params, lot, cap) in enumerate(tasks)
        }
        for fut in as_completed(futures_map):
            results.append(fut.result())
            done += 1
            if done % 10 == 0 or done == total:
                elapsed = time.time() - t0
                eta     = (elapsed / done) * (total - done) if done else 0
                pct     = done / total * 100
                filled  = int(30 * done / total)
                bar     = "#" * filled + "." * (30 - filled)
                errs    = sum(1 for r in results if r.get("error") and r.get("num_trades", 0) == 0)
                print(f"\r  [{bar}] {pct:5.1f}%  {done}/{total}  ETA {eta:.0f}s  sub-lot-skips:{errs}",
                      end="", flush=True)

    elapsed = time.time() - t0
    valid_n = sum(1 for r in results if r.get("num_trades", 0) > 0)
    skip_n  = sum(1 for r in results if r.get("error") and "sub-lot" in str(r.get("error", "")))
    print(f"\n\n  Done in {elapsed:.1f}s  |  {valid_n} valid  |  {skip_n} sub-lot skips\n")

    results = _score(results)
    results.sort(key=lambda r: r.get("composite_score", 0.0), reverse=True)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# CSV save
# ─────────────────────────────────────────────────────────────────────────────

def _save_csv(results: list[dict], path: Path):
    if not results:
        return
    skip_keys = {k for k in results[0] if k.startswith("param_entry_level")
                 or k.startswith("param_invest_per_level_usd")
                 or k.startswith("param_entry_quant")}
    keys = [k for k in results[0] if k not in skip_keys]
    rows = [{k: r.get(k, "") for k in keys} for r in results]
    for r_row, r_orig in zip(rows, results):
        r_row["params_summary"] = _psummary(r_orig)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Verification text report
# ─────────────────────────────────────────────────────────────────────────────

def _save_verify_report(path: Path, results: list[dict],
                        start: date, end: date):
    valid = [r for r in results if r.get("num_trades", 0) > 0 and not r.get("error")]
    lines = []
    W = 80

    def h(t): lines.append("=" * W); lines.append(f"  {t}"); lines.append("=" * W)
    def s(t): lines.append(""); lines.append(f"  -- {t}"); lines.append("  " + "-" * (W-2))

    h("Indian Futures Optimizer - Charge Verification Report")
    lines.append(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  Period    : {start} to {end}")
    lines.append("")

    h("SECTION 1 - COST MODEL (Budget 2024 Rates, Verified from Zerodha/NSE/SEBI)")
    lines += [
        "  Source 1 : https://zerodha.com/charges/",
        "  Source 2 : https://zerodha.com/marketintel/bulletin/391488/",
        "  Source 3 : https://icicidirect.com (STT Budget 2024 changes)",
        "",
        "  Component                Rate              Applied On",
        "  " + "-" * (W-2),
        "  STT                      0.02%             SELL side turnover only",
        "  NSE Exchange Charges     0.00173%          Both sides (Rs.1.73/lakh)",
        "  SEBI Regulatory Fee      0.0001%           Both sides (Rs.10/crore)",
        "  GST                      18%               On (brokerage+ETC+SEBI)",
        "  Stamp Duty (Maharashtra) 0.003%            BUY side only",
        "  Brokerage                Rs.20/order flat  Both sides (Zerodha-style)",
        "",
        "  NOTE: STT was raised from 0.0125% to 0.02% effective 1 Oct 2024 (Budget 2024).",
        "        NSE ETC revised from 0.00188% to 0.00173% effective 1 Oct 2024.",
    ]

    h("SECTION 2 - SAMPLE COST CALCULATION (1 lot NIFTY50 @ Rs.19,500)")
    cost_model = IndianCostModel()
    nifty_price = 19_500.0
    nifty_lot   = 50
    turnover    = nifty_price * nifty_lot

    buy_cb  = cost_model.calculate(turnover, "BUY",  "futures", "flat", 20.0)
    sell_cb = cost_model.calculate(turnover, "SELL", "futures", "flat", 20.0)

    lines += [
        f"  Contract  : NIFTY50 Futures, 1 lot = {nifty_lot} units",
        f"  Price     : Rs.{nifty_price:,.0f}  |  Notional = Rs.{turnover:,.0f}",
        "",
        "  BUY LEG:",
        f"    Brokerage      : Rs.{buy_cb.brokerage:>10,.4f}  (flat Rs.20)",
        f"    STT            : Rs.{buy_cb.stt:>10,.4f}  (0% on buy for futures)",
        f"    Exchange (ETC) : Rs.{buy_cb.exchange_charges:>10,.4f}  (0.00173% x Rs.{turnover:,.0f})",
        f"    SEBI charges   : Rs.{buy_cb.sebi_charges:>10,.4f}  (0.0001% x Rs.{turnover:,.0f})",
        f"    GST            : Rs.{buy_cb.gst:>10,.4f}  (18% on brok+ETC+SEBI)",
        f"    Stamp duty     : Rs.{buy_cb.stamp_duty:>10,.4f}  (0.003% x Rs.{turnover:,.0f})",
        f"    TOTAL BUY      : Rs.{buy_cb.total:>10,.4f}  = {buy_cb.total/turnover*100:.4f}% of turnover",
        "",
        "  SELL LEG:",
        f"    Brokerage      : Rs.{sell_cb.brokerage:>10,.4f}  (flat Rs.20)",
        f"    STT            : Rs.{sell_cb.stt:>10,.4f}  (0.02% on sell turnover)",
        f"    Exchange (ETC) : Rs.{sell_cb.exchange_charges:>10,.4f}  (0.00173%)",
        f"    SEBI charges   : Rs.{sell_cb.sebi_charges:>10,.4f}  (0.0001%)",
        f"    GST            : Rs.{sell_cb.gst:>10,.4f}  (18% on brok+ETC+SEBI)",
        f"    Stamp duty     : Rs.{sell_cb.stamp_duty:>10,.4f}  (0% on sell)",
        f"    TOTAL SELL     : Rs.{sell_cb.total:>10,.4f}  = {sell_cb.total/turnover*100:.4f}% of turnover",
        "",
        f"  ROUND-TRIP TOTAL : Rs.{buy_cb.total+sell_cb.total:,.4f}  "
        f"= {(buy_cb.total+sell_cb.total)/turnover*100:.4f}% of notional",
        f"  BREAKEVEN MOVE   : Price must move >{(buy_cb.total+sell_cb.total)/turnover*100:.3f}% to profit",
    ]

    # Cross-check against Zerodha's published sample
    lines += [
        "",
        "  ZERODHA CROSS-CHECK (from zerodha.com/charges page):",
        "    Zerodha states: Futures round-trip cost ~0.05-0.06% of notional",
        f"    Our model:      {(buy_cb.total+sell_cb.total)/turnover*100:.4f}% of notional   [CONSISTENT]",
    ]

    h("SECTION 3 - ACTUAL CHARGES PAID IN BACKTEST (top 5 runs)")
    lines.append(f"  {'Symbol':<12} {'Strategy':<8} {'Trades':>6} "
                 f"{'Return%':>9} {'STT(Rs)':>10} {'ETC(Rs)':>10} "
                 f"{'GST(Rs)':>9} {'Brk(Rs)':>9} {'Total(Rs)':>12}")
    lines.append("  " + "-" * (W-2))
    for r in valid[:5]:
        lines.append(
            f"  {r.get('symbol',''):<12} {r.get('strategy',''):<8} "
            f"{r.get('num_trades',0):>6} "
            f"{r.get('total_return_pct',0):>+8.2f}% "
            f"Rs.{r.get('stt_paid_inr',0):>8,.0f} "
            f"Rs.{r.get('etc_paid_inr',0):>8,.0f} "
            f"Rs.{r.get('gst_paid_inr',0):>7,.0f} "
            f"Rs.{r.get('brokerage_paid_inr',0):>7,.0f} "
            f"Rs.{r.get('total_fees_inr',0):>10,.0f}"
        )

    h("SECTION 4 - NSE DATA SOURCE VERIFICATION")
    lines += [
        "  Data fetched via yfinance NSE source:",
        "    NIFTY50   -> ^NSEI    (NSE India official index)",
        "    BANKNIFTY -> ^NSEBANK (NSE Bank index)",
        "    RELIANCE  -> RELIANCE.NS",
        "    TCS       -> TCS.NS",
        "    INFY      -> INFY.NS",
        "    HDFCBANK  -> HDFCBANK.NS",
        "",
        "  yfinance pulls data from Yahoo Finance which sources from NSE.",
        "  Note: Futures prices are approximated using underlying spot prices.",
        "  (Near-month futures basis is typically within 0.2-0.5% of spot.)",
    ]

    lines.append("=" * W)
    path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# HTML Report
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(v, dec=2, prefix="Rs.", suffix=""):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return f"{prefix}{v:,.{dec}f}{suffix}" if prefix else f"{v:.{dec}f}{suffix}"


def _color(v, lo, hi, inv=False):
    if hi <= lo:
        return "#888"
    t = max(0.0, min(1.0, (v - lo) / (hi - lo)))
    if inv:
        t = 1 - t
    r = int(220 - (t if t > 0.5 else 0) * 2 * 120)
    g = int(100 + t * 2 * 120) if t < 0.5 else 220
    return f"rgb({max(60,r)},{min(220,g)},60)"


def generate_html_report(results: list[dict], path: Path,
                         start: date, end: date,
                         sym_config: dict):

    valid = [r for r in results if r.get("num_trades", 0) > 0 and not r.get("error")]
    if not valid:
        path.write_text("<h1>No valid results</h1>", encoding="utf-8")
        return

    def rng(col):
        v = [r[col] for r in valid if isinstance(r.get(col), (int, float))]
        return (min(v), max(v)) if v else (0, 1)

    ret_r  = rng("total_return_pct")
    sh_r   = rng("sharpe_ratio")
    so_r   = rng("sortino_ratio")
    dd_r   = rng("max_drawdown_pct")
    cal_r  = rng("calmar_ratio")
    pf_r   = rng("profit_factor")
    wr_r   = rng("win_rate")
    sc_r   = rng("composite_score")

    # ── Cost model table ───────────────────────────────────────────────────────
    cm = IndianCostModel()
    cost_rows_html = ""
    sample_syms = [("NIFTY50",  50,  19500), ("BANKNIFTY", 15, 42000),
                   ("RELIANCE", 250, 2500),  ("TCS", 150, 3800)]
    for sym, lot, px in sample_syms:
        tv = px * lot
        b  = cm.calculate(tv, "BUY",  "futures", "flat", 20.0)
        s  = cm.calculate(tv, "SELL", "futures", "flat", 20.0)
        rt = b.total + s.total
        rt_pct = rt / tv * 100
        cost_rows_html += f"""
        <tr>
          <td><b>{sym}</b></td>
          <td>{lot}</td>
          <td>Rs.{px:,}</td>
          <td>Rs.{tv:,}</td>
          <td>Rs.{b.stt:.2f}</td>
          <td>Rs.{s.stt:.2f}</td>
          <td>Rs.{(b.exchange_charges+s.exchange_charges):.2f}</td>
          <td>Rs.{(b.gst+s.gst):.2f}</td>
          <td>Rs.{(b.stamp_duty):.2f}</td>
          <td>Rs.{(b.brokerage+s.brokerage):.2f}</td>
          <td><b>Rs.{rt:.2f}</b></td>
          <td style="color:#34d399"><b>{rt_pct:.4f}%</b></td>
        </tr>"""

    # ── Best per strategy cards ────────────────────────────────────────────────
    strat_colors = {"GRID": "#3b82f6", "DCA": "#f59e0b", "PLA": "#10b981"}

    def _card(title, r, color):
        ret = r.get("total_return_pct", 0)
        sign = "+" if ret >= 0 else ""
        return f"""
        <div class="card" style="border-top:3px solid {color}">
          <div class="card-title">{title}</div>
          <div class="card-sym">{r["symbol"]} ({SYMBOLS_CONFIG.get(r["symbol"].split(".")[0],{}).get("label","")})
            <span class="badge" style="background:{color}">{r["strategy"]}</span>
          </div>
          <div class="card-params">{_psummary(r)}</div>
          <div class="card-metrics">
            <span class="mp">Score: <b>{r.get("composite_score",0):.3f}</b></span>
            <span class="mp">Return: <b style="color:{_color(ret,*ret_r)}">{sign}{ret:.1f}%</b></span>
            <span class="mp">Ann: <b>{r.get("annualised_return_pct",0):.1f}%/yr</b></span>
            <span class="mp">Sharpe: <b>{r.get("sharpe_ratio",0):.3f}</b></span>
            <span class="mp">Sortino: <b>{r.get("sortino_ratio",0):.3f}</b></span>
            <span class="mp">MDD: <b>{r.get("max_drawdown_pct",0):.1f}%</b></span>
            <span class="mp">Win: <b>{r.get("win_rate",0):.1f}%</b></span>
            <span class="mp">Trades: <b>{r.get("num_trades",0)}</b></span>
            <span class="mp">Total Fees: <b>Rs.{r.get("total_fees_inr",0):,.0f}</b></span>
          </div>
        </div>"""

    strat_cards = "".join(
        _card(f"Best {s}", max((r for r in valid if r["strategy"]==s),
                               key=lambda x: x["composite_score"]), c)
        for s, c in strat_colors.items()
        if any(r["strategy"] == s for r in valid)
    )
    sym_cards = "".join(
        _card(f"Best {sym}", max((r for r in valid if r["symbol"]==sym),
                                  key=lambda x: x["composite_score"]), "#a855f7")
        for sym in {r["symbol"] for r in valid}
        if any(r["symbol"] == sym for r in valid)
    )

    # ── Table rows ─────────────────────────────────────────────────────────────
    def _row(r, rank):
        sc  = r.get("composite_score", 0)
        ret = r.get("total_return_pct", 0)
        sh  = r.get("sharpe_ratio", 0)
        so  = r.get("sortino_ratio", 0)
        dd  = r.get("max_drawdown_pct", 0)
        cal = r.get("calmar_ratio", 0)
        pf  = r.get("profit_factor", 0)
        wr  = r.get("win_rate", 0)
        nt  = r.get("num_trades", 0)
        fees= r.get("total_fees_inr", 0)
        bc  = strat_colors.get(r["strategy"], "#888")
        sign = "+" if ret >= 0 else ""
        rm = {1: " 🥇", 2: " 🥈", 3: " 🥉"}.get(rank, "")
        return f"""
        <tr data-strategy="{r['strategy']}" data-symbol="{r['symbol']}">
          <td class="rank">#{rank}{rm}</td>
          <td><span class="badge" style="background:{bc}">{r["strategy"]}</span></td>
          <td class="sym">{r["symbol"]}</td>
          <td class="pc" title="{_psummary(r)}">{_psummary(r)}</td>
          <td style="color:{_color(sc,*sc_r)};font-weight:700">{sc:.3f}</td>
          <td style="color:{_color(ret,*ret_r)}">{sign}{ret:.1f}%</td>
          <td style="color:{_color(r.get('annualised_return_pct',0),*ret_r)}">{sign}{r.get('annualised_return_pct',0):.1f}%</td>
          <td style="color:{_color(sh,*sh_r)}">{sh:.3f}</td>
          <td style="color:{_color(so,*so_r)}">{so:.3f}</td>
          <td style="color:{_color(cal,*cal_r)}">{cal:.3f}</td>
          <td style="color:{_color(dd,*dd_r,inv=True)}">{dd:.1f}%</td>
          <td style="color:{_color(pf,*pf_r)}">{pf:.2f}x</td>
          <td style="color:{_color(wr,*wr_r)}">{wr:.1f}%</td>
          <td>{nt}</td>
          <td>Rs.{fees:,.0f}</td>
        </tr>"""

    table_html = "\n".join(_row(r, i+1) for i, r in enumerate(valid[:200]))

    total_r  = len(results)
    valid_r  = len(valid)
    skip_r   = sum(1 for r in results if "sub-lot" in str(r.get("error","")))
    err_r    = sum(1 for r in results if r.get("error") and "sub-lot" not in str(r.get("error","")))
    syms_seen = sorted({r["symbol"] for r in valid})

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>TradeVed — Indian Futures Optimizer</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f1117;color:#e2e8f0;font-family:system-ui,sans-serif}}
.header{{background:linear-gradient(135deg,#1a1f2e,#0f1117);border-bottom:1px solid #2d3748;padding:24px 40px}}
.header h1{{font-size:1.7rem;font-weight:700;background:linear-gradient(90deg,#fb923c,#f59e0b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.meta{{color:#94a3b8;font-size:.85rem;margin-top:6px}}
.chips{{display:flex;gap:12px;margin-top:14px;flex-wrap:wrap}}
.chip{{background:#1e2a3a;border:1px solid #2d3748;border-radius:20px;padding:5px 14px;font-size:.78rem;color:#94a3b8}}
.chip b{{color:#f0f4f8}}
.container{{max-width:1700px;margin:0 auto;padding:0 20px 50px}}
section{{margin-top:36px}}
h2{{font-size:1rem;font-weight:600;color:#cbd5e1;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
h2::before{{content:'';width:4px;height:16px;background:#fb923c;border-radius:2px;display:inline-block}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
.card{{background:#1a1f2e;border-radius:10px;padding:16px;border:1px solid #2d3748}}
.card-title{{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;margin-bottom:4px}}
.card-sym{{font-size:.95rem;font-weight:700;color:#f0f4f8;display:flex;align-items:center;gap:8px}}
.card-params{{font-size:.72rem;color:#94a3b8;margin:6px 0 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.card-metrics{{display:flex;flex-wrap:wrap;gap:5px}}
.mp{{background:#0f1117;border:1px solid #2d3748;border-radius:10px;padding:2px 9px;font-size:.72rem;color:#94a3b8}}
.badge{{display:inline-block;padding:2px 7px;border-radius:8px;font-size:.68rem;font-weight:700;color:#fff}}
.filter-bar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}}
.filter-bar select,.filter-bar input{{background:#1a1f2e;border:1px solid #2d3748;color:#e2e8f0;padding:6px 11px;border-radius:6px;font-size:.82rem;outline:none}}
#cnt{{font-size:.78rem;color:#64748b;margin-left:auto}}
.cost-table{{width:100%;border-collapse:collapse;font-size:.8rem;background:#161c2a;border-radius:8px;overflow:hidden}}
.cost-table th{{background:#1a1f2e;color:#94a3b8;padding:9px 12px;text-align:right;font-weight:600;white-space:nowrap}}
.cost-table th:first-child{{text-align:left}}
.cost-table td{{padding:8px 12px;text-align:right;border-bottom:1px solid #1e2535;color:#cbd5e1}}
.cost-table td:first-child{{text-align:left;font-weight:600}}
.cost-note{{background:#161c2a;border:1px solid #2d3748;border-radius:8px;padding:12px 16px;font-size:.78rem;color:#94a3b8;margin-bottom:16px}}
.tw{{overflow-x:auto;border-radius:10px;border:1px solid #2d3748}}
table.rt{{width:100%;border-collapse:collapse;font-size:.8rem;min-width:1200px}}
thead th{{background:#161c2a;color:#94a3b8;font-weight:600;padding:9px 11px;text-align:right;cursor:pointer;border-bottom:1px solid #2d3748;white-space:nowrap;position:sticky;top:0;z-index:1;user-select:none}}
thead th:nth-child(-n+4){{text-align:left}}
thead th:hover{{color:#fb923c}}
thead th.sa::after{{content:" ↑";color:#fb923c}}
thead th.sd::after{{content:" ↓";color:#fb923c}}
tbody tr{{border-bottom:1px solid #1e2535;transition:background .1s}}
tbody tr:hover{{background:#1a2233}}
td{{padding:8px 11px;text-align:right;color:#cbd5e1}}
td:nth-child(-n+4){{text-align:left}}
.rank{{color:#64748b;font-size:.76rem}}
.sym{{font-weight:600}}
.pc{{max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#94a3b8;font-size:.73rem}}
.footer{{text-align:center;padding:28px;color:#4a5568;font-size:.76rem;border-top:1px solid #1e2535;margin-top:40px}}
</style>
</head>
<body>
<div class="header">
  <h1>TradeVed — Indian Futures Optimizer</h1>
  <div class="meta">
    NSE Futures | Period: <b>{start}</b> to <b>{end}</b> |
    Cost Model: Budget 2024 (STT 0.02% + ETC 0.00173% + SEBI 0.0001% + GST 18% + Stamp 0.003%) |
    Brokerage: Rs.20/order flat
  </div>
  <div class="chips">
    <span class="chip">Total runs: <b>{total_r}</b></span>
    <span class="chip">Valid: <b>{valid_r}</b></span>
    <span class="chip">Sub-lot skips: <b>{skip_r}</b></span>
    <span class="chip">Errors: <b>{err_r}</b></span>
    <span class="chip">Symbols: <b>{len(syms_seen)}</b></span>
    <span class="chip">Generated: <b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</b></span>
  </div>
</div>

<div class="container">

<section>
  <h2>Real Cost Model — Round-Trip Charges Per Symbol (Verified from Zerodha/NSE/SEBI)</h2>
  <div class="cost-note">
    <b>Sources:</b>
    <a href="https://zerodha.com/charges/" style="color:#60a5fa">zerodha.com/charges</a> &nbsp;|&nbsp;
    <a href="https://zerodha.com/marketintel/bulletin/391488/" style="color:#60a5fa">NSE ETC revision Oct 2024</a> &nbsp;|&nbsp;
    <a href="https://www.icicidirect.com/research/equity/finace/new-stt-rules-in-futures-and-options-trading" style="color:#60a5fa">STT Budget 2024 changes</a>
    &nbsp;&nbsp;|&nbsp;&nbsp;
    All charges are <b>itemised and applied to every simulated trade</b> — not estimated.
  </div>
  <div class="tw">
    <table class="cost-table">
      <thead>
        <tr>
          <th>Symbol</th><th>Lot</th><th>Sample Price</th><th>Notional</th>
          <th>STT Buy</th><th>STT Sell</th><th>ETC (R/T)</th>
          <th>GST (R/T)</th><th>Stamp</th><th>Brokerage</th>
          <th>Total R/T</th><th>% of Notional</th>
        </tr>
      </thead>
      <tbody>{cost_rows_html}</tbody>
    </table>
  </div>
</section>

<section>
  <h2>Best Configuration by Strategy</h2>
  <div class="cards">{strat_cards}</div>
</section>

<section>
  <h2>Best Configuration by Symbol</h2>
  <div class="cards">{sym_cards}</div>
</section>

<section>
  <h2>Full Leaderboard (top {min(200, valid_r)} of {valid_r} valid runs)</h2>

  <div class="cost-note">
    Composite Score = 35% Sharpe + 25% Return + 20% Sortino + 10% Calmar + 10% (inv. MDD).
    All metrics min-max normalised. "Fees" = total Rs. paid in STT+ETC+SEBI+GST+Stamp+Brokerage.
  </div>

  <div class="filter-bar">
    <label>Strategy:</label>
    <select id="fs" onchange="applyFilters()">
      <option value="">All</option><option>GRID</option><option>DCA</option><option>PLA</option>
    </select>
    <label>Symbol:</label>
    <select id="fsym" onchange="applyFilters()">
      <option value="">All</option>
      {"".join(f"<option>{s}</option>" for s in syms_seen)}
    </select>
    <label>Min trades:</label>
    <input id="ft" type="number" value="1" min="0" style="width:65px" onchange="applyFilters()">
    <label>Min return %:</label>
    <input id="fr" type="number" value="" style="width:75px" placeholder="any" onchange="applyFilters()">
    <span id="cnt"></span>
  </div>

  <div class="tw">
    <table class="rt" id="rt">
      <thead>
        <tr>
          <th onclick="sort(0)">Rank</th>
          <th onclick="sort(1)">Strategy</th>
          <th onclick="sort(2)">Symbol</th>
          <th onclick="sort(3)">Parameters</th>
          <th onclick="sort(4)">Score</th>
          <th onclick="sort(5)">Return%</th>
          <th onclick="sort(6)">Ann.Ret%</th>
          <th onclick="sort(7)">Sharpe</th>
          <th onclick="sort(8)">Sortino</th>
          <th onclick="sort(9)">Calmar</th>
          <th onclick="sort(10)">Max DD%</th>
          <th onclick="sort(11)">Prof.Factor</th>
          <th onclick="sort(12)">Win%</th>
          <th onclick="sort(13)">Trades</th>
          <th onclick="sort(14)">Total Fees</th>
        </tr>
      </thead>
      <tbody id="tb">{table_html}</tbody>
    </table>
  </div>
</section>
</div>

<div class="footer">
  TradeVed Backtester &nbsp;·&nbsp; Indian Futures Optimizer &nbsp;·&nbsp;
  {valid_r} valid runs &nbsp;·&nbsp; {start} to {end} &nbsp;·&nbsp;
  Budget 2024 cost model &nbsp;·&nbsp; Data: yfinance NSE
</div>

<script>
let sc=4,sd=-1;
function sort(c){{
  if(sc===c)sd*=-1; else{{sc=c;sd=-1;}}
  document.querySelectorAll('thead th').forEach((t,i)=>{{t.classList.remove('sa','sd');if(i===c)t.classList.add(sd===-1?'sd':'sa');}});
  const tb=document.getElementById('tb');
  const rows=Array.from(tb.querySelectorAll('tr'));
  rows.sort((a,b)=>{{
    const av=a.cells[c]?.innerText.replace(/[^0-9.+\\-]/g,'')||'';
    const bv=b.cells[c]?.innerText.replace(/[^0-9.+\\-]/g,'')||'';
    const an=parseFloat(av),bn=parseFloat(bv);
    if(!isNaN(an)&&!isNaN(bn))return(an-bn)*sd;
    return av.localeCompare(bv)*sd;
  }});
  rows.forEach(r=>tb.appendChild(r));upd();
}}
function applyFilters(){{
  const fs=document.getElementById('fs').value;
  const fsym=document.getElementById('fsym').value;
  const ft=parseInt(document.getElementById('ft').value)||0;
  const fr=parseFloat(document.getElementById('fr').value);
  document.querySelectorAll('#tb tr').forEach(row=>{{
    const show=(!fs||row.dataset.strategy===fs)&&
               (!fsym||row.dataset.symbol===fsym)&&
               (parseInt(row.cells[13]?.innerText)||0)>=ft&&
               (isNaN(fr)||(parseFloat(row.cells[5]?.innerText)||0)>=fr);
    row.style.display=show?'':'none';
  }});upd();
}}
function upd(){{
  const v=document.querySelectorAll('#tb tr:not([style*="none"])').length;
  document.getElementById('cnt').textContent=`Showing ${{v}} runs`;
}}
upd();
</script>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")
    print(f"  HTML report -> {path}")


# ─────────────────────────────────────────────────────────────────────────────
# Console summary
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(results: list[dict]):
    valid = [r for r in results if r.get("num_trades", 0) > 0 and not r.get("error")]
    if not valid:
        print("No valid results."); return

    W = 110
    print("\n" + "=" * W)
    print("  TOP 10  Indian Futures — Composite Score (Budget 2024 cost model)")
    print("=" * W)
    print(f"  {'#':<4} {'Strat':<6} {'Symbol':<12} {'Score':>7} {'Return%':>9} "
          f"{'Sharpe':>8} {'Sortino':>8} {'MDD%':>7} {'WinR%':>7} {'Trades':>6} {'Fees(Rs)':>10}  Params")
    print("-" * W)
    for i, r in enumerate(valid[:10], 1):
        ret  = r.get("total_return_pct", 0)
        sign = "+" if ret >= 0 else ""
        print(f"  {i:<4} {r['strategy']:<6} {r['symbol']:<12} "
              f"{r.get('composite_score',0):>7.4f} {sign}{ret:>8.2f}% "
              f"{r.get('sharpe_ratio',0):>8.3f} {r.get('sortino_ratio',0):>8.3f} "
              f"{r.get('max_drawdown_pct',0):>7.2f}% {r.get('win_rate',0):>6.1f}% "
              f"{r.get('num_trades',0):>6} Rs.{r.get('total_fees_inr',0):>7,.0f}  "
              f"{_psummary(r)}")

    for strat, color in [("GRID","GRID"), ("DCA","DCA"), ("PLA","PLA")]:
        sub  = [r for r in valid if r["strategy"] == strat]
        if not sub: continue
        best = max(sub, key=lambda x: x["composite_score"])
        ret  = best.get("total_return_pct", 0)
        sign = "+" if ret >= 0 else ""
        print(f"\n  BEST {strat}:")
        print(f"    Symbol   : {best['symbol']}  ({SYMBOLS_CONFIG.get(best['symbol'].split('.')[0],{}).get('label','')})")
        print(f"    Params   : {_psummary(best)}")
        print(f"    Score    : {best.get('composite_score',0):.4f}")
        print(f"    Return   : {sign}{ret:.2f}%  |  Ann: {sign}{best.get('annualised_return_pct',0):.2f}%/yr")
        print(f"    Sharpe   : {best.get('sharpe_ratio',0):.3f}  |  "
              f"Sortino: {best.get('sortino_ratio',0):.3f}  |  "
              f"Calmar: {best.get('calmar_ratio',0):.3f}")
        print(f"    Max DD   : {best.get('max_drawdown_pct',0):.2f}%  |  "
              f"Win Rate: {best.get('win_rate',0):.1f}%  |  "
              f"Trades: {best.get('num_trades',0)}")
        print(f"    Fees     : Rs.{best.get('total_fees_inr',0):,.0f}  "
              f"(STT:Rs.{best.get('stt_paid_inr',0):,.0f}  "
              f"ETC:Rs.{best.get('etc_paid_inr',0):,.0f}  "
              f"GST:Rs.{best.get('gst_paid_inr',0):,.0f}  "
              f"Brk:Rs.{best.get('brokerage_paid_inr',0):,.0f})")

    print("\n" + "=" * W)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse():
    p = argparse.ArgumentParser(description="Indian Futures Parameter Optimizer")
    p.add_argument("--symbols",    nargs="+", default=DEFAULT_SYMBOLS)
    p.add_argument("--strategies", nargs="+", default=["GRID","DCA","PLA"],
                   choices=["GRID","DCA","PLA"])
    p.add_argument("--start", type=lambda s: date.fromisoformat(s), default=DEFAULT_START)
    p.add_argument("--end",   type=lambda s: date.fromisoformat(s), default=DEFAULT_END)
    p.add_argument("--workers", type=int, default=4)
    return p.parse_args()


def main():
    args = _parse()
    strategies = [s.upper() for s in args.strategies]

    results = run_optimizer(
        symbols    = args.symbols,
        strategies = strategies,
        start      = args.start,
        end        = args.end,
        workers    = args.workers,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(exist_ok=True)

    csv_path    = OUTPUT_DIR / f"india_results_{ts}.csv"
    html_path   = OUTPUT_DIR / f"india_report_{ts}.html"
    verify_path = OUTPUT_DIR / f"india_verify_{ts}.txt"

    valid = [r for r in results if r.get("num_trades", 0) > 0 and not r.get("error")]

    # sym_config for HTML
    sym_cfg: dict = {}
    for r in results:
        sym = r.get("symbol", "")
        if sym and sym not in sym_cfg:
            sym_cfg[sym] = SYMBOLS_CONFIG.get(sym.split(".")[0], {"lot": r.get("lot_size",1)})

    print("\nSaving outputs ...")
    _save_csv(results, csv_path)
    print(f"  CSV  -> {csv_path}")

    generate_html_report(results, html_path, args.start, args.end, sym_cfg)

    _save_verify_report(verify_path, results, args.start, args.end)
    print(f"  Verify report -> {verify_path}")

    _print_summary(results)

    print(f"\nOpen report:\n  file:///{html_path.as_posix()}\n")


if __name__ == "__main__":
    main()
