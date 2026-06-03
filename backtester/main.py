"""
TradeVed Backtester — FastAPI application entry point.

Run:
    python main.py
  or
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

import models
from config import (
    API_DESCRIPTION, API_PREFIX, API_TITLE, API_VERSION,
    DEFAULT_CAPITAL, DEFAULT_FEE_PERCENT, DEFAULT_SLIPPAGE_PERCENT,
    RATE_LIMIT_PER_MINUTE, REPORTS_DIR,
)
from database import get_db, init_db
from data.fetcher import DataFetcher
from data.validator import DataValidator
from data.eda import EDAEngine
from data.indian_assets import (
    to_yf_symbol as indian_to_yf,
    NSE_DROPDOWN, NSE_ETFS, FO_LOT_SIZES, INDEX_MAP,
    is_indian, get_lot_size,
)
from engine.simulator import TradeSimulator
from engine.metrics import calculate_metrics
from engine.cost_models import IndianCostModel
from engine.regimes import classify_regimes, regime_breakdown
from engine.validation import run_holdout, run_walk_forward
from engine.stress import (
    SCENARIO_PRESETS, StressScenario, run_stress_backtest,
    apply_stress, run_single_backtest, aggregate_stress_results, run_trade_mc,
    compute_wfe, compute_robustness_score, _compute_regime_vol_scales,
)
from engine.regimes import classify_regimes
from frontend.report import generate_report
from strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)


# ── JSON safety helpers ────────────────────────────────────────────────────────

def _safe_float(v: Any, fallback: float = 0.0) -> Any:
    """Replace inf / nan with JSON-safe values. Returns non-floats unchanged."""
    if not isinstance(v, float):
        return v
    if math.isnan(v):
        return fallback
    if math.isinf(v):
        return 9999.0 if v > 0 else -9999.0
    return v


def _sanitize(obj: Any) -> Any:
    """Recursively replace inf/nan floats inside dicts and lists."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return _safe_float(obj)


def _round_nice(value: float, direction: str = "floor") -> float:
    """
    Round a price to the nearest 'nice' number so grid bounds look clean.
    e.g. 43_127 → 43_000 (floor) or 44_000 (ceil).
    Works for any asset price magnitude: $0.001 (SHIB) to $100k (BTC).
    """
    if value <= 0:
        return 0.0
    magnitude = 10 ** (math.floor(math.log10(abs(value))) - 1)
    if direction == "floor":
        return math.floor(value / magnitude) * magnitude
    return math.ceil(value / magnitude) * magnitude


# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{RATE_LIMIT_PER_MINUTE}/minute"])

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Singletons ─────────────────────────────────────────────────────────────────
fetcher   = DataFetcher()
validator = DataValidator()
eda_engine = EDAEngine()

# ── Simple in-memory cache ────────────────────────────────────────────────────
_cache: dict[str, Any] = {}

# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("🚀 TradeVed Backtester API started")


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol:     str         = Field("BTC/USDT", description="Trading pair or NSE/BSE symbol")
    strategy:   str         = Field("GRID",     description="GRID | DCA | PLA")
    start_date: date        = Field(...,         description="Start date (YYYY-MM-DD)")
    end_date:   date        = Field(...,         description="End date (YYYY-MM-DD)")
    capital:    float       = Field(DEFAULT_CAPITAL)
    fee_pct:    float       = Field(DEFAULT_FEE_PERCENT,      description="Legacy % fee (ignored when use_indian_costs=True)")
    slippage:   float       = Field(DEFAULT_SLIPPAGE_PERCENT, description="Market-impact slippage %")
    source:     str         = Field("binance",   description="binance | yfinance | nse | bse")
    interval:   str         = Field("1d")
    params:     dict        = Field(default_factory=dict, description="Strategy-specific params")
    # ── Indian market fields ───────────────────────────────────────────────────
    use_indian_costs: bool  = Field(False,   description="Enable precise Indian cost model (STT + exchange + GST + stamp)")
    market_type:      str   = Field("equity_delivery",
                                    description="equity_delivery | equity_intraday | futures | options")
    brokerage_model:  str   = Field("flat",  description="flat | percentage | zero")
    brokerage_flat:   float = Field(20.0,    description="₹ per order (Zerodha-style flat brokerage)")
    brokerage_pct:    float = Field(0.005,   description="% of turnover for percentage brokerage")
    synthetic_intraday: bool = Field(False,  description="Generate synthetic 15m/1h candles from daily OHLCV for unlimited history (NSE/BSE only)")
    # ── Out-of-sample validation fields ──────────────────────────────────────
    validation_mode: str   = Field("none",  description="none | holdout | walk_forward")
    train_ratio:     float = Field(0.7,     description="Holdout: fraction of data used for in-sample (0.5–0.9)")
    wf_window:       int   = Field(252,     description="Walk-forward: train window in candles (default 252 = ~1yr daily)")
    wf_step:         int   = Field(63,      description="Walk-forward: test/step size in candles (default 63 = ~1qtr daily)")


class CompareRequest(BaseModel):
    backtest_ids: list[str]


class OptimizeRequest(BaseModel):
    symbol:       str
    strategy:     str
    start_date:   date
    end_date:     date
    capital:      float = DEFAULT_CAPITAL
    source:       str   = "binance"
    param_ranges: dict[str, list]  # {"num_levels": [3,5,7], "upper_bound": [45000]}
    metric:       str   = "sharpe_ratio"  # metric to maximise


# ─────────────────────────────────────────────────────────────────────────────
# ── Root
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "TradeVed Backtester API", "version": API_VERSION}

@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# ── Data endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/data/{{symbol:path}}", tags=["Data"])
def get_data(
    symbol:     str,
    start_date: date   = Query(date(2023, 1, 1)),
    end_date:   date   = Query(date(2023, 12, 31)),
    source:     str    = Query("binance"),
    interval:   str    = Query("1d"),
    db:         Session = Depends(get_db),
):
    """Fetch OHLCV data for a symbol. Tries DB cache first, then external source."""
    # DB check
    existing = (
        db.query(models.OHLCVData)
        .filter(
            models.OHLCVData.symbol == symbol,
            models.OHLCVData.source == source,
            models.OHLCVData.timestamp >= datetime.combine(start_date, datetime.min.time()),
            models.OHLCVData.timestamp <= datetime.combine(end_date,   datetime.max.time()),
        )
        .order_by(models.OHLCVData.timestamp)
        .all()
    )

    if existing:
        return {
            "symbol":    symbol,
            "source":    source,
            "records":   len(existing),
            "data":      [r.to_dict() for r in existing],
            "cached":    True,
        }

    # Fetch fresh
    df = fetcher.fetch(symbol, datetime.combine(start_date, datetime.min.time()),
                       datetime.combine(end_date, datetime.max.time()), source, interval)

    val = validator.validate(df)

    # Persist to DB
    for _, row in df.iterrows():
        try:
            db.merge(models.OHLCVData(
                symbol        = symbol,
                timestamp     = row["timestamp"],
                open          = row["open"],
                high          = row["high"],
                low           = row["low"],
                close         = row["close"],
                volume        = row["volume"],
                source        = source,
                quality_score = val.quality_score,
            ))
        except Exception:
            pass
    db.commit()

    return {
        "symbol":        symbol,
        "source":        source,
        "records":       len(df),
        "data":          df.to_dict(orient="records"),
        "quality_score": val.quality_score,
        "cached":        False,
    }


