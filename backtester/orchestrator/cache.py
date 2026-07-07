"""
Strategy cache lookup — dedups identical (IR, symbol, timeframe) combos
against the outcome log so a repeat submission serves an instant cached
report instead of re-running the whole pipeline. Extends the existing
StrategyOutcome table rather than introducing a new datastore.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from sqlalchemy.orm import Session

import models


def compute_cache_key(ir: dict[str, Any], symbol: str, timeframe: str) -> str:
    """Stable hash of normalised IR + symbol + timeframe, order-independent on params."""
    strategy = str(ir.get("strategy", "")).upper()
    params = ir.get("params", {}) or {}
    normalized = {
        "strategy": strategy,
        "params": {k: params[k] for k in sorted(params)},
        "symbol": symbol.upper(),
        "timeframe": timeframe,
    }
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def find_cached_outcome(db: Session, cache_key: str) -> Optional[models.StrategyOutcome]:
    """
    Look up a prior StrategyOutcome matching this cache key.

    StrategyOutcome doesn't store cache_key directly (it predates this
    feature and is written on every backtest, cache-aware or not) — so the
    lookup recomputes each candidate row's key from its own strategy/params/
    symbol columns and compares. Cheap at current row counts; if this table
    grows large, add a `cache_key` column to StrategyOutcome and index it
    instead of recomputing per row.
    """
    candidates = (
        db.query(models.StrategyOutcome)
        .order_by(models.StrategyOutcome.created_at.desc())
        .limit(500)
        .all()
    )
    for row in candidates:
        try:
            params = json.loads(row.params) if row.params else {}
        except (TypeError, ValueError):
            params = {}
        ir = {"strategy": row.strategy, "params": params}
        timeframe = row.interval or "1d"
        if compute_cache_key(ir, row.symbol, timeframe) == cache_key:
            return row
    return None
