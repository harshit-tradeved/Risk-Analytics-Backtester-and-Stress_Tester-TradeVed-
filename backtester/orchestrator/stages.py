"""
Pure stage functions for the unified pipeline. Each function does ONE piece
of work and returns a plain dict/DataFrame — no DB reads or writes here.
`orchestrator/pipeline.py` is the only place that touches the PipelineRun
row; that keeps these functions independently testable and reusable (the
same run_loop_round, for instance, is used both by the normal loop and by
the retry-symbol re-entry path).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from data.fetcher import DataFetcher, is_forex_pair
from data.validator import DataValidator
from engine.metrics import score_backtest
from engine.validation import run_segment_backtest, run_holdout, run_walk_forward
from ir_validator import validate_ir, normalize_ir
from strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)

_fetcher = DataFetcher()
_validator = DataValidator()

# The DataFetcher's actual source registry — anything else an LLM suggests
# (arbitrary casing, "forex", "oanda", ...) must be sanitized before use.
_ALLOWED_SOURCES = {"binance", "yfinance", "nse", "bse", "auto"}


def fetch_and_validate_data(
    symbol: str, source: str, interval: str, start_date: date, end_date: date,
) -> pd.DataFrame:
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    df = _fetcher.fetch(symbol, start_dt, end_dt, source, interval)
    result = _validator.validate(df, interval=interval)
    if not result.passed:
        raise ValueError(f"Data quality too low ({result.quality_score:.0f}/100): {result.issues}")
    return df


def extract_ir(transcript: str, caption: str, tweak: Optional[str] = None) -> dict[str, Any]:
    """Extract a Strategy IR from a transcript. If a tweak was submitted
    alongside the original input, fold it into the transcript context so
    extraction accounts for it from the start (cheaper than extract-then-patch
    when the tweak is already available)."""
    from reel_extractor import extract_strategy_ir
    effective_transcript = transcript
    if tweak:
        effective_transcript = f"{transcript}\n\n[User's additional instruction: {tweak}]"
    return extract_strategy_ir(effective_transcript, caption)


def validate_and_normalize(ir: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = normalize_ir(ir)
    errors = validate_ir(normalized)
    return normalized, errors


def validate_and_repair(ir: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Like validate_and_normalize, but if the extracted IR fails schema
    validation (e.g. the model invented its own top-level shape instead of
    following the {"strategy": ..., "params": {...}} schema — observed live
    on a real reel after a prompt change), makes one self-repair attempt via
    improvement_agent.repair_improved_ir() before giving up. Reuses the same
    repair mechanic already used for the improve-strategy flow rather than
    adding a second one.
    """
    normalized, errors = validate_and_normalize(ir)
    if not errors:
        return normalized, errors

    from improvement_agent import repair_improved_ir
    repaired = repair_improved_ir(ir, errors, ir)
    if not isinstance(repaired, dict):
        return normalized, errors
    repaired_normalized, repaired_errors = validate_and_normalize(repaired)
    if not repaired_errors:
        return repaired_normalized, []
    return normalized, errors


# Classic strategies already get every field filled in from their own
# default_params() when a backtest actually runs (see run_loop_round below),
# so a missing position-size field never blocks them. Only CUSTOM/indicator
# presets read invest_per_trade_usd — that's the field reel_extractor's own
# prompt already tries to default to 1000, but sometimes withholds when
# bundling it in with other, genuinely-blocking gaps (e.g. a stop-loss the
# schema can't express). This makes that default deterministic in code
# instead of depending on the LLM to have applied its own instruction.
_CLASSIC_STRATEGIES = {"DCA", "GRID", "PLA"}


def apply_default_position_size(ir: dict[str, Any], capital: float) -> dict[str, Any]:
    """Fill a missing/zero invest_per_trade_usd with a capital-scaled default
    (10% of capital, floor $100 / cap $2000) for non-classic strategies."""
    strategy = str(ir.get("strategy", "")).upper()
    if strategy in _CLASSIC_STRATEGIES:
        return ir
    params = ir.get("params", {}) or {}
    if not params.get("invest_per_trade_usd"):
        params = {**params, "invest_per_trade_usd": max(100.0, min(capital * 0.1, 2000.0))}
        ir = {**ir, "params": params}
    return ir


def build_fallback_suggestion(transcript: str, caption: str, gaps: list[str]) -> dict[str, Any]:
    """When extract_ir() genuinely fails (strategy_ir is None, even after its
    own internal retry), ask for a practical disclaimer plus a best-choice
    minimal-viable strategy_ir instead of dead-ending the run."""
    from reel_extractor import suggest_fallback_ir
    return suggest_fallback_ir(transcript, caption, gaps)


def resolve_run_target(
    symbol: Optional[str], source: Optional[str], interval: Optional[str], extraction: dict[str, Any],
) -> tuple[str, str, str]:
    """
    Picks the symbol/source/interval a run actually executes with. An
    explicit caller-supplied value always wins; otherwise falls back to
    extract_strategy_ir()'s own suggested_symbol/suggested_source/
    suggested_interval (inferred from the transcript itself — e.g. an NSE
    stock reel should run on nse/RELIANCE, not the crypto defaults), and
    only falls back to the hardcoded defaults if extraction suggested
    nothing either.
    """
    resolved_symbol = str(symbol or extraction.get("suggested_symbol") or "BTC/USDT").strip()
    resolved_source = str(source or extraction.get("suggested_source") or "binance").strip().lower()
    resolved_interval = str(interval or extraction.get("suggested_interval") or "1d").strip().lower()

    # LLM-suggested sources arrive in arbitrary casing ("BINANCE") or as
    # names that aren't fetchers at all ("forex", "oanda") — found via live
    # E2E run 2026-07-10, where fetchers.get("BINANCE") returned None for
    # every source and the run died with 'Last error: None'. Unknown sources
    # degrade to "auto" (binance→yfinance chain) instead of failing.
    if resolved_source not in _ALLOWED_SOURCES:
        resolved_source = "auto"
    # Fiat forex pairs (AUDCAD, GBPJPY, ...) only exist on yfinance — Binance
    # has no fiat-fiat markets, so honoring a suggested "binance" would
    # guarantee a fetch failure.
    if is_forex_pair(resolved_symbol):
        resolved_source = "yfinance"
    return resolved_symbol, resolved_source, resolved_interval