@app.get(f"{API_PREFIX}/data/{{symbol:path}}/quality", tags=["Data"])
def get_data_quality(
    symbol:     str,
    start_date: date   = Query(date(2023, 1, 1)),
    end_date:   date   = Query(date(2023, 12, 31)),
    source:     str    = Query("binance"),
):
    """Return data quality score and validation issues."""
    df  = fetcher.fetch(symbol, datetime.combine(start_date, datetime.min.time()),
                        datetime.combine(end_date, datetime.max.time()), source)
    val = validator.validate(df)
    return {
        "symbol":        symbol,
        "quality_score": val.quality_score,
        "passed":        val.passed,
        "issues":        val.issues,
        "warnings":      val.warnings,
        "stats":         val.stats,
    }


@app.get(f"{API_PREFIX}/data/{{symbol:path}}/eda", tags=["Data"])
def get_eda(
    symbol:     str,
    start_date: date = Query(date(2023, 1, 1)),
    end_date:   date = Query(date(2023, 12, 31)),
    source:     str  = Query("binance"),
):
    """Run full EDA on a symbol and return a structured analysis."""
    df     = fetcher.fetch(symbol, datetime.combine(start_date, datetime.min.time()),
                           datetime.combine(end_date, datetime.max.time()), source)
    report = eda_engine.analyse(df, symbol)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# ── Strategy endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/strategies", tags=["Strategies"])
def list_strategies():
    """List all available trading strategies."""
    return [
        {
            "name":        name,
            "description": cls.description(),
            "parameters":  cls.default_params(),
        }
        for name, cls in STRATEGY_REGISTRY.items()
    ]


@app.get(f"{API_PREFIX}/strategies/{{strategy}}/defaults", tags=["Strategies"])
def strategy_defaults(strategy: str):
    """Get default parameters for a strategy."""
    strategy = strategy.upper()
    cls = STRATEGY_REGISTRY.get(strategy)
    if not cls:
        raise HTTPException(404, f"Strategy '{strategy}' not found. Available: {list(STRATEGY_REGISTRY)}")
    return cls.default_params()


@app.get(f"{API_PREFIX}/strategies/grid/bounds", tags=["Strategies"])
def grid_bounds_auto(
    symbol:     str  = Query("BTC/USDT", description="Trading pair or stock ticker"),
    source:     str  = Query("binance",   description="Data source"),
    interval:   str  = Query("1d"),
    start_date: date = Query(None,        description="Start of range (defaults to 90 days ago)"),
    end_date:   date = Query(None,        description="End of range (defaults to today)"),
):
    """
    Auto-detect appropriate GRID strategy bounds for any asset.
    Fetches real price history and returns rounded lower/upper bounds,
    suggested grid levels, and invest-per-level hint.
    Works for crypto (BTC, ETH, SHIB…), stocks (AAPL, NVDA…), and forex.
    """
    from datetime import timedelta

    today = date.today()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = end_date - timedelta(days=90)

    # Clamp to valid range
    if start_date >= end_date:
        start_date = end_date - timedelta(days=7)

    try:
        df = fetcher.fetch(
            symbol,
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date,   datetime.max.time()),
            source, interval,
        )
    except Exception as exc:
        raise HTTPException(400, f"Could not fetch price data for '{symbol}': {exc}") from exc

    if df.empty or len(df) < 2:
        raise HTTPException(400, f"Insufficient price data for '{symbol}'")

    prices   = df["close"].astype(float)
    lo_raw   = float(prices.min())
    hi_raw   = float(prices.max())
    current  = float(prices.iloc[-1])
    open_    = float(prices.iloc[0])

    # 10 % padding on each side → ensures current price sits inside the grid
    pad       = (hi_raw - lo_raw) * 0.10
    lower_raw = max(0.0, lo_raw - pad)
    upper_raw = hi_raw + pad

    lower = _round_nice(lower_raw, "floor")
    upper = _round_nice(upper_raw, "ceil")

    # Ensure current price is inside bounds (safety guard)
    if current < lower:
        lower = _round_nice(current * 0.85, "floor")
    if current > upper:
        upper = _round_nice(current * 1.15, "ceil")

    # Suggest num_levels: 1 level per ~2 % of range
    pct_range = (upper - lower) / current * 100 if current > 0 else 20
    suggested_levels = int(max(3, min(20, round(pct_range / 2))))

    return _sanitize({
        "symbol":            symbol,
        "source":            source,
        "period_start":      str(start_date),
        "period_end":        str(end_date),
        "candles":           int(len(df)),
        "current_price":     round(current,  8),
        "period_low":        round(lo_raw,   8),
        "period_high":       round(hi_raw,   8),
        "price_change_pct":  round((current / open_ - 1) * 100, 2) if open_ > 0 else 0.0,
        "suggested_lower":   lower,
        "suggested_upper":   upper,
        "suggested_levels":  suggested_levels,
        "padding_pct":       10.0,
    })


# ─────────────────────────────────────────────────────────────────────────────
# ── Indian Market endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/india/assets", tags=["India"])
def india_assets():
    """
    Return curated list of Indian market assets for the UI dropdown.
    Includes Nifty 50 stocks, indices, ETFs, and F&O instruments.
    """
    return {
        "stocks_and_indices": [
            {"symbol": sym, "label": label, "lot_size": FO_LOT_SIZES.get(sym, 1)}
            for sym, label in NSE_DROPDOWN.items()
        ],
        "etfs": [
            {"symbol": sym, "label": label, "lot_size": 1}
            for sym, label in NSE_ETFS.items()
        ],
        "fo_lot_sizes": FO_LOT_SIZES,
    }


@app.get(f"{API_PREFIX}/india/cost_preview", tags=["India"])
def india_cost_preview(
    market_type:     str   = Query("equity_delivery"),
    brokerage_model: str   = Query("flat"),
    brokerage_flat:  float = Query(20.0),
    turnover:        float = Query(100_000.0, description="Sample trade size in ₹"),
):
    """
    Preview Indian market transaction costs for a given trade size.
    Returns itemised breakdown (STT, exchange charges, GST, stamp duty, brokerage).
    Useful for showing users the exact cost model before running a backtest.
    """
    calc = IndianCostModel()
    buy  = calc.calculate(turnover, "BUY",  market_type, brokerage_model, brokerage_flat)
    sell = calc.calculate(turnover, "SELL", market_type, brokerage_model, brokerage_flat)
    rt_pct = round((buy.total + sell.total) / turnover * 100, 4)

    return _sanitize({
        "sample_turnover_inr": turnover,
        "market_type":         market_type,
        "brokerage_model":     brokerage_model,
        "brokerage_flat_inr":  brokerage_flat,
        "buy_leg":  buy.as_dict(),
        "sell_leg": sell.as_dict(),
        "round_trip_total_inr": round(buy.total + sell.total, 4),
        "round_trip_pct":       rt_pct,
        "note": (
            "Rates: STT (Budget 2024), NSE exchange charges, SEBI 0.0001%, "
            "GST 18%, Maharashtra stamp duty. "
            "F&O lot sizes verified for FY2024-25."
        ),
    })


