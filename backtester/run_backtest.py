"""
run_backtest.py — Standalone CLI script.

Runs a complete backtest (no server required) and opens the HTML report.

Usage examples:
    python run_backtest.py
    python run_backtest.py --strategy GRID --symbol BTC/USDT --year 2023
    python run_backtest.py --strategy DCA  --symbol ETH/USDT --capital 5000
Options:
    --symbol      Trading pair (default: BTC/USDT)
    --strategy    GRID | DCA | PLA  (default: GRID)
    --start       Start date YYYY-MM-DD (default: 2023-01-01)
    --end         End date YYYY-MM-DD  (default: 2023-12-31)
    --capital     Initial capital USD  (default: 10000)
    --source      binance | yfinance | nse | bse (default: binance)
    --interval    1d | 4h | 1h (default: 1d)
    --fee         Fee percent  (default: 0.001)
    --slippage    Slippage %   (default: 0.001)
    --open        Open report in browser when done
    --all         Run all three strategies and compare
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# ── Fix Windows console encoding ─────────────────────────────────────────────
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Bootstrap path so relative imports work ───────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from data.fetcher    import DataFetcher
from data.validator  import DataValidator
from data.eda        import EDAEngine
from engine.simulator import TradeSimulator
from engine.metrics  import calculate_metrics
from frontend.report import generate_report
from strategies      import STRATEGY_REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────

DIVIDER = "─" * 70


def run_single(
    symbol:    str,
    strategy:  str,
    start:     str,
    end:       str,
    capital:   float,
    source:    str,
    interval:  str,
    fee:       float,
    slippage:  float,
    extra_params: dict,
    run_eda:   bool = False,
) -> tuple[dict, Path]:
    """Run one complete backtest and return (metrics, report_path)."""
    strategy = strategy.upper()
    if strategy not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose from: {list(STRATEGY_REGISTRY)}")

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt   = datetime.strptime(end,   "%Y-%m-%d")

    print(f"\n{DIVIDER}")
    print(f"  📊  {strategy} Backtest — {symbol}")
    print(f"  📅  {start} → {end}  |  Capital: ${capital:,.0f}  |  Source: {source}")
    print(DIVIDER)

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    print("\n[1/5] Fetching market data…")
    fetcher = DataFetcher()
    df      = fetcher.fetch(symbol, start_dt, end_dt, source, interval)
    print(f"      ✅  {len(df)} candles fetched")

    # ── 2. Validate ───────────────────────────────────────────────────────────
    print("[2/5] Validating data quality…")
    val = DataValidator().validate(df)
    print(f"      ✅  Quality score: {val.quality_score:.1f}/100")
    if val.issues:
        print(f"      ⚠️   Issues: {val.issues}")
    if val.warnings:
        print(f"      ℹ️   Warnings: {val.warnings[:3]}")

    # ── 3. EDA (optional) ─────────────────────────────────────────────────────
    if run_eda:
        print("[3/5] Running EDA…")
        eda  = EDAEngine()
        eda_report = eda.analyse(df.copy(), symbol)
        print(f"      ✅  EDA complete — charts saved to ./charts/")
        _print_eda_summary(eda_report)
    else:
        print("[3/5] EDA skipped (use --eda to enable)")

    # ── 4. Strategy + simulation ──────────────────────────────────────────────
    print(f"[4/5] Generating {strategy} signals and simulating trades…")
    cls       = STRATEGY_REGISTRY[strategy]
    params    = {**cls.default_params(), **extra_params}
    strategy_inst = cls(**params)
    signals_df    = strategy_inst.generate_signals(df.copy())

    buy_cnt  = (signals_df["signal"] == "BUY").sum()
    sell_cnt = (signals_df["signal"] == "SELL").sum()
    print(f"      ✅  Signals — BUY: {buy_cnt} | SELL: {sell_cnt}")

    sim     = TradeSimulator(symbol, capital, fee, slippage)
    sim_out = sim.run(signals_df)

    # ── 5. Metrics ────────────────────────────────────────────────────────────
    print("[5/5] Computing performance metrics…")
    metrics = calculate_metrics(
        trades         = sim_out["trades"],
        equity_curve   = sim_out["equity_curve"],
        timestamps     = sim_out["timestamps"],
        initial_capital = capital,
    )

    # ── Print results ─────────────────────────────────────────────────────────
    _print_metrics(metrics, sim_out, strategy, symbol)

    # ── Generate report ───────────────────────────────────────────────────────
    import uuid
    bid   = str(uuid.uuid4())[:8]
    rpath = generate_report(
        backtest_id = bid,
        symbol      = symbol,
        strategy    = strategy,
        params      = params,
        metrics     = metrics,
        ohlcv_df    = df,
    )
    print(f"\n  📄  Report saved → {rpath}")

    return metrics, rpath


def _print_metrics(metrics: dict, sim_out: dict, strategy: str, symbol: str):
    ret     = metrics["total_return_pct"]
    ret_sgn = "+" if ret >= 0 else ""
    ret_clr = "\033[92m" if ret >= 0 else "\033[91m"
    reset   = "\033[0m"

    print(f"\n{DIVIDER}")
    print(f"  🏆  RESULTS — {strategy} on {symbol}")
    print(DIVIDER)
    print(f"  Total Return     : {ret_clr}{ret_sgn}{ret:.2f}%{reset}   (${metrics['total_return_usd']:+,.2f})")
    print(f"  Ann. Return      : {ret_sgn}{metrics['annualised_return_pct']:.2f}%")
    print(f"  Final Equity     : ${metrics['final_equity']:,.2f}")
    print(f"  ─────────────────────────────────────────")
    print(f"  Sharpe Ratio     : {metrics['sharpe_ratio']:.4f}")
    print(f"  Sortino Ratio    : {metrics['sortino_ratio']:.4f}")
    print(f"  Calmar Ratio     : {metrics['calmar_ratio']:.4f}")
    print(f"  Volatility       : {metrics['volatility_pct']:.2f}%")
    print(f"  ─────────────────────────────────────────")
    print(f"  Max Drawdown     : \033[91m{metrics['max_drawdown_pct']:.2f}%\033[0m")
    print(f"  DD Duration      : {metrics['max_dd_duration_candles']} candles")
    print(f"  ─────────────────────────────────────────")
    print(f"  Num Trades       : {metrics['num_trades']}")
    print(f"  Win Rate         : {metrics['win_rate']:.1f}%")
    print(f"  Profit Factor    : {metrics['profit_factor']:.4f}")
    print(f"  Best Trade       : ${metrics['best_trade']:+,.4f}")
    print(f"  Worst Trade      : ${metrics['worst_trade']:+,.4f}")
    print(f"  Avg Duration     : {metrics['avg_trade_duration']:.1f}h")
    print(f"  Trades / Day     : {metrics['trades_per_day']:.4f}")
    print(f"  Fees Paid        : ${sim_out['total_fees_paid']:,.4f}")
    print(DIVIDER)


def _print_eda_summary(eda: dict):
    stats = eda.get("statistics", {})
    close = stats.get("close", {})
    vol   = eda.get("volatility", {})
    print(f"\n      EDA Summary for {eda['symbol']}")
    print(f"        Candles        : {stats.get('total_candles','?')}")
    print(f"        Price range    : ${close.get('min','?'):,.2f} – ${close.get('max','?'):,.2f}")
    print(f"        Total return   : {stats.get('returns',{}).get('total_pct','?'):.2f}%")
    print(f"        Ann. volatility: {vol.get('annualised_volatility_pct','?'):.2f}%")
    print(f"        Best month     : {eda.get('seasonality',{}).get('best_month','?')}")
    print(f"        Worst month    : {eda.get('seasonality',{}).get('worst_month','?')}")


def run_all(args) -> None:
    """Run Grid, DCA and PLA on the same data and print a comparison table."""
    results = {}
    paths   = {}

    for strat in ["GRID", "DCA", "PLA"]:
        try:
            m, p = run_single(
                symbol    = args.symbol,
                strategy  = strat,
                start     = args.start,
                end       = args.end,
                capital   = args.capital,
                source    = args.source,
                interval  = args.interval,
                fee       = args.fee,
                slippage  = args.slippage,
                extra_params = {},
                run_eda   = False,
            )
            results[strat] = m
            paths[strat]   = p
        except Exception as exc:
            logger.error("%s failed: %s", strat, exc)
            results[strat] = None

    # ── Comparison table ──────────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  📊  STRATEGY COMPARISON")
    print(f"{'═'*70}")
    header = f"  {'Metric':<26}{'GRID':>12}{'DCA':>12}{'PLA':>12}"
    print(header)
    print(f"  {'─'*64}")

    metrics_to_show = [
        ("Total Return (%)", "total_return_pct"),
        ("Ann. Return (%)",  "annualised_return_pct"),
        ("Sharpe Ratio",     "sharpe_ratio"),
        ("Max Drawdown (%)", "max_drawdown_pct"),
        ("Win Rate (%)",     "win_rate"),
        ("Num Trades",       "num_trades"),
        ("Profit Factor",    "profit_factor"),
    ]
    for label, key in metrics_to_show:
        vals = []
        for strat in ["GRID", "DCA", "PLA"]:
            r = results.get(strat)
            vals.append(f"{r[key]:>12.2f}" if r else f"{'N/A':>12}")
        print(f"  {label:<26}{''.join(vals)}")

    print(f"{'═'*70}\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="TradeVed Backtester — run strategies from the command line"
    )
    p.add_argument("--symbol",   default="BTC/USDT")
    p.add_argument("--strategy", default="GRID",       choices=["GRID", "DCA", "PLA"])
    p.add_argument("--start",    default="2023-01-01")
    p.add_argument("--end",      default="2023-12-31")
    p.add_argument("--capital",  default=10_000.0,     type=float)
    p.add_argument("--source",   default="binance",    choices=["binance", "yfinance", "nse", "bse"])
    p.add_argument("--interval", default="1d")
    p.add_argument("--fee",      default=0.001,        type=float)
    p.add_argument("--slippage", default=0.001,        type=float)
    p.add_argument("--open",     action="store_true",  help="Open report in browser")
    p.add_argument("--eda",      action="store_true",  help="Run EDA analysis")
    p.add_argument("--all",      action="store_true",  help="Run all strategies & compare")
    return p.parse_args()


def main():
    args = parse_args()

    if args.all:
        run_all(args)
        return

    metrics, report_path = run_single(
        symbol       = args.symbol,
        strategy     = args.strategy,
        start        = args.start,
        end          = args.end,
        capital      = args.capital,
        source       = args.source,
        interval     = args.interval,
        fee          = args.fee,
        slippage     = args.slippage,
        extra_params = {},
        run_eda      = args.eda,
    )

    if args.open:
        webbrowser.open(str(report_path))
    else:
        print(f"\n  💡  Open the report:")
        print(f"      file:///{report_path}")


if __name__ == "__main__":
    main()