def fetch_with_source_fallback(
    symbol: str, source: str, interval: str, start_date: date, end_date: date,
) -> tuple[pd.DataFrame, str]:
    """
    fetch_and_validate_data with one safety net: if the resolved source
    fails outright (LLM suggested a source that doesn't carry the symbol),
    retry once with source='auto' (binance→yfinance chain) before letting
    the run fail. Returns (df, source_actually_used).
    """
    try:
        return fetch_and_validate_data(symbol, source, interval, start_date, end_date), source
    except Exception:
        if source == "auto":
            raise
        return fetch_and_validate_data(symbol, "auto", interval, start_date, end_date), "auto"


def patch_ir_with_tweak(ir: dict[str, Any], tweak: str, symbol: str, interval: str) -> dict[str, Any]:
    """
    User typed a tweak during the checkpoint window. Reuses the same
    mechanic as improvement_agent.critique_and_improve() — a single LLM
    call that edits the existing IR — except triggered by user text
    instead of an automated metrics critique, and with no metrics yet
    (there's been no backtest run at checkpoint time).
    """
    from improvement_agent import _llm, _parse_json  # same LLM plumbing critique_and_improve uses

    system = """You are a trading strategy IR editor. The user has an extracted
Strategy IR and wants a specific change applied. Modify ONLY what their
instruction asks for — keep everything else unchanged. Reply with ONLY the
corrected JSON IR object (no markdown, no wrapper):
{"strategy": "<NAME>", "params": {...}}"""
    user = json.dumps({"current_ir": ir, "user_instruction": tweak, "symbol": symbol, "interval": interval})
    try:
        raw = _llm(system, user, max_tokens=900)
        patched = _parse_json(raw)
        return patched if isinstance(patched, dict) and patched.get("strategy") else ir
    except Exception as e:
        logger.error("patch_ir_with_tweak failed: %s", e)
        return ir


def run_loop_round(
    df: pd.DataFrame, ir: dict[str, Any], capital: float, sim_kwargs: dict, symbol: str, interval: str,
) -> dict[str, Any]:
    """Run one backtest for the current IR and score it. Does not decide
    whether to keep looping — that's the caller's job (it needs the
    previous round's score to compare against)."""
    strategy_name = ir["strategy"].upper()
    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    metrics = run_segment_backtest(df, strategy_cls, ir.get("params", {}), sim_kwargs, capital)
    if metrics is None:
        metrics = {"num_trades": 0, "sharpe_ratio": 0.0, "total_return_pct": 0.0,
                   "sortino_ratio": 0.0, "calmar_ratio": 0.0, "max_drawdown_pct": 0.0}
    score = score_backtest(metrics)
    return {"metrics": metrics, "score": score}


def run_holdout_check(df: pd.DataFrame, ir: dict[str, Any], capital: float, sim_kwargs: dict) -> dict[str, Any]:
    strategy_name = ir["strategy"].upper()
    return run_holdout(df, strategy_name, ir.get("params", {}), sim_kwargs, capital)


CHIP_DEFS = [
    {"id": "stress_detail",   "label": "Stress test detail (17 scenarios)", "kind": "instant"},
    {"id": "walk_forward",    "label": "Walk-forward fold breakdown",       "kind": "instant"},
    {"id": "composite_math",  "label": "Composite score math",              "kind": "instant"},
    {"id": "paper_trading",   "label": "Paper trading",                    "kind": "live"},
    {"id": "retry_symbol",    "label": "Try this on another symbol",        "kind": "instant"},
]


def build_report(run: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the concise, verdict-first report plus chip metadata. `run` is
    expected to look like a PipelineRun row (dict of its columns) — callers
    in pipeline.py pass the actual ORM row's __dict__-equivalent fields.
    """
    scores = json.loads(run.get("composite_scores_json") or "[]")
    holdout = json.loads(run.get("holdout_result_json") or "null")
    # The pipeline reverts to the best-scoring IR after the loop (a later
    # "improved" round can score worse), so the report must describe the
    # BEST round's score, not blindly scores[-1]. The raw scores list is
    # left untouched so the UI can still show the full round history.
    last_score = max((s["score"] for s in scores), default=None) if scores else None
    verdict = "No rounds completed yet."
    if holdout:
        v = holdout.get("verdict", "unknown")
        verdict = {
            "stable":   f"Held up out-of-sample on {run.get('symbol', 'this symbol')} — in-sample and holdout results are consistent.",
            "degraded": f"Passed in-sample but weakened out-of-sample on {run.get('symbol', 'this symbol')} — treat with caution.",
            "failed":   f"Passed in-sample but failed the out-of-sample check on {run.get('symbol', 'this symbol')} — likely overfit.",
        }.get(v, "Holdout check produced an unclear result.")
    elif last_score is not None:
        verdict = f"Optimization finished at composite score {last_score:.2f}; holdout check pending."

    return {"verdict": verdict, "last_score": last_score, "chips": CHIP_DEFS}