@app.get(f"{API_PREFIX}/india/symbols/search", tags=["India"])
def india_symbol_search(q: str = Query(..., description="Symbol or company name prefix")):
    """
    Quick symbol search for Indian markets.
    Returns matching symbols from NSE stocks, ETFs and indices.
    """
    q_up = q.strip().upper()
    results = []
    for sym, label in NSE_DROPDOWN.items():
        if q_up in sym or q_up in label.upper():
            results.append({
                "symbol":   sym,
                "label":    label,
                "exchange": "NSE",
                "lot_size": FO_LOT_SIZES.get(sym, 1),
                "is_fo":    sym in FO_LOT_SIZES,
            })
    for sym, label in NSE_ETFS.items():
        if q_up in sym or q_up in label.upper():
            results.append({
                "symbol":   sym,
                "label":    label,
                "exchange": "NSE",
                "lot_size": 1,
                "is_fo":    False,
            })
    return {"query": q, "results": results[:20]}


# ─────────────────────────────────────────────────────────────────────────────
# ── Backtest endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post(f"{API_PREFIX}/backtest/run", tags=["Backtest"])
def run_backtest(req: BacktestRequest, db: Session = Depends(get_db)):
    """Run a full backtest end-to-end."""
    strategy_name = req.strategy.upper()
    if strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(400, f"Unknown strategy '{strategy_name}'. Choose from: {list(STRATEGY_REGISTRY)}")

    backtest_id = str(uuid.uuid4())[:8]

    # ── Persist job ───────────────────────────────────────────────────────────
    job = models.Backtest(
        id         = backtest_id,
        symbol     = req.symbol,
        strategy   = strategy_name,
        start_date = req.start_date,
        end_date   = req.end_date,
        capital    = req.capital,
        params     = json.dumps(req.params),
        status     = "running",
    )
    db.add(job)
    db.commit()

    try:
        # ── Fetch data ────────────────────────────────────────────────────────
        start_dt = datetime.combine(req.start_date, datetime.min.time())
        end_dt   = datetime.combine(req.end_date,   datetime.max.time())
        df       = fetcher.fetch(req.symbol, start_dt, end_dt, req.source, req.interval,
                                 synthetic_intraday=getattr(req, "synthetic_intraday", False))

        # ── Validate ──────────────────────────────────────────────────────────
        val = validator.validate(df)
        if not val.passed:
            raise ValueError(f"Data quality too low ({val.quality_score:.0f}/100): {val.issues}")

        # ── Strategy signals ──────────────────────────────────────────────────
        strategy_cls    = STRATEGY_REGISTRY[strategy_name]
        strategy_params = {**strategy_cls.default_params(), **req.params}

        # Auto-compute GRID bounds when both are 0/equal OR when user bounds don't overlap the data
        if strategy_name == "GRID":
            lo = float(strategy_params.get("lower_bound", 0) or 0)
            hi = float(strategy_params.get("upper_bound", 0) or 0)
            prices   = df["close"].astype(float)
            lo_raw   = float(prices.min())
            hi_raw   = float(prices.max())
            if lo >= hi or lo > hi_raw or hi < lo_raw:
                pad      = (hi_raw - lo_raw) * 0.10
                strategy_params["lower_bound"] = _round_nice(max(1.0, lo_raw - pad), "floor")
                strategy_params["upper_bound"] = _round_nice(hi_raw + pad, "ceil")
                logger.info(
                    "GRID bounds auto-set: lower=%.2f upper=%.2f (from price range %.2f–%.2f)",
                    strategy_params["lower_bound"], strategy_params["upper_bound"],
                    lo_raw, hi_raw,
                )

        strategy_inst   = strategy_cls(**strategy_params)
        signals_df      = strategy_inst.generate_signals(df)

        # ── Determine if Indian costs should apply ────────────────────────────
        auto_indian = req.source in ("nse", "bse") or is_indian(req.symbol)
        use_indian  = req.use_indian_costs or auto_indian
        lot_sz      = get_lot_size(req.symbol) if req.market_type in ("futures", "options") else 1

        # ── Simulate ──────────────────────────────────────────────────────────
        sim = TradeSimulator(
            symbol           = req.symbol,
            capital          = req.capital,
            fee_percent      = req.fee_pct,
            slippage_percent = req.slippage,
            use_indian_costs = use_indian,
            market_type      = req.market_type,
            brokerage_model  = req.brokerage_model,
            brokerage_flat   = req.brokerage_flat,
            brokerage_pct    = req.brokerage_pct,
            lot_size         = lot_sz,
        )
        sim_out = sim.run(signals_df)

        # ── Lot-size validation: catch silent 0-trade F&O failures ───────────
        if lot_sz > 1 and len(sim_out["trades"]) == 0:
            buy_count = int((signals_df["signal"] == "BUY").sum())
            skips     = sim_out.get("lot_size_skips", 0)
            if buy_count > 0 or skips > 0:
                current_price = float(df["close"].iloc[-1])
                min_invest    = lot_sz * current_price
                raise HTTPException(422, detail=(
                    f"No trades executed: {buy_count} BUY signal(s) generated but all quantities "
                    f"were below the minimum lot size ({lot_sz} units per lot). "
                    f"At current price ₹{current_price:,.0f}, you need at least ₹{int(min_invest):,} "
                    f"per order to trade 1 lot ({lot_sz} units × ₹{current_price:,.0f}). "
                    f"Fix options: "
                    f"(1) Increase 'Invest Per Buy' / 'Invest Per Level' to at least ₹{int(min_invest * 1.05):,} "
                    f"(includes 5% cost buffer), OR "
                    f"(2) Switch Market Type to 'Delivery' or 'Intraday' for equity trading without lot-size restrictions."
                ))

        # ── Metrics ───────────────────────────────────────────────────────────
        metrics = calculate_metrics(
            trades       = sim_out["trades"],
            equity_curve = sim_out["equity_curve"],
            timestamps   = sim_out["timestamps"],
            initial_capital = req.capital,
        )

        # ── Regime classification + breakdown ─────────────────────────────────
        regime_labels = classify_regimes(df)
        # Ensure regime_labels aligns 1:1 with the candle timestamps sent to
        # the frontend (metrics["timestamps"] has one entry per candle = len(df)).
        _n_candles = len(df)
        if len(regime_labels) > _n_candles:
            regime_labels = regime_labels[-_n_candles:]
        elif len(regime_labels) < _n_candles:
            regime_labels = ["sideways"] * (_n_candles - len(regime_labels)) + regime_labels

        regimes_data  = regime_breakdown(
            equity_curve    = sim_out["equity_curve"],
            timestamps      = sim_out["timestamps"],
            trades          = sim_out["trades"],
            regimes         = regime_labels,
            initial_capital = req.capital,
        )

        # ── Out-of-sample validation (holdout / walk-forward) ────────────────
        validation_data: dict | None = None
        if req.validation_mode != "none":
            # Build sim_kwargs once so validation runs use identical cost settings
            _sim_kwargs = dict(
                symbol           = req.symbol,
                capital          = req.capital,
                fee_percent      = req.fee_pct,
                slippage_percent = req.slippage,
                use_indian_costs = use_indian,
                market_type      = req.market_type,
                brokerage_model  = req.brokerage_model,
                brokerage_flat   = req.brokerage_flat,
                brokerage_pct    = req.brokerage_pct,
                lot_size         = lot_sz,
            )
            if req.validation_mode == "holdout":
                validation_data = run_holdout(
                    df              = df,
                    strategy_name   = strategy_name,
                    strategy_params = strategy_params,
                    sim_kwargs      = _sim_kwargs,
                    capital         = req.capital,
                    train_ratio     = req.train_ratio,
                )
            elif req.validation_mode == "walk_forward":
                validation_data = run_walk_forward(
                    df              = df,
                    strategy_name   = strategy_name,
                    strategy_params = strategy_params,
                    sim_kwargs      = _sim_kwargs,
                    capital         = req.capital,
                    window          = req.wf_window,
                    step            = req.wf_step,
                    interval        = req.interval,
                )

        # ── Persist results ───────────────────────────────────────────────────
        result = models.BacktestResult(
            backtest_id       = backtest_id,
            total_return      = metrics["total_return_usd"],
            total_return_pct  = metrics["total_return_pct"],
            sharpe_ratio      = metrics["sharpe_ratio"],
            sortino_ratio     = metrics["sortino_ratio"],
            max_drawdown      = metrics["max_drawdown_pct"],
            profit_factor     = metrics["profit_factor"] if metrics["profit_factor"] != float("inf") else 9999,
            win_rate          = metrics["win_rate"],
            num_trades        = metrics["num_trades"],
            trades_per_day    = metrics["trades_per_day"],
            avg_trade_duration = metrics["avg_trade_duration"],
            best_trade        = metrics["best_trade"],
            worst_trade       = metrics["worst_trade"],
            results_json      = json.dumps(_sanitize({
                k: v for k, v in metrics.items()
                if k not in ("equity_curve", "drawdowns", "timestamps", "trades")
            })),
        )
        db.add(result)

        # Persist trades
        for t in sim_out["trades"]:
            db.add(models.Trade(
                backtest_id = backtest_id,
                entry_time  = pd.Timestamp(t["entry_time"]).to_pydatetime(),
                entry_price = t["entry_price"],
                exit_time   = pd.Timestamp(t["exit_time"]).to_pydatetime(),
                exit_price  = t["exit_price"],
                quantity    = t["quantity"],
                pnl         = t["pnl"],
                pnl_pct     = t["pnl_pct"],
                fees        = t["fees"],
            ))

        job.status = "completed"
        db.commit()

        # Store full metrics (including curves) in memory cache for report gen
        _cache[backtest_id] = {"metrics": metrics, "ohlcv": df, "params": strategy_params}

        # ── Generate HTML report automatically ────────────────────────────────
        report_path = generate_report(
            backtest_id = backtest_id,
            symbol      = req.symbol,
            strategy    = strategy_name,
            params      = strategy_params,
            metrics     = metrics,
            ohlcv_df    = df,
        )

        # ── Currency detection ────────────────────────────────────────────────
        currency = "₹" if (req.source in ("nse", "bse") or is_indian(req.symbol)) else "$"

        # ── Indian cost summary ───────────────────────────────────────────────
        cost_breakdown = sim_out.get("cost_breakdown", {})
        if use_indian and not cost_breakdown:
            # If Indian costs were applied but breakdown wasn't tracked (shouldn't happen)
            cost_breakdown = {"total": sim_out["total_fees_paid"]}

        # The simulator prepends initial_capital to equity_curve (making it N+1)
        # but timestamps / regime_labels are N entries (one per candle).
        # Strip the leading synthetic entry so all four arrays are N-length
        # and aligned 1:1 — canonical fix for NaN-NaN-NaN on charts.
        _ts = metrics["timestamps"]                          # N entries
        _n  = len(_ts)
        _eq = metrics["equity_curve"][1:] if len(metrics["equity_curve"]) == _n + 1 else metrics["equity_curve"]
        _dd = metrics["drawdowns"][1:]    if len(metrics["drawdowns"])    == _n + 1 else metrics["drawdowns"]

        if validation_data:
            val_ts = validation_data.get("validation_timestamps", [])
            val_n = len(val_ts)
            if "validation_equity_curve" in validation_data:
                val_eq = validation_data["validation_equity_curve"]
                if len(val_eq) == val_n + 1:
                    validation_data["validation_equity_curve"] = val_eq[1:]
            if "validation_drawdowns" in validation_data:
                val_dd = validation_data["validation_drawdowns"]
                if len(val_dd) == val_n + 1:
                    validation_data["validation_drawdowns"] = val_dd[1:]


        # Build response and sanitize ALL floats (inf/nan crash FastAPI's JSON encoder)
        return _sanitize({
            "backtest_id": backtest_id,
            "status":      "completed",
            "report_url":  f"/api/report/{backtest_id}",
            "report_file": str(report_path),
            "currency":    currency,
            "market_type": req.market_type if use_indian else "crypto",
            "results": {
                "total_return_pct":       metrics["total_return_pct"],
                "total_return_usd":       metrics["total_return_usd"],
                "annualised_return":      metrics["annualised_return_pct"],
                "annualised_return_pct":  metrics["annualised_return_pct"],
                "sharpe_ratio":           metrics["sharpe_ratio"],
                "sortino_ratio":          metrics["sortino_ratio"],
                "max_drawdown_pct":       metrics["max_drawdown_pct"],
                "calmar_ratio":           metrics["calmar_ratio"],
                "volatility_pct":         metrics["volatility_pct"],
                "win_rate":               metrics["win_rate"],
                "profit_factor":          metrics["profit_factor"],   # may be inf → 9999
                "num_trades":             metrics["num_trades"],
                "best_trade":             metrics["best_trade"],
                "worst_trade":            metrics["worst_trade"],
                "final_equity":           metrics["final_equity"],
                "initial_capital":        req.capital,
                "avg_trade_pnl":          metrics["avg_trade_pnl"],
                "avg_trade_duration":     metrics["avg_trade_duration"],
                "gross_profit":           metrics["gross_profit"],
                "gross_loss":             metrics["gross_loss"],
                "total_fees_paid":        sim_out["total_fees_paid"],
                "data_quality_score":     val.quality_score,
                # Indian-specific cost breakdown
                "cost_breakdown":         cost_breakdown,
                # Market regime breakdown (bull / bear / sideways)
                "regimes":                regimes_data,
            },
            # Full time-series data for the React frontend charts.
            # All four arrays (_eq, _dd, _ts, regime_labels) are guaranteed N-length.
            "series": {
                "equity_curve":  _eq,
                "drawdowns":     _dd,
                "timestamps":    _ts,
                "trades":        metrics["trades"],
                "close_prices":  df["close"].tolist(),
                "regime_labels": regime_labels,   # already N-length from classify_regimes
            },
            # Out-of-sample validation (present only when validation_mode != "none")
            **({"validation": validation_data} if validation_data is not None else {}),
        })

    except HTTPException:
        # Preserve 4xx guidance errors (e.g. 422 lot-size warning) — don't wrap as 500
        raise
    except Exception as exc:
        job.status    = "error"
        job.error_msg = str(exc)
        db.commit()
        logger.exception("Backtest %s failed: %s", backtest_id, exc)
        raise HTTPException(500, f"Backtest failed: {exc}") from exc


@app.get(f"{API_PREFIX}/backtest/{{backtest_id}}", tags=["Backtest"])
def get_backtest(backtest_id: str, db: Session = Depends(get_db)):
    """Retrieve full backtest metadata and metrics."""
    job = db.query(models.Backtest).filter(models.Backtest.id == backtest_id).first()
    if not job:
        raise HTTPException(404, f"Backtest '{backtest_id}' not found")

    out = {
        "backtest_id": job.id,
        "symbol":      job.symbol,
        "strategy":    job.strategy,
        "start_date":  str(job.start_date),
        "end_date":    str(job.end_date),
        "capital":     job.capital,
        "params":      job.params_dict,
        "status":      job.status,
        "created_at":  str(job.created_at),
    }
    if job.result:
        out["metrics"] = job.result.to_dict()
    return out


@app.get(f"{API_PREFIX}/backtest/{{backtest_id}}/metrics", tags=["Backtest"])
def get_backtest_metrics(backtest_id: str, db: Session = Depends(get_db)):
    result = db.query(models.BacktestResult).filter(
        models.BacktestResult.backtest_id == backtest_id
    ).first()
    if not result:
        raise HTTPException(404, "Metrics not found")
    return result.to_dict()


@app.get(f"{API_PREFIX}/backtest/{{backtest_id}}/trades", tags=["Backtest"])
def get_backtest_trades(backtest_id: str, db: Session = Depends(get_db)):
    trades = db.query(models.Trade).filter(models.Trade.backtest_id == backtest_id).all()
    return [t.to_dict() for t in trades]


# ─────────────────────────────────────────────────────────────────────────────
# ── Analytics endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post(f"{API_PREFIX}/compare", tags=["Analytics"])
def compare_backtests(req: CompareRequest, db: Session = Depends(get_db)):
    """Compare multiple backtests side-by-side."""
    rows = []
    for bid in req.backtest_ids:
        job = db.query(models.Backtest).filter(models.Backtest.id == bid).first()
        if not job:
            continue
        row = {
            "backtest_id": bid,
            "symbol":      job.symbol,
            "strategy":    job.strategy,
            "start_date":  str(job.start_date),
            "end_date":    str(job.end_date),
        }
        if job.result:
            row.update(job.result.to_dict())
        rows.append(row)

    if not rows:
        raise HTTPException(404, "No matching backtests found")

    # Simple ranking
    for metric in ["total_return_pct", "sharpe_ratio", "win_rate"]:
        vals = [(r["backtest_id"], r.get(metric, 0)) for r in rows]
        vals.sort(key=lambda x: x[1], reverse=True)
        best_id = vals[0][0] if vals else None
        for r in rows:
            if r["backtest_id"] == best_id:
                r[f"best_{metric}"] = True

    return {"count": len(rows), "comparison": rows}


@app.post(f"{API_PREFIX}/optimize", tags=["Analytics"])
def optimize(req: OptimizeRequest, db: Session = Depends(get_db)):
    """
    Grid-search over param_ranges to find the best parameter set.
    Runs a backtest for every combination.
    """
    import itertools

    strategy_name = req.strategy.upper()
    if strategy_name not in STRATEGY_REGISTRY:
        raise HTTPException(400, f"Unknown strategy '{strategy_name}'")

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    param_names  = list(req.param_ranges.keys())
    param_values = list(req.param_ranges.values())
    combos       = list(itertools.product(*param_values))

    if len(combos) > 200:
        raise HTTPException(400, f"Too many combinations ({len(combos)}). Limit: 200")

    start_dt = datetime.combine(req.start_date, datetime.min.time())
    end_dt   = datetime.combine(req.end_date,   datetime.max.time())
    df       = fetcher.fetch(req.symbol, start_dt, end_dt, req.source)

    results = []
    best    = None
    best_val = float("-inf")

    for combo in combos:
        params = dict(zip(param_names, combo))
        try:
            merged = {**strategy_cls.default_params(), **params}
            inst   = strategy_cls(**merged)
            sigs   = inst.generate_signals(df.copy())
            sim    = TradeSimulator(req.symbol, req.capital)
            out    = sim.run(sigs)
            met    = calculate_metrics(out["trades"], out["equity_curve"], out["timestamps"], req.capital)
            score  = met.get(req.metric, 0)
            if score == float("inf"):
                score = 9999.0
            entry  = {**params, req.metric: round(score, 4),
                      "total_return_pct": met["total_return_pct"],
                      "num_trades": met["num_trades"]}
            results.append(entry)
            if score > best_val:
                best_val = score
                best     = entry
        except Exception as exc:
            results.append({**params, "error": str(exc)})

    results.sort(key=lambda x: x.get(req.metric, float("-inf")), reverse=True)

    return _sanitize({
        "symbol":          req.symbol,
        "strategy":        strategy_name,
        "metric":          req.metric,
        "combinations_tested": len(combos),
        "best_params":     best,
        "all_results":     results[:50],   # top 50
    })


# ─────────────────────────────────────────────────────────────────────────────
# ── Report endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/report/{{backtest_id}}", tags=["Reports"])
def get_report(backtest_id: str, db: Session = Depends(get_db)):
    """Return the HTML report for a backtest."""
    report_file = REPORTS_DIR / f"report_{backtest_id}.html"

    if not report_file.exists():
        # Try to regenerate from DB
        cached = _cache.get(backtest_id)
        if cached:
            job = db.query(models.Backtest).filter(models.Backtest.id == backtest_id).first()
            if job:
                report_file = generate_report(
                    backtest_id = backtest_id,
                    symbol      = job.symbol,
                    strategy    = job.strategy,
                    params      = cached["params"],
                    metrics     = cached["metrics"],
                    ohlcv_df    = cached["ohlcv"],
                )
        if not report_file.exists():
            raise HTTPException(404, f"Report '{backtest_id}' not found. Run the backtest first.")

    return FileResponse(str(report_file), media_type="text/html")


@app.post(f"{API_PREFIX}/report/generate", tags=["Reports"])
def generate_report_endpoint(
    backtest_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """Regenerate an HTML report from cached data."""
    cached = _cache.get(backtest_id)
    if not cached:
        raise HTTPException(404, f"No cached data for backtest '{backtest_id}'. Re-run the backtest.")

    job = db.query(models.Backtest).filter(models.Backtest.id == backtest_id).first()
    if not job:
        raise HTTPException(404, f"Backtest '{backtest_id}' not found")

    path = generate_report(
        backtest_id = backtest_id,
        symbol      = job.symbol,
        strategy    = job.strategy,
        params      = cached["params"],
        metrics     = cached["metrics"],
        ohlcv_df    = cached["ohlcv"],
    )
    return {"report_url": f"/api/report/{backtest_id}", "file_path": str(path)}


# ─────────────────────────────────────────────────────────────────────────────
# ── Stress Test endpoint
# ─────────────────────────────────────────────────────────────────────────────

class StressRequest(BaseModel):
    # ── Dataset ────────────────────────────────────────────────────────────────
    symbol:     str   = Field("BTC/USDT")
    source:     str   = Field("binance")
    interval:   str   = Field("1d")
    start_date: date  = Field(...)
    end_date:   date  = Field(...)
    capital:    float = Field(DEFAULT_CAPITAL)
    # ── Strategy ───────────────────────────────────────────────────────────────
    strategy:   str   = Field("DCA")
    params:     dict  = Field(default_factory=dict)
    # ── Simulator ──────────────────────────────────────────────────────────────
    fee_pct:         float = Field(DEFAULT_FEE_PERCENT)
    slippage:        float = Field(DEFAULT_SLIPPAGE_PERCENT)
    use_indian_costs: bool = Field(False)
    market_type:     str   = Field("equity_delivery")
    brokerage_model: str   = Field("flat")
    brokerage_flat:  float = Field(20.0)
    brokerage_pct:   float = Field(0.005)
    # ── Stress configuration ───────────────────────────────────────────────────
    scenario_key:        str            = Field("covid_crash", description="Key from SCENARIO_PRESETS")
    severity:            float          = Field(1.0,  description="0.5=mild, 1.0=moderate, 1.5=severe")
    shock_depth_pct:     Optional[float] = Field(None, description="Override scenario default")
    shock_duration_days: Optional[int]   = Field(None)
    vol_multiplier:      Optional[float] = Field(None)
    outlier_count:       int            = Field(0,    description="Extra outliers layered on scenario")
    monte_carlo_runs:    int            = Field(1,    description="1=deterministic; 100/500/1000 for MC")
    seed:                Optional[int]  = Field(None)
    # Trade-level MC
    trade_mc_runs:       int            = Field(0,    description="0=disabled; 200+ for trade-level MC (reshuffle+skip)")
    trade_skip_pct:      float          = Field(0.10, description="Fraction of trades to randomly skip per run (0.0–0.5)")
    # Walk-forward validation (wires into Robustness Score overfit-resistance axis)
    run_validation:      bool           = Field(False, description="Run walk-forward to compute Walk-Forward Efficiency (WFE) for the Robustness Score")
    wf_window:           int            = Field(252,   description="Walk-forward train window in candles (default 252 = ~1yr daily)")
    wf_step:             int            = Field(63,    description="Walk-forward OOS step in candles (default 63 = ~1qtr daily)")
    # Regime-aware MC: scale per-run severity by the asset's bull/bear/sideways volatility profile
    regime_aware_mc:       bool           = Field(False, description="Scale MC run severity by regime-specific realized volatility for physically realistic path fanning")
    # Synthetic intraday: generate 15m/1h candles from daily OHLCV for unlimited history
    synthetic_intraday:    bool           = Field(False, description="Generate synthetic intraday from daily OHLCV via Brownian Bridge disaggregation (NSE/BSE only; unlimited free history)")


@app.post(f"{API_PREFIX}/stress/run", tags=["Stress"])
def run_stress(req: StressRequest, db: Session = Depends(get_db)):
    """
    Run baseline + N stress-perturbed backtests on real OHLCV data.
    Returns baseline metrics, stressed metrics, optional Monte Carlo percentiles,
    and equity/price series for charting.
    """
    if req.strategy.upper() not in STRATEGY_REGISTRY:
        raise HTTPException(400, f"Unknown strategy '{req.strategy}'. Choose: {list(STRATEGY_REGISTRY)}")

    if req.scenario_key not in SCENARIO_PRESETS:
        raise HTTPException(400, f"Unknown scenario '{req.scenario_key}'. Choose: {list(SCENARIO_PRESETS)}")

    # ── Fetch OHLCV ──────────────────────────────────────────────────────────
    try:
        start_dt = datetime.combine(req.start_date, datetime.min.time())
        end_dt   = datetime.combine(req.end_date,   datetime.max.time())
        df       = fetcher.fetch(req.symbol, start_dt, end_dt, req.source, req.interval,
                                 synthetic_intraday=req.synthetic_intraday)
    except Exception as exc:
        raise HTTPException(500, f"Data fetch failed: {exc}")

    if df is None or df.empty:
        raise HTTPException(422, "No data returned for the given symbol / date range.")

    # ── Build scenario (apply custom overrides) ───────────────────────────────
    scenario = deepcopy(SCENARIO_PRESETS[req.scenario_key])
    if req.shock_depth_pct  is not None: scenario.shock_depth_pct     = req.shock_depth_pct
    if req.shock_duration_days is not None: scenario.shock_duration_days = req.shock_duration_days
    if req.vol_multiplier   is not None: scenario.vol_multiplier       = req.vol_multiplier

    # ── Build strategy params ────────────────────────────────────────────────
    strategy_cls    = STRATEGY_REGISTRY[req.strategy.upper()]
    strategy_params = {**strategy_cls.default_params(), **req.params}

    # Auto-compute GRID bounds when both are 0/equal OR when user bounds don't overlap the data
    if req.strategy.upper() == "GRID":
        lo = float(strategy_params.get("lower_bound", 0) or 0)
        hi = float(strategy_params.get("upper_bound", 0) or 0)
        prices   = df["close"].astype(float)
        lo_raw   = float(prices.min())
        hi_raw   = float(prices.max())
        if lo >= hi or lo > hi_raw or hi < lo_raw:
            pad      = (hi_raw - lo_raw) * 0.10
            strategy_params["lower_bound"] = _round_nice(max(1.0, lo_raw - pad), "floor")
            strategy_params["upper_bound"] = _round_nice(hi_raw + pad, "ceil")
            logger.info(
                "GRID bounds auto-set: lower=%.2f upper=%.2f (from price range %.2f-%.2f)",
                strategy_params["lower_bound"], strategy_params["upper_bound"],
                lo_raw, hi_raw,
            )

    # ── Build simulator kwargs ────────────────────────────────────────────────
    auto_indian   = req.source in ("nse", "bse") or is_indian(req.symbol)
    use_indian    = req.use_indian_costs or auto_indian
    lot_sz        = get_lot_size(req.symbol) if req.market_type in ("futures", "options") else 1

    sim_kwargs = dict(
        symbol           = req.symbol,
        fee_percent      = req.fee_pct,
        slippage_percent = req.slippage,
        use_indian_costs = use_indian,
        market_type      = req.market_type,
        brokerage_model  = req.brokerage_model,
        brokerage_flat   = req.brokerage_flat,
        brokerage_pct    = req.brokerage_pct,
        lot_size         = lot_sz,
    )

    # ── Run stress backtest ───────────────────────────────────────────────────
    try:
        result = run_stress_backtest(
            df                  = df,
            strategy_cls        = strategy_cls,
            strategy_params     = strategy_params,
            sim_kwargs          = sim_kwargs,
            capital             = req.capital,
            scenario            = scenario,
            severity            = req.severity,
            monte_carlo_runs    = max(1, req.monte_carlo_runs),
            extra_outlier_count = req.outlier_count,
            seed                = req.seed,
            regime_aware_mc     = req.regime_aware_mc,
        )
    except Exception as exc:
        logger.exception("Stress backtest failed")
        raise HTTPException(500, f"Stress backtest error: {exc}")

    # ── Walk-forward validation (optional — upgrades Robustness Score) ───────
    wf_result: Optional[dict] = None
    if req.run_validation:
        try:
            wf_result = run_walk_forward(
                df              = df,
                strategy_name   = req.strategy.upper(),
                strategy_params = strategy_params,
                sim_kwargs      = {**sim_kwargs, "capital": req.capital},
                capital         = req.capital,
                window          = req.wf_window,
                step            = req.wf_step,
                interval        = req.interval,
            )
            wfe = compute_wfe(wf_result)
            if wfe is not None:
                result["robustness"] = compute_robustness_score(
                    result.get("baseline", {}), result.get("monte_carlo"), req.capital, wfe=wfe
                )
                result["robustness"]["walk_forward_windows"] = len(wf_result.get("windows", []))
        except Exception as exc:
            logger.warning("Walk-forward for stress failed (non-fatal): %s", exc)

    # ── Trade-level MC (optional, runs on baseline trades) ───────────────────
    trade_mc_result: Optional[dict] = None
    if req.trade_mc_runs > 0:
        baseline_trades = result.get("baseline", {}).get("trades", [])
        # baseline dict has trades stripped; re-run baseline to get them
        baseline_full = run_single_backtest(df, strategy_cls, strategy_params, sim_kwargs, req.capital)
        baseline_trades = baseline_full.get("trades", [])
        if baseline_trades:
            trade_mc_result = run_trade_mc(
                trades         = baseline_trades,
                capital        = req.capital,
                n_runs         = min(req.trade_mc_runs, 2000),
                trade_skip_pct = max(0.0, min(0.5, req.trade_skip_pct)),
                seed           = req.seed,
            )

    backtest_id = str(uuid.uuid4())[:8]
    return _sanitize({
        "backtest_id": backtest_id,
        "symbol":      req.symbol,
        "strategy":    req.strategy.upper(),
        **result,
        **({"trade_mc":      trade_mc_result} if trade_mc_result else {}),
        **({"walk_forward":  wf_result}        if wf_result       else {}),
    })


@app.get(f"{API_PREFIX}/stress/scenarios", tags=["Stress"])
def list_stress_scenarios():
    """Return all available stress scenario keys with display names and defaults."""
    return {
        key: {
            "display_name":        s.display_name,
            "shock_depth_pct":     s.shock_depth_pct,
            "shock_duration_days": s.shock_duration_days,
            "vol_multiplier":      s.vol_multiplier,
            "slip_multiplier":     s.slip_multiplier,
            "direction":           s.direction,
            "has_outliers":        s.outlier_count > 0,
        }
        for key, s in SCENARIO_PRESETS.items()
    }


@app.post(f"{API_PREFIX}/stress/stream", tags=["Stress"])
async def stream_stress_sse(req: StressRequest, db: Session = Depends(get_db)):
    """
    SSE streaming version of the stress test.
    Yields server-sent events as each MC run completes so the frontend can
    animate paths in real-time.

    Event types:
      {type: "baseline", metrics: {...}}
      {type: "run",      run_num: N, total: N, metrics: {...}, equity: [...]}
      {type: "complete", result: {...}}   — same shape as /stress/run
      {type: "error",    message: "..."}
    """
    if req.strategy.upper() not in STRATEGY_REGISTRY:
        raise HTTPException(400, f"Unknown strategy '{req.strategy}'")
    if req.scenario_key not in SCENARIO_PRESETS:
        raise HTTPException(400, f"Unknown scenario '{req.scenario_key}'")

    # ── Fetch data (blocking — run once before streaming) ────────────────────
    try:
        start_dt = datetime.combine(req.start_date, datetime.min.time())
        end_dt   = datetime.combine(req.end_date,   datetime.max.time())
        df = await asyncio.to_thread(
            fetcher.fetch, req.symbol, start_dt, end_dt, req.source, req.interval,
            req.synthetic_intraday,
        )
    except Exception as exc:
        raise HTTPException(500, f"Data fetch failed: {exc}")

    if df is None or df.empty:
        raise HTTPException(422, "No data returned for the given symbol / date range.")

    # ── Build scenario ────────────────────────────────────────────────────────
    scenario = deepcopy(SCENARIO_PRESETS[req.scenario_key])
    if req.shock_depth_pct     is not None: scenario.shock_depth_pct     = req.shock_depth_pct
    if req.shock_duration_days is not None: scenario.shock_duration_days = req.shock_duration_days
    if req.vol_multiplier      is not None: scenario.vol_multiplier      = req.vol_multiplier

    strategy_cls    = STRATEGY_REGISTRY[req.strategy.upper()]
    strategy_params = {**strategy_cls.default_params(), **req.params}

    # Auto-compute GRID bounds when both are 0/equal OR when user bounds don't overlap the data
    if req.strategy.upper() == "GRID":
        lo = float(strategy_params.get("lower_bound", 0) or 0)
        hi = float(strategy_params.get("upper_bound", 0) or 0)
        prices   = df["close"].astype(float)
        lo_raw   = float(prices.min())
        hi_raw   = float(prices.max())
        if lo >= hi or lo > hi_raw or hi < lo_raw:
            pad      = (hi_raw - lo_raw) * 0.10
            strategy_params["lower_bound"] = _round_nice(max(1.0, lo_raw - pad), "floor")
            strategy_params["upper_bound"] = _round_nice(hi_raw + pad, "ceil")
            logger.info(
                "GRID bounds auto-set: lower=%.2f upper=%.2f (from price range %.2f-%.2f)",
                strategy_params["lower_bound"], strategy_params["upper_bound"],
                lo_raw, hi_raw,
            )

    auto_indian = req.source in ("nse", "bse") or is_indian(req.symbol)
    use_indian  = req.use_indian_costs or auto_indian
    lot_sz      = get_lot_size(req.symbol) if req.market_type in ("futures", "options") else 1

    sim_kwargs = dict(
        symbol           = req.symbol,
        fee_percent      = req.fee_pct,
        slippage_percent = req.slippage,
        use_indian_costs = use_indian,
        market_type      = req.market_type,
        brokerage_model  = req.brokerage_model,
        brokerage_flat   = req.brokerage_flat,
        brokerage_pct    = req.brokerage_pct,
        lot_size         = lot_sz,
    )

    # Capture mutable state for the generator
    df_snap          = df.copy()
    scenario_snap    = scenario
    req_snap         = req
    strategy_cls_    = strategy_cls
    strategy_params_ = strategy_params
    sim_kwargs_      = sim_kwargs

    async def _generate():
        import numpy as np_

        def _ev(obj: dict) -> str:
            return f"data: {json.dumps(_sanitize(obj))}\n\n"

        n_runs = max(1, req_snap.monte_carlo_runs)

        # WFE is deferred — runs after all MC paths so baseline appears immediately.
        wf_result_sse: Optional[dict] = None
        wfe_sse: Optional[float] = None

        # ── Baseline ─────────────────────────────────────────────────────────
        try:
            baseline = await asyncio.to_thread(
                run_single_backtest,
                df_snap, strategy_cls_, strategy_params_, sim_kwargs_, req_snap.capital,
            )
        except Exception as exc:
            yield _ev({"type": "error", "message": str(exc)})
            return

        safe_baseline = {k: v for k, v in baseline.items()
                         if k not in ("equity_curve", "drawdowns", "timestamps", "trades")}
        yield _ev({"type": "baseline", "metrics": safe_baseline, "total": n_runs,
                   **({"wfe": wfe_sse} if wfe_sse is not None else {})})

        # ── Effective scenario (with extra outliers) ──────────────────────────
        eff_scenario = deepcopy(scenario_snap)
        if req_snap.outlier_count > 0:
            eff_scenario.outlier_count += req_snap.outlier_count

        stressed_sim_kw = {**sim_kwargs_}
        if eff_scenario.slip_multiplier > 1.0:
            base_slip = stressed_sim_kw.get("slippage_percent", 0.001)
            stressed_sim_kw["slippage_percent"] = (
                base_slip * eff_scenario.slip_multiplier * req_snap.severity
            )

        # ── Regime-aware MC setup (once before the loop) ─────────────────────
        sse_regime_vol_scales: Optional[dict] = None
        sse_regime_fractions:  Optional[dict] = None
        if req_snap.regime_aware_mc:
            try:
                _sse_labels = await asyncio.to_thread(classify_regimes, df_snap)
                sse_regime_vol_scales, sse_regime_fractions = await asyncio.to_thread(
                    _compute_regime_vol_scales, df_snap, _sse_labels
                )
            except Exception as exc:
                logger.warning("Regime classification (SSE) failed, using flat jitter: %s", exc)

        # ── MC runs ──────────────────────────────────────────────────────────
        master_rng = np_.random.default_rng(req_snap.seed)
        per_run:      list[dict]       = []
        equity_curves: list[list[float]] = []
        price_curves:  list[list[float]] = []
        _regime_names_sse = ["bull", "bear", "sideways"]

        for i in range(n_runs):
            run_seed = int(master_rng.integers(0, 2 ** 31))
            if n_runs == 1:
                run_severity = req_snap.severity
            elif (req_snap.regime_aware_mc
                  and sse_regime_vol_scales is not None
                  and sse_regime_fractions  is not None):
                probs = [max(0.0, sse_regime_fractions.get(r, 0.0)) for r in _regime_names_sse]
                total_p = sum(probs)
                probs = [p / total_p for p in probs] if total_p > 0 else [1/3, 1/3, 1/3]
                chosen_idx    = int(master_rng.choice(len(_regime_names_sse), p=probs))
                chosen_regime = _regime_names_sse[chosen_idx]
                regime_scale  = sse_regime_vol_scales.get(chosen_regime, 1.0)
                run_severity  = req_snap.severity * regime_scale * float(master_rng.uniform(0.85, 1.15))
            else:
                run_severity = float(req_snap.severity * master_rng.uniform(0.75, 1.25))
            perturbed_df = await asyncio.to_thread(
                apply_stress, df_snap, eff_scenario, run_severity, run_seed
            )
            m = await asyncio.to_thread(
                run_single_backtest,
                perturbed_df, strategy_cls_, strategy_params_, stressed_sim_kw, req_snap.capital,
            )

            eq     = m.get("equity_curve", [req_snap.capital])
            n_ts   = min(len(eq), 200)
            ts_idx = [round(j * (len(eq) - 1) / max(n_ts - 1, 1)) for j in range(n_ts)]
            eq_sub = [round(float(eq[j]), 2) for j in ts_idx]

            run_data = {
                "run_idx":          i,
                "return_pct":       round(float(m.get("total_return_pct",     0.0)), 4),
                "sharpe":           round(float(m.get("sharpe_ratio",         0.0)), 4),
                "sortino":          round(float(m.get("sortino_ratio",        0.0)), 4),
                "calmar":           round(float(m.get("calmar_ratio",         0.0)), 4),
                "max_dd_pct":       round(float(m.get("max_drawdown_pct",     0.0)), 4),
                "win_rate":         round(float(m.get("win_rate",             0.0)), 4),
                "num_trades":       int(m.get("num_trades",                    0)),
                "final_equity":     round(float(m.get("final_equity", req_snap.capital)), 2),
                "annualized_return":round(float(m.get("annualised_return_pct", 0.0)), 4),
            }
            per_run.append(run_data)
            equity_curves.append(eq)
            price_curves.append(perturbed_df["close"].tolist())

            yield _ev({
                "type":    "run",
                "run_num": i + 1,
                "total":   n_runs,
                "metrics": run_data,
                "equity":  eq_sub,
            })

        # ── Walk-forward (after all MC runs so baseline + paths stream first) ──
        if req_snap.run_validation:
            try:
                wf_result_sse = await asyncio.to_thread(
                    run_walk_forward,
                    df_snap, req_snap.strategy.upper(), strategy_params_,
                    {**sim_kwargs_, "capital": req_snap.capital},
                    req_snap.capital, req_snap.wf_window, req_snap.wf_step,
                    req_snap.interval,
                )
                wfe_sse = compute_wfe(wf_result_sse)
            except Exception as exc:
                logger.warning("Walk-forward for stress (SSE) failed: %s", exc)

        # ── Final aggregation ─────────────────────────────────────────────────
        try:
            agg = await asyncio.to_thread(
                aggregate_stress_results,
                baseline, per_run, equity_curves, price_curves,
                df_snap, req_snap.capital, scenario_snap, req_snap.severity,
            )
        except Exception as exc:
            yield _ev({"type": "error", "message": f"Aggregation failed: {exc}"})
            return

        # ── Trade-level MC (optional) ─────────────────────────────────────────
        trade_mc_result_sse: Optional[dict] = None
        if req_snap.trade_mc_runs > 0:
            baseline_trades_sse = baseline.get("trades", [])
            if baseline_trades_sse:
                trade_mc_result_sse = await asyncio.to_thread(
                    run_trade_mc,
                    baseline_trades_sse,
                    req_snap.capital,
                    min(req_snap.trade_mc_runs, 2000),
                    max(0.0, min(0.5, req_snap.trade_skip_pct)),
                    req_snap.seed,
                )

        # Update robustness score with WFE if walk-forward was run
        if wfe_sse is not None and "robustness" in agg:
            agg["robustness"] = compute_robustness_score(
                agg.get("baseline", {}), agg.get("monte_carlo"), req_snap.capital, wfe=wfe_sse
            )
            agg["robustness"]["walk_forward_windows"] = len(wf_result_sse.get("windows", [])) if wf_result_sse else 0

        # Attach regime_mc_info if regime-aware MC was used
        sse_regime_mc_info: Optional[dict] = None
        if req_snap.regime_aware_mc and sse_regime_vol_scales is not None:
            sse_regime_mc_info = {
                "enabled":           True,
                "regime_fractions":  {k: round(v, 4) for k, v in (sse_regime_fractions or {}).items()},
                "regime_vol_scales": {k: round(v, 4) for k, v in sse_regime_vol_scales.items()},
            }

        backtest_id = str(uuid.uuid4())[:8]
        yield _ev({
            "type":   "complete",
            "result": {
                "backtest_id": backtest_id,
                "symbol":      req_snap.symbol,
                "strategy":    req_snap.strategy.upper(),
                **agg,
                **({"trade_mc":       trade_mc_result_sse} if trade_mc_result_sse  else {}),
                **({"walk_forward":   wf_result_sse}       if wf_result_sse        else {}),
                **({"regime_mc_info": sse_regime_mc_info}  if sse_regime_mc_info   else {}),
            },
        })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "Connection":       "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# ── Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,   # reload=True caused constant restarts: logs/backtester.log
                        # and optimizer_results/ writes triggered watchfiles every 400ms,
                        # freezing the event loop. Restart the server manually after code changes.
    )
