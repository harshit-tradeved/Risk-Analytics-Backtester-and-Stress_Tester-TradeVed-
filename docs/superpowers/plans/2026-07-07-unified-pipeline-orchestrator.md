# Unified Pipeline Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `PipelineRun` orchestrator that sequences reel/strategy extraction → checkpoint → bounded optimization loop → one-time holdout → background paper trading → concise report, per `docs/superpowers/specs/2026-07-07-unified-pipeline-orchestrator-design.md`.

**Architecture:** A new `PipelineRun` SQLAlchemy table persists stage state. A new `orchestrator/` package holds pure stage functions plus an `asyncio`-task runner (`run_pipeline(run_id)`) that advances the row through stages, reusing existing engine code (`reel_extractor`, `ir_validator`, `engine.validation`, `engine.stress`, `improvement_agent`, the paper-trading SSE generator) rather than reimplementing it. New FastAPI routes in `main.py` expose start/stream/checkpoint/retry endpoints. A background sweep `asyncio` task (started at app boot) handles checkpoint-timeout auto-proceed and restart recovery. Frontend gets a new `PipelinePage.tsx` that drives the whole flow via SSE, mirroring `StressPage.tsx`'s streaming state machine.

**Tech Stack:** FastAPI, SQLAlchemy (SQLite), Python asyncio, React 18 + Vite + TS, Server-Sent Events.

## Global Constraints

- Do not add `pandas-ta` or any TA lib importing `from numpy import NaN`.
- Do not set `reload=True` anywhere — `main.py` already runs with `reload=False`; do not change that.
- Do not hardcode `$` in any new frontend component — use the existing `currency` prop pattern.
- `win_rate` from `calculate_metrics` is already 0–100 — never multiply by 100 again.
- New DB columns on existing tables need the manual `PRAGMA`-based migration helper (Task 1) since SQLite `create_all` does not alter existing tables — do not assume a fresh `create_all` is sufficient.
- Loop round cap = 5, plateau threshold = 2% composite-score improvement, checkpoint timeout = 60–100s (implement as a random per-run value in that range, set once at checkpoint-open time), sweep cadence = 10s — exact values from the approved spec.
- One active run per user (`user_id` = the existing analytics identity's `user_email`, falling back to `session_id` if no email set) blocks only while status is in `running|awaiting_checkpoint|looping|holdout`.

---

### Task 1: `PipelineRun` model, column-migration helper, composite score function

**Files:**
- Modify: `backtester/models.py` (add `PipelineRun` class; add `source_url`, `source_platform`, `source_creator` columns to existing `StrategyOutcome` class)
- Modify: `backtester/database.py` (add `_ensure_columns()` migration helper, call it from `init_db()`)
- Modify: `backtester/engine/metrics.py` (add `score_backtest(metrics: dict) -> float`)
- Test: `backtester/test_pipeline_model.py` (new file)

**Interfaces:**
- Produces: `models.PipelineRun` (columns per spec's Data Model section), `models.StrategyOutcome.source_url/source_platform/source_creator` (nullable `String`), `database._ensure_columns()`, `engine.metrics.score_backtest(metrics: dict) -> float`.

- [ ] **Step 1: Write the failing test for `score_backtest`**

```python
# backtester/test_pipeline_model.py
from engine.metrics import score_backtest


def test_score_backtest_weights_and_bounds():
    good = {
        "sharpe_ratio": 3.0, "total_return_pct": 100.0,
        "sortino_ratio": 3.0, "calmar_ratio": 3.0, "max_drawdown_pct": 0.0,
    }
    bad = {
        "sharpe_ratio": -3.0, "total_return_pct": -50.0,
        "sortino_ratio": -3.0, "calmar_ratio": -3.0, "max_drawdown_pct": 50.0,
    }
    assert score_backtest(good) > score_backtest(bad)
    # Score is always in [0, 1] regardless of how extreme the inputs are.
    assert 0.0 <= score_backtest(good) <= 1.0
    assert 0.0 <= score_backtest(bad) <= 1.0


def test_score_backtest_missing_fields_default_to_zero_contribution():
    assert score_backtest({}) == 0.5  # every metric clamps to its midpoint when absent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backtester && python -m pytest test_pipeline_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_backtest'`

- [ ] **Step 3: Implement `score_backtest` in `engine/metrics.py`**

Append to the end of `backtester/engine/metrics.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backtester && python -m pytest test_pipeline_model.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add `PipelineRun` model and `StrategyOutcome` new columns**

In `backtester/models.py`, add these three columns inside the existing `StrategyOutcome` class, right after the `symbol` column (around line 191):

```python
    source_url      = Column(String(500))              # original reel/transcript URL, if any
    source_platform = Column(String(20))                # instagram | youtube | tiktok | manual
    source_creator  = Column(String(120))                # creator handle/name, for recommendation surface
```

Then append a new class at the end of `models.py`:

```python
class PipelineRun(Base):
    """Persisted state for one run of the unified extract→loop→holdout→report pipeline.

    Every stage transition writes to this row — that's what makes a run
    resumable across a backend restart and enforces "holdout touched once"
    (holdout only ever runs if holdout_result_json is still null).
    """
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_user", "user_id"),
        Index("ix_pipeline_status", "status"),
        Index("ix_pipeline_cache_key", "cache_key"),
    )

    id          = Column(String(36), primary_key=True)
    user_id     = Column(String(200), nullable=False)
    status      = Column(String(20), nullable=False, default="running")
    # running | awaiting_checkpoint | looping | holdout | paper_trading | complete | failed | interrupted
    stage       = Column(String(30), nullable=False, default="extracting")

    ir_json     = Column(Text)
    symbol      = Column(String(20))
    timeframe   = Column(String(10))
    source_url      = Column(String(500))
    source_platform = Column(String(20))
    source_creator  = Column(String(120))
    cache_key   = Column(String(64))

    loop_round             = Column(Integer, default=0)
    composite_scores_json  = Column(Text)     # list[{round, score, metrics}]

    checkpoint_opened_at    = Column(DateTime)
    checkpoint_timeout_secs = Column(Integer)   # random 60-100, fixed once at checkpoint-open

    holdout_result_json = Column(Text)
    report_json          = Column(Text)
    paper_trading_task_id = Column(String(36))
    error_message         = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Confirm `Index`, `Column`, `String`, `Text`, `Integer`, `DateTime`, `datetime` are already imported at the top of `models.py` (they are, per the existing `StrategyOutcome`/`Feedback` classes) — no new imports needed.

- [ ] **Step 6: Add the column-migration helper to `database.py`**

In `backtester/database.py`, add this function above `init_db()`:

```python
def _ensure_columns():
    """
    SQLite's create_all() only creates NEW tables — it never alters existing
    ones. When we add columns to an already-deployed table (StrategyOutcome
    gaining source_url/source_platform/source_creator), we have to add them
    by hand or the Railway volume's existing DB file will 500 on first write.
    """
    from sqlalchemy import text
    additions = {
        "strategy_outcomes": [
            ("source_url", "VARCHAR(500)"),
            ("source_platform", "VARCHAR(20)"),
            ("source_creator", "VARCHAR(120)"),
        ],
    }
    with engine.connect() as conn:
        for table, cols in additions.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col_name, col_type in cols:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    logger.info("Migrated: added %s.%s", table, col_name)
        conn.commit()
```

Then update `init_db()` to call it:

```python
def init_db():
    """Create all tables if they don't already exist."""
    import models  # noqa: F401 – ensure models are registered with Base
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    logger.info("✅ Database tables created / verified")
```

- [ ] **Step 7: Write a test that the model + migration actually work**

Append to `backtester/test_pipeline_model.py`:

```python
import uuid
from database import SessionLocal, init_db
import models


def test_pipeline_run_roundtrip():
    init_db()
    db = SessionLocal()
    try:
        run_id = str(uuid.uuid4())
        row = models.PipelineRun(id=run_id, user_id="test@example.com", status="running", stage="extracting")
        db.add(row)
        db.commit()
        fetched = db.query(models.PipelineRun).filter_by(id=run_id).first()
        assert fetched is not None
        assert fetched.status == "running"
        assert fetched.loop_round == 0 or fetched.loop_round is None
    finally:
        db.query(models.PipelineRun).filter_by(id=run_id).delete()
        db.commit()
        db.close()


def test_strategy_outcome_has_source_columns():
    init_db()
    db = SessionLocal()
    try:
        row = models.StrategyOutcome(
            strategy="DCA", symbol="BTC/USDT",
            source_url="https://instagram.com/reel/abc", source_platform="instagram",
            source_creator="some_trader",
        )
        db.add(row)
        db.commit()
        assert row.id is not None
    finally:
        db.query(models.StrategyOutcome).filter_by(id=row.id).delete()
        db.commit()
        db.close()
```

- [ ] **Step 8: Run all tests in the file to verify they pass**

Run: `cd backtester && python -m pytest test_pipeline_model.py -v`
Expected: PASS (4 tests). Delete any stray `backtester.db` test artifacts are not needed — these tests clean up their own rows.

- [ ] **Step 9: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/models.py backtester/database.py backtester/engine/metrics.py backtester/test_pipeline_model.py
git commit -m "feat(pipeline): add PipelineRun model, column migration helper, composite score fn"
```

---

### Task 2: Public alias for single-backtest reuse in `engine/validation.py`

**Files:**
- Modify: `backtester/engine/validation.py` (add one alias line)
- Test: `backtester/test_pipeline_model.py` (append)

**Interfaces:**
- Consumes: `engine.validation._segment_metrics(df, strategy_cls, strategy_params, sim_kwargs, capital) -> dict | None` (already exists).
- Produces: `engine.validation.run_segment_backtest` — same callable, public name, for the orchestrator to import without reaching into a private helper.

- [ ] **Step 1: Write the failing test**

```python
# append to backtester/test_pipeline_model.py
def test_run_segment_backtest_alias_exists():
    from engine.validation import run_segment_backtest, _segment_metrics
    assert run_segment_backtest is _segment_metrics
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backtester && python -m pytest test_pipeline_model.py::test_run_segment_backtest_alias_exists -v`
Expected: FAIL with `ImportError: cannot import name 'run_segment_backtest'`

- [ ] **Step 3: Add the alias**

At the end of `backtester/engine/validation.py`, add:

```python
# Public alias — orchestrator/pipeline.py runs single backtests (loop rounds,
# retry-symbol) through this rather than reaching into the "private" helper
# directly. Mirrors the existing `run_single_backtest = _single_backtest`
# alias pattern in engine/stress.py.
run_segment_backtest = _segment_metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backtester && python -m pytest test_pipeline_model.py::test_run_segment_backtest_alias_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/engine/validation.py backtester/test_pipeline_model.py
git commit -m "feat(pipeline): expose run_segment_backtest as public alias for orchestrator reuse"
```

---

### Task 3: Strategy cache lookup (`orchestrator/cache.py`)

**Files:**
- Create: `backtester/orchestrator/__init__.py` (empty)
- Create: `backtester/orchestrator/cache.py`
- Test: `backtester/orchestrator/test_cache.py`

**Interfaces:**
- Consumes: `models.StrategyOutcome`, `database.SessionLocal`.
- Produces: `orchestrator.cache.compute_cache_key(ir: dict, symbol: str, timeframe: str) -> str`, `orchestrator.cache.find_cached_outcome(db: Session, cache_key: str) -> models.StrategyOutcome | None`. Later tasks (Task 4) call these two functions only.

- [ ] **Step 1: Write the failing tests**

```python
# backtester/orchestrator/test_cache.py
from orchestrator.cache import compute_cache_key, find_cached_outcome
from database import SessionLocal, init_db
import models


def test_cache_key_is_stable_regardless_of_param_order():
    ir_a = {"strategy": "DCA", "params": {"a": 1, "b": 2}}
    ir_b = {"strategy": "DCA", "params": {"b": 2, "a": 1}}
    assert compute_cache_key(ir_a, "BTC/USDT", "1d") == compute_cache_key(ir_b, "BTC/USDT", "1d")


def test_cache_key_differs_on_symbol_or_timeframe():
    ir = {"strategy": "DCA", "params": {"a": 1}}
    k1 = compute_cache_key(ir, "BTC/USDT", "1d")
    k2 = compute_cache_key(ir, "ETH/USDT", "1d")
    k3 = compute_cache_key(ir, "BTC/USDT", "4h")
    assert len({k1, k2, k3}) == 3


def test_find_cached_outcome_hit_and_miss():
    init_db()
    db = SessionLocal()
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24}}
    key = compute_cache_key(ir, "BTC/USDT", "1d")
    try:
        assert find_cached_outcome(db, key) is None  # miss before insert

        row = models.StrategyOutcome(
            strategy="DCA", symbol="BTC/USDT", params='{"buy_interval_hours": 24}',
        )
        # cache_key isn't a StrategyOutcome column — the lookup matches on
        # strategy+symbol+params directly, so build the row the same way.
        db.add(row)
        db.commit()

        hit = find_cached_outcome(db, key)
        assert hit is not None
        assert hit.strategy == "DCA"
    finally:
        db.query(models.StrategyOutcome).filter_by(strategy="DCA", symbol="BTC/USDT").delete()
        db.commit()
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backtester && python -m pytest orchestrator/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator'`

- [ ] **Step 3: Create the package and implement**

`backtester/orchestrator/__init__.py`:

```python
```

(empty file — just marks the package)

`backtester/orchestrator/cache.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backtester && python -m pytest orchestrator/test_cache.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/orchestrator/__init__.py backtester/orchestrator/cache.py backtester/orchestrator/test_cache.py
git commit -m "feat(pipeline): add strategy cache lookup for dedup against StrategyOutcome"
```

---

### Task 4: Stage functions (`orchestrator/stages.py`)

**Files:**
- Create: `backtester/orchestrator/stages.py`
- Test: `backtester/orchestrator/test_stages.py`

**Interfaces:**
- Consumes: `reel_extractor.extract_strategy_ir(transcript, caption) -> dict`, `ir_validator.validate_ir(ir) -> list[str]`, `ir_validator.normalize_ir(ir) -> dict`, `improvement_agent.critique_and_improve(ir, metrics, gaps, symbol, interval) -> dict`, `improvement_agent.judge_pipeline(trace) -> dict`, `engine.validation.run_segment_backtest`, `engine.validation.run_holdout`, `engine.validation.run_walk_forward`, `engine.metrics.score_backtest`, `engine.stress.run_stress_backtest`, `engine.stress.SCENARIO_PRESETS`, `strategies.STRATEGY_REGISTRY`, `data.fetcher.DataFetcher`, `data.validator.DataValidator`.
- Produces (all pure functions, no DB access — Task 5's `pipeline.py` does the DB read/write around each call): `fetch_and_validate_data(symbol, source, interval, start_date, end_date) -> pd.DataFrame`, `extract_ir(transcript, caption, tweak) -> dict`, `validate_and_normalize(ir) -> tuple[dict, list[str]]`, `patch_ir_with_tweak(ir, tweak, symbol, interval) -> dict`, `run_loop_round(df, ir, capital, sim_kwargs, symbol, interval) -> dict` (returns `{metrics, score, next_ir_or_none}`), `run_holdout_check(df, ir, capital, sim_kwargs) -> dict`, `build_report(run) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# backtester/orchestrator/test_stages.py
import pandas as pd
from orchestrator.stages import validate_and_normalize, run_loop_round, build_report


def test_validate_and_normalize_passthrough_valid_ir():
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}
    normalized, errors = validate_and_normalize(ir)
    assert errors == []
    assert normalized["strategy"] == "DCA"


def test_validate_and_normalize_reports_unknown_strategy():
    ir = {"strategy": "NOT_A_STRATEGY", "params": {}}
    normalized, errors = validate_and_normalize(ir)
    assert len(errors) > 0


def _synthetic_df(n=300):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    price = 100 + (pd.Series(range(n)) * 0.1).values
    return pd.DataFrame({
        "timestamp": dates, "open": price, "high": price * 1.01,
        "low": price * 0.99, "close": price, "volume": 1000.0,
    })


def test_run_loop_round_returns_score_and_metrics():
    df = _synthetic_df()
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}
    sim_kwargs = {"symbol": "BTC/USDT", "capital": 10000}
    result = run_loop_round(df, ir, capital=10000, sim_kwargs=sim_kwargs, symbol="BTC/USDT", interval="1d")
    assert "metrics" in result
    assert "score" in result
    assert 0.0 <= result["score"] <= 1.0


def test_build_report_is_concise_and_has_chip_metadata():
    fake_run = {
        "symbol": "BTC/USDT",
        "composite_scores_json": '[{"round": 1, "score": 0.62, "metrics": {"sharpe_ratio": 1.2}}]',
        "holdout_result_json": '{"verdict": "stable", "in_sample": {}, "out_of_sample": {}}',
        "report_json": None,
    }
    report = build_report(fake_run)
    assert "verdict" in report
    assert "chips" in report
    chip_ids = {c["id"] for c in report["chips"]}
    assert {"stress_detail", "walk_forward", "composite_math", "paper_trading", "retry_symbol"} <= chip_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backtester && python -m pytest orchestrator/test_stages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.stages'`

- [ ] **Step 3: Implement `orchestrator/stages.py`**

```python
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

from data.fetcher import DataFetcher
from data.validator import DataValidator
from engine.metrics import score_backtest
from engine.validation import run_segment_backtest, run_holdout, run_walk_forward
from ir_validator import validate_ir, normalize_ir
from strategies import STRATEGY_REGISTRY

logger = logging.getLogger(__name__)

_fetcher = DataFetcher()
_validator = DataValidator()


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
    last_score = scores[-1]["score"] if scores else None
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backtester && python -m pytest orchestrator/test_stages.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/orchestrator/stages.py backtester/orchestrator/test_stages.py
git commit -m "feat(pipeline): add pure stage functions for extract/validate/patch/loop/holdout/report"
```

---

### Task 5: The orchestrator task runner (`orchestrator/pipeline.py`)

**Files:**
- Create: `backtester/orchestrator/pipeline.py`
- Test: `backtester/orchestrator/test_pipeline_runner.py`

**Interfaces:**
- Consumes: everything from Task 3 (`cache.py`) and Task 4 (`stages.py`); `models.PipelineRun`, `database.SessionLocal`; `engine.stress.run_stress_backtest`, `SCENARIO_PRESETS`; `improvement_agent.critique_and_improve`, `judge_pipeline`; `strategies.STRATEGY_REGISTRY`.
- Produces: `orchestrator.pipeline.start_run(user_id, transcript, caption, symbol, source, interval, start_date, end_date, capital, tweak=None) -> str` (returns `run_id`, creates the row, launches the asyncio task), `orchestrator.pipeline.submit_checkpoint_response(run_id, action, tweak_text=None) -> None`, `orchestrator.pipeline.retry_with_new_symbol(run_id, new_symbol) -> str` (returns new `run_id`), `orchestrator.pipeline.sweep_once() -> None` (checks checkpoint timeouts + interrupted rows; called both by a background loop and directly by tests), `orchestrator.pipeline.LOOP_ROUND_CAP = 5`, `orchestrator.pipeline.PLATEAU_THRESHOLD = 0.02`.

- [ ] **Step 1: Write the failing tests**

```python
# backtester/orchestrator/test_pipeline_runner.py
import asyncio
import json
import time
import uuid

import pytest

from database import SessionLocal, init_db
import models
from orchestrator import pipeline


def _cleanup(run_id: str):
    db = SessionLocal()
    db.query(models.PipelineRun).filter_by(id=run_id).delete()
    db.commit()
    db.close()


def test_one_active_run_per_user_blocks_second_start():
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(id=run_id, user_id="dup@example.com", status="looping", stage="loop_round_1"))
    db.commit()
    db.close()
    try:
        with pytest.raises(pipeline.ActiveRunExistsError):
            pipeline.assert_no_active_run("dup@example.com")
    finally:
        _cleanup(run_id)


def test_assert_no_active_run_allows_when_only_complete_runs_exist():
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(id=run_id, user_id="ok@example.com", status="paper_trading", stage="done"))
    db.commit()
    db.close()
    try:
        pipeline.assert_no_active_run("ok@example.com")  # should not raise
    finally:
        _cleanup(run_id)


def test_sweep_once_auto_proceeds_expired_checkpoint():
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    past = pipeline._utcnow_minus_seconds(999)
    db.add(models.PipelineRun(
        id=run_id, user_id="x@example.com", status="awaiting_checkpoint", stage="checkpoint",
        ir_json=json.dumps({"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}),
        symbol="BTC/USDT", timeframe="1d",
        checkpoint_opened_at=past, checkpoint_timeout_secs=60,
    ))
    db.commit()
    db.close()
    try:
        pipeline.sweep_once()
        db = SessionLocal()
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        assert row.status != "awaiting_checkpoint"
        db.close()
    finally:
        _cleanup(run_id)


def test_sweep_once_marks_orphaned_running_rows_interrupted():
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(id=run_id, user_id="y@example.com", status="looping", stage="loop_round_1"))
    db.commit()
    db.close()
    try:
        pipeline.sweep_once()  # no live task registered for this run_id -> interrupted
        db = SessionLocal()
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        assert row.status == "interrupted"
        db.close()
    finally:
        _cleanup(run_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backtester && python -m pytest orchestrator/test_pipeline_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator.pipeline'`

- [ ] **Step 3: Implement `orchestrator/pipeline.py`**

```python
"""
The orchestrator: sequences PipelineRun rows through their stages, launches
one asyncio task per run, and runs a background sweep for checkpoint
timeouts + restart recovery. This module owns all reads/writes to the
PipelineRun row; orchestrator/stages.py holds the pure work functions it
calls in between.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

import models
from database import SessionLocal
from engine.metrics import score_backtest
from engine.validation import run_walk_forward
from engine.stress import run_stress_backtest, SCENARIO_PRESETS
from improvement_agent import critique_and_improve, judge_pipeline
from strategies import STRATEGY_REGISTRY
from orchestrator.cache import compute_cache_key, find_cached_outcome
from orchestrator.stages import (
    fetch_and_validate_data, extract_ir, validate_and_normalize,
    patch_ir_with_tweak, run_loop_round, run_holdout_check, build_report,
)

logger = logging.getLogger(__name__)

LOOP_ROUND_CAP = 5
PLATEAU_THRESHOLD = 0.02
SWEEP_INTERVAL_SECS = 10
CHECKPOINT_TIMEOUT_RANGE = (60, 100)

_ACTIVE_STATUSES = ("running", "awaiting_checkpoint", "looping", "holdout")

# run_id -> asyncio.Task, so the sweep can tell "genuinely still running" from
# "row says running but the process restarted and the task is gone."
_live_tasks: dict[str, "asyncio.Task"] = {}


class ActiveRunExistsError(Exception):
    def __init__(self, run_id: str):
        super().__init__(f"User already has an active run: {run_id}")
        self.run_id = run_id


def _utcnow_minus_seconds(secs: int) -> datetime:
    return datetime.utcnow() - timedelta(seconds=secs)


def assert_no_active_run(user_id: str) -> None:
    db = SessionLocal()
    try:
        existing = (
            db.query(models.PipelineRun)
            .filter(models.PipelineRun.user_id == user_id, models.PipelineRun.status.in_(_ACTIVE_STATUSES))
            .first()
        )
        if existing:
            raise ActiveRunExistsError(existing.id)
    finally:
        db.close()


def _save(db: Session, row: models.PipelineRun, **fields) -> None:
    for k, v in fields.items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()


def start_run(
    user_id: str, transcript: str, caption: str, symbol: str, source: str, interval: str,
    start_date: date, end_date: date, capital: float, tweak: Optional[str] = None,
) -> str:
    assert_no_active_run(user_id)
    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        row = models.PipelineRun(
            id=run_id, user_id=user_id, status="running", stage="extracting",
            symbol=symbol, timeframe=interval,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    task = asyncio.create_task(_run_pipeline(run_id, transcript, caption, source, start_date, end_date, capital, tweak))
    _live_tasks[run_id] = task
    return run_id


async def _run_pipeline(
    run_id: str, transcript: str, caption: str, source: str,
    start_date: date, end_date: date, capital: float, tweak: Optional[str],
) -> None:
    db = SessionLocal()
    try:
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()

        # ── Extract ──
        extraction = await asyncio.to_thread(extract_ir, transcript, caption, tweak)
        ir = extraction.get("strategy_ir")
        if not ir:
            _save(db, row, status="failed", stage="extracting", error_message=extraction.get("error", "extraction failed"))
            return

        # ── Cache lookup ──
        cache_key = compute_cache_key(ir, row.symbol, row.timeframe)
        cached = find_cached_outcome(db, cache_key)
        if cached:
            report = {
                "verdict": f"Served from cache — this exact strategy was already tested on {row.symbol}.",
                "last_score": None, "chips": [],
            }
            _save(db, row, status="complete", stage="done", cache_key=cache_key,
                  ir_json=json.dumps(ir), report_json=json.dumps(report))
            return

        # ── Validate IR ──
        normalized, errors = validate_and_normalize(ir)
        if errors:
            _save(db, row, status="failed", stage="validating_ir", error_message="; ".join(errors))
            return
        _save(db, row, ir_json=json.dumps(normalized), cache_key=cache_key, stage="checkpoint",
              status="awaiting_checkpoint",
              checkpoint_opened_at=datetime.utcnow(),
              checkpoint_timeout_secs=random.randint(*CHECKPOINT_TIMEOUT_RANGE))
        # Task ends here — resumed either by submit_checkpoint_response() or
        # by the sweep's timeout auto-proceed, both of which call _continue_after_checkpoint.
    finally:
        db.close()


def submit_checkpoint_response(run_id: str, action: str, tweak_text: Optional[str] = None) -> None:
    task = asyncio.create_task(_continue_after_checkpoint(run_id, action, tweak_text))
    _live_tasks[run_id] = task


async def _continue_after_checkpoint(run_id: str, action: str, tweak_text: Optional[str]) -> None:
    db = SessionLocal()
    try:
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        if row is None or row.status != "awaiting_checkpoint":
            return
        ir = json.loads(row.ir_json)

        if action == "tweak" and tweak_text:
            ir = await asyncio.to_thread(patch_ir_with_tweak, ir, tweak_text, row.symbol, row.timeframe)
            normalized, errors = validate_and_normalize(ir)
            if errors:
                _save(db, row, status="failed", stage="patching_ir", error_message="; ".join(errors))
                return
            ir = normalized

        _save(db, row, ir_json=json.dumps(ir), status="looping", stage="loop_round_1",
              checkpoint_opened_at=None, loop_round=0, composite_scores_json=json.dumps([]))
    finally:
        db.close()

    await _run_loop_and_beyond(run_id)


async def _run_loop_and_beyond(run_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        ir = json.loads(row.ir_json)
        df = await asyncio.to_thread(
            fetch_and_validate_data, row.symbol, "binance", row.timeframe,
            date.today() - __import__("datetime").timedelta(days=730), date.today(),
        )
        sim_kwargs = {"symbol": row.symbol}
        capital = 10_000.0
        scores: list[dict] = json.loads(row.composite_scores_json or "[]")

        for round_num in range(1, LOOP_ROUND_CAP + 1):
            _save(db, row, loop_round=round_num, stage=f"loop_round_{round_num}")
            round_result = await asyncio.to_thread(run_loop_round, df, ir, capital, sim_kwargs, row.symbol, row.timeframe)
            score = round_result["score"]
            scores.append({"round": round_num, "score": score, "metrics": round_result["metrics"]})
            _save(db, row, composite_scores_json=json.dumps(scores))

            if round_num >= 2 and (score - scores[-2]["score"]) < PLATEAU_THRESHOLD:
                break
            if round_num == LOOP_ROUND_CAP:
                break

            critique = await asyncio.to_thread(
                critique_and_improve, ir, round_result["metrics"], [], row.symbol, row.timeframe,
            )
            improved = critique.get("improved_ir")
            if not improved:
                break
            normalized, errors = validate_and_normalize(improved)
            if errors:
                break
            ir = normalized
            _save(db, row, ir_json=json.dumps(ir))

        # ── Holdout (touched exactly once) ──
        _save(db, row, status="holdout", stage="holdout")
        holdout = await asyncio.to_thread(run_holdout_check, df, ir, capital, sim_kwargs)
        _save(db, row, holdout_result_json=json.dumps(holdout))

        # ── Kick off paper trading in the background (never blocks the report) ──
        paper_task_id = str(uuid.uuid4())
        _save(db, row, paper_trading_task_id=paper_task_id, status="paper_trading", stage="paper_trading")
        asyncio.create_task(_run_paper_trading(run_id, paper_task_id, ir, row.symbol, row.timeframe, capital))

        # ── Report ──
        report = build_report({
            "symbol": row.symbol,
            "composite_scores_json": row.composite_scores_json,
            "holdout_result_json": row.holdout_result_json,
            "report_json": None,
        })
        _save(db, row, report_json=json.dumps(report), status="complete", stage="done")
    except Exception as e:
        logger.exception("Pipeline run %s failed", run_id)
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        if row:
            _save(db, row, status="failed", error_message=str(e))
    finally:
        db.close()
        _live_tasks.pop(run_id, None)


async def _run_paper_trading(run_id: str, task_id: str, ir: dict, symbol: str, timeframe: str, capital: float) -> None:
    """
    Drains the existing paper-trading SSE generator in-process (no HTTP hop)
    and writes the final metrics into this run's report_json under the
    "paper_trading" chip once it completes. Never flips the parent row's
    status away from "complete".
    """
    from main import PaperRequest, stream_paper_trade  # local import avoids a circular import at module load

    req = PaperRequest(
        symbol=symbol, interval=timeframe, start_date=date.today() - __import__("datetime").timedelta(days=365),
        end_date=date.today(), capital=capital, strategy=ir["strategy"], params=ir.get("params", {}),
        horizon_days=90, reveal_ms=50,
    )
    try:
        response = await stream_paper_trade(req)
        final_metrics = None
        async for chunk in response.body_iterator:
            text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
            for line in text.splitlines():
                if line.startswith("data: "):
                    event = json.loads(line[len("data: "):])
                    if event.get("type") == "complete":
                        final_metrics = event.get("metrics")
        db = SessionLocal()
        try:
            row = db.query(models.PipelineRun).filter_by(id=run_id).first()
            if row and row.report_json:
                report = json.loads(row.report_json)
                report["paper_trading_result"] = final_metrics
                for chip in report.get("chips", []):
                    if chip["id"] == "paper_trading":
                        chip["kind"] = "instant"
                _save(db, row, report_json=json.dumps(report))
        finally:
            db.close()
    except Exception:
        logger.exception("Background paper trading failed for run %s", run_id)


def retry_with_new_symbol(run_id: str, new_symbol: str) -> str:
    """'Try this on another symbol' — new PipelineRun row, same IR, fresh
    holdout, starts straight at the loop stage (skips extract/validate/checkpoint)."""
    db = SessionLocal()
    try:
        old = db.query(models.PipelineRun).filter_by(id=run_id).first()
        if old is None or old.status != "complete":
            raise ValueError("Original run not found or not complete")
        new_id = str(uuid.uuid4())
        new_row = models.PipelineRun(
            id=new_id, user_id=old.user_id, status="looping", stage="loop_round_1",
            ir_json=old.ir_json, symbol=new_symbol, timeframe=old.timeframe,
            loop_round=0, composite_scores_json=json.dumps([]),
        )
        db.add(new_row)
        db.commit()
    finally:
        db.close()
    task = asyncio.create_task(_run_loop_and_beyond(new_id))
    _live_tasks[new_id] = task
    return new_id


def sweep_once() -> None:
    """
    Called every SWEEP_INTERVAL_SECS by a background loop (see main.py's
    startup handler). Two jobs:
      1. Checkpoint rows whose timeout has elapsed with no user response
         auto-proceed (as if the user confirmed with no tweak).
      2. Non-terminal rows with no live asyncio task (e.g. after a backend
         restart) get marked "interrupted" for the frontend to offer resume.
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        expired = (
            db.query(models.PipelineRun)
            .filter(models.PipelineRun.status == "awaiting_checkpoint")
            .all()
        )
        for row in expired:
            if row.checkpoint_opened_at is None or row.checkpoint_timeout_secs is None:
                continue
            elapsed = (now - row.checkpoint_opened_at).total_seconds()
            if elapsed >= row.checkpoint_timeout_secs:
                submit_checkpoint_response(row.id, action="confirm")

        orphaned = (
            db.query(models.PipelineRun)
            .filter(models.PipelineRun.status.in_(_ACTIVE_STATUSES))
            .all()
        )
        for row in orphaned:
            task = _live_tasks.get(row.id)
            if task is None or task.done():
                _save(db, row, status="interrupted")
    finally:
        db.close()


async def sweep_loop() -> None:
    while True:
        try:
            sweep_once()
        except Exception:
            logger.exception("Pipeline sweep failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECS)


def resume_run(run_id: str) -> None:
    """User clicked 'resume' on an interrupted run. Restarts the asyncio
    task for whatever stage the row is currently on."""
    db = SessionLocal()
    try:
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        if row is None:
            raise ValueError("Run not found")
        if row.stage == "checkpoint":
            _save(db, row, status="awaiting_checkpoint")
            return
        _save(db, row, status="looping")
    finally:
        db.close()
    task = asyncio.create_task(_run_loop_and_beyond(run_id))
    _live_tasks[run_id] = task
```

Note on the `test_sweep_once_auto_proceeds_expired_checkpoint` test: `submit_checkpoint_response` creates an `asyncio.create_task`, which requires a running event loop. Since `pytest` runs sync tests without one, mark that test (and any other test that calls into `sweep_once`/`submit_checkpoint_response`) with `pytest.mark.asyncio` and run it inside an event loop, OR — simpler for this plan — call `sweep_once()` from inside a tiny `asyncio.run(...)` wrapper in the test. Update the test file:

```python
# revise the two tests that trigger asyncio.create_task inside sweep_once
def test_sweep_once_auto_proceeds_expired_checkpoint():
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    past = pipeline._utcnow_minus_seconds(999)
    db.add(models.PipelineRun(
        id=run_id, user_id="x@example.com", status="awaiting_checkpoint", stage="checkpoint",
        ir_json=json.dumps({"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}),
        symbol="BTC/USDT", timeframe="1d",
        checkpoint_opened_at=past, checkpoint_timeout_secs=60,
    ))
    db.commit()
    db.close()

    async def _run():
        pipeline.sweep_once()
        await asyncio.sleep(0.2)  # let the created task's first DB write land

    try:
        asyncio.run(_run())
        db = SessionLocal()
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        assert row.status != "awaiting_checkpoint"
        db.close()
    finally:
        _cleanup(run_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backtester && python -m pytest orchestrator/test_pipeline_runner.py -v`
Expected: PASS (4 tests). If `test_sweep_once_auto_proceeds_expired_checkpoint` is flaky on the `sleep(0.2)`, bump to `0.5` — it's only waiting on a DB write, not a real LLM call, but `_continue_after_checkpoint` for this test's DCA IR will actually attempt a full loop run; that's acceptable for this test's purposes (it only asserts status left `awaiting_checkpoint`) but will be slow. Prefer this alternative: assert only on the immediate transition by checking status is no longer `awaiting_checkpoint` — do not wait for full loop completion.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/orchestrator/pipeline.py backtester/orchestrator/test_pipeline_runner.py
git commit -m "feat(pipeline): add orchestrator task runner with checkpoint timer and restart recovery"
```

---

### Task 6: API routes in `main.py`

**Files:**
- Modify: `backtester/main.py` (add Pydantic request models + 5 routes + startup sweep registration)
- Test: `backtester/test_pipeline_api.py`

**Interfaces:**
- Consumes: `orchestrator.pipeline.start_run`, `submit_checkpoint_response`, `retry_with_new_symbol`, `resume_run`, `sweep_loop`, `ActiveRunExistsError`.
- Produces: `POST /api/pipeline/start`, `GET /api/pipeline/{run_id}`, `POST /api/pipeline/{run_id}/checkpoint`, `POST /api/pipeline/{run_id}/retry-symbol`, `POST /api/pipeline/{run_id}/resume`.

- [ ] **Step 1: Write the failing test**

```python
# backtester/test_pipeline_api.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_pipeline_start_requires_input():
    resp = client.post("/api/pipeline/start", json={"user_id": "t@example.com"})
    assert resp.status_code == 400


def test_pipeline_start_returns_run_id_and_blocks_second_active_run():
    resp = client.post("/api/pipeline/start", json={
        "user_id": "dup2@example.com",
        "transcript": "Buy BTC every day and hold for a week.",
    })
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert run_id

    resp2 = client.post("/api/pipeline/start", json={
        "user_id": "dup2@example.com",
        "transcript": "Something else entirely.",
    })
    assert resp2.status_code == 409

    # cleanup
    from database import SessionLocal
    import models
    db = SessionLocal()
    db.query(models.PipelineRun).filter_by(id=run_id).delete()
    db.commit()
    db.close()


def test_get_pipeline_run_not_found_returns_404():
    resp = client.get("/api/pipeline/does-not-exist")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backtester && python -m pytest test_pipeline_api.py -v`
Expected: FAIL with 404 (route doesn't exist yet) on all three.

- [ ] **Step 3: Add Pydantic models and routes to `main.py`**

Add these imports near the other local imports at the top of `main.py` (after `from strategies import STRATEGY_REGISTRY` around line 61):

```python
from orchestrator import pipeline as pipeline_orchestrator
```

Add these Pydantic models near the other request models (after `ReelAnalyzeRequest`, around line 1230):

```python
class PipelineStartRequest(BaseModel):
    user_id:    str = Field(..., description="Analytics identity email, or session_id fallback")
    url:        Optional[str] = None
    transcript: Optional[str] = None
    caption:    Optional[str] = None
    tweak:      Optional[str] = Field(None, description="Optional free-text modification submitted alongside the input")
    symbol:     str = Field("BTC/USDT")
    source:     str = Field("binance")
    interval:   str = Field("1d")
    start_date: date = Field(default_factory=lambda: date.today() - __import__("datetime").timedelta(days=730))
    end_date:   date = Field(default_factory=date.today)
    capital:    float = Field(10_000.0)


class PipelineCheckpointRequest(BaseModel):
    action: str = Field(..., description="'confirm' or 'tweak'")
    tweak_text: Optional[str] = None


class PipelineRetrySymbolRequest(BaseModel):
    symbol: str
```

Add the routes at the end of the file's route section (right before the `# Analytics & Feedback` section around line 2752), tagged `["Pipeline"]`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# ── Unified Pipeline
# ─────────────────────────────────────────────────────────────────────────────

@app.post(f"{API_PREFIX}/pipeline/start", tags=["Pipeline"])
async def pipeline_start(req: PipelineStartRequest):
    transcript = (req.transcript or "").strip()
    if not transcript and not req.url:
        raise HTTPException(400, "Provide either 'transcript' or 'url'")
    if not transcript and req.url:
        from config import INGESTION_API_URL
        if INGESTION_API_URL:
            import httpx
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{INGESTION_API_URL.rstrip('/')}/extract", json={"url": req.url})
                resp.raise_for_status()
                data = resp.json()
                transcript = data.get("transcript", "") or data.get("original_source_text", "")
        else:
            raise HTTPException(400, "No INGESTION_API_URL configured — provide 'transcript' directly instead")

    try:
        run_id = pipeline_orchestrator.start_run(
            user_id=req.user_id, transcript=transcript, caption=req.caption or "",
            symbol=req.symbol, source=req.source, interval=req.interval,
            start_date=req.start_date, end_date=req.end_date, capital=req.capital, tweak=req.tweak,
        )
    except pipeline_orchestrator.ActiveRunExistsError as e:
        raise HTTPException(409, f"You already have an active pipeline run: {e.run_id}")
    return {"run_id": run_id}


@app.get(f"{API_PREFIX}/pipeline/{{run_id}}", tags=["Pipeline"])
def pipeline_get(run_id: str, db: Session = Depends(get_db)):
    row = db.query(models.PipelineRun).filter_by(id=run_id).first()
    if row is None:
        raise HTTPException(404, "Run not found")
    return {
        "id": row.id, "status": row.status, "stage": row.stage,
        "loop_round": row.loop_round, "symbol": row.symbol,
        "composite_scores": json.loads(row.composite_scores_json) if row.composite_scores_json else [],
        "holdout_result": json.loads(row.holdout_result_json) if row.holdout_result_json else None,
        "report": json.loads(row.report_json) if row.report_json else None,
        "error_message": row.error_message,
        "ir": json.loads(row.ir_json) if row.ir_json else None,
    }


@app.post(f"{API_PREFIX}/pipeline/{{run_id}}/checkpoint", tags=["Pipeline"])
def pipeline_checkpoint(run_id: str, req: PipelineCheckpointRequest, db: Session = Depends(get_db)):
    row = db.query(models.PipelineRun).filter_by(id=run_id).first()
    if row is None:
        raise HTTPException(404, "Run not found")
    if row.status != "awaiting_checkpoint":
        raise HTTPException(400, f"Run is not awaiting a checkpoint (status={row.status})")
    pipeline_orchestrator.submit_checkpoint_response(run_id, req.action, req.tweak_text)
    return {"ok": True}


@app.post(f"{API_PREFIX}/pipeline/{{run_id}}/retry-symbol", tags=["Pipeline"])
def pipeline_retry_symbol(run_id: str, req: PipelineRetrySymbolRequest):
    try:
        new_run_id = pipeline_orchestrator.retry_with_new_symbol(run_id, req.symbol)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"run_id": new_run_id}


@app.post(f"{API_PREFIX}/pipeline/{{run_id}}/resume", tags=["Pipeline"])
def pipeline_resume(run_id: str, db: Session = Depends(get_db)):
    row = db.query(models.PipelineRun).filter_by(id=run_id).first()
    if row is None:
        raise HTTPException(404, "Run not found")
    if row.status != "interrupted":
        raise HTTPException(400, f"Run is not interrupted (status={row.status})")
    pipeline_orchestrator.resume_run(run_id)
    return {"ok": True}
```

Update `on_startup` to launch the sweep loop (replace the existing function around line 199):

```python
@app.on_event("startup")
async def on_startup():
    init_db()
    from orchestrator.pipeline import sweep_loop
    asyncio.create_task(sweep_loop())
    logger.info("🚀 TradeVed Backtester API started")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backtester && python -m pytest test_pipeline_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full existing suite to check for regressions**

Run: `cd backtester && python -m pytest test_all.py test_pipeline_model.py orchestrator/ test_pipeline_api.py -v`
Expected: all PASS. If `test_all.py` fails on anything unrelated to this change, stop and investigate before continuing — do not proceed with a broken baseline.

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/main.py backtester/test_pipeline_api.py
git commit -m "feat(pipeline): add /api/pipeline/* routes and startup sweep registration"
```

---

### Task 7: Frontend — types, api client, PipelinePage

**Files:**
- Modify: `backtester/frontend/src/types.ts` (add pipeline types)
- Modify: `backtester/frontend/src/api.ts` (add pipeline API functions)
- Create: `backtester/frontend/src/components/PipelinePage.tsx`
- Modify: `backtester/frontend/src/App.tsx` (add `'pipeline'` page + nav pill)

**Interfaces:**
- Consumes: `POST /api/pipeline/start`, `GET /api/pipeline/{id}`, `POST /api/pipeline/{id}/checkpoint`, `POST /api/pipeline/{id}/retry-symbol`, `POST /api/pipeline/{id}/resume` (Task 6).
- Produces: `PipelineRunState` type, `startPipeline()`, `getPipelineRun()`, `submitPipelineCheckpoint()`, `retryPipelineSymbol()`, `resumePipelineRun()` in `api.ts`; `<PipelinePage />` component.

- [ ] **Step 1: Add types to `types.ts`**

Append to `backtester/frontend/src/types.ts`:

```typescript
export type PipelineStatus =
  | "running" | "awaiting_checkpoint" | "looping" | "holdout"
  | "paper_trading" | "complete" | "failed" | "interrupted";

export interface PipelineChip {
  id: string;
  label: string;
  kind: "instant" | "live";
}

export interface PipelineReport {
  verdict: string;
  last_score: number | null;
  chips: PipelineChip[];
  paper_trading_result?: Record<string, unknown>;
}

export interface PipelineRunState {
  id: string;
  status: PipelineStatus;
  stage: string;
  loop_round: number | null;
  symbol: string;
  composite_scores: Array<{ round: number; score: number; metrics: Record<string, unknown> }>;
  holdout_result: { verdict: string; in_sample: unknown; out_of_sample: unknown } | null;
  report: PipelineReport | null;
  error_message: string | null;
  ir: { strategy: string; params: Record<string, unknown> } | null;
}
```

- [ ] **Step 2: Add API functions to `api.ts`**

Append to `backtester/frontend/src/api.ts` (matching the existing `API_BASE`/`fetch` pattern used by `runBacktest`/`fetchAdminSummary`):

```typescript
export async function startPipeline(body: {
  user_id: string; transcript?: string; url?: string; caption?: string; tweak?: string;
  symbol?: string; source?: string; interval?: string; capital?: number;
}): Promise<{ run_id: string }> {
  const resp = await fetch(`${API_BASE}/api/pipeline/start`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || "Failed to start pipeline");
  return resp.json();
}

export async function getPipelineRun(runId: string): Promise<import("./types").PipelineRunState> {
  const resp = await fetch(`${API_BASE}/api/pipeline/${runId}`);
  if (!resp.ok) throw new Error("Failed to fetch pipeline run");
  return resp.json();
}

export async function submitPipelineCheckpoint(
  runId: string, action: "confirm" | "tweak", tweakText?: string,
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/pipeline/${runId}/checkpoint`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, tweak_text: tweakText }),
  });
  if (!resp.ok) throw new Error("Failed to submit checkpoint response");
}

export async function retryPipelineSymbol(runId: string, symbol: string): Promise<{ run_id: string }> {
  const resp = await fetch(`${API_BASE}/api/pipeline/${runId}/retry-symbol`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol }),
  });
  if (!resp.ok) throw new Error("Failed to retry with new symbol");
  return resp.json();
}

export async function resumePipelineRun(runId: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/pipeline/${runId}/resume`, { method: "POST" });
  if (!resp.ok) throw new Error("Failed to resume run");
}
```

- [ ] **Step 3: Create `PipelinePage.tsx`**

```tsx
// backtester/frontend/src/components/PipelinePage.tsx
import { useEffect, useRef, useState } from "react";
import {
  startPipeline, getPipelineRun, submitPipelineCheckpoint,
  retryPipelineSymbol, resumePipelineRun,
} from "../api";
import type { PipelineRunState } from "../types";

const POLL_MS = 2000;

export default function PipelinePage({ userId }: { userId: string }) {
  const [transcript, setTranscript] = useState("");
  const [tweak, setTweak] = useState("");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<PipelineRunState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkpointTweak, setCheckpointTweak] = useState("");
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const state = await getPipelineRun(runId);
        setRun(state);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    poll();
    pollRef.current = window.setInterval(poll, POLL_MS);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [runId]);

  const handleStart = async () => {
    setError(null);
    try {
      const { run_id } = await startPipeline({ user_id: userId, transcript, tweak: tweak || undefined, symbol });
      setRunId(run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleConfirm = async () => {
    if (!runId) return;
    await submitPipelineCheckpoint(runId, "confirm");
  };

  const handleTweakSubmit = async () => {
    if (!runId || !checkpointTweak.trim()) return;
    await submitPipelineCheckpoint(runId, "tweak", checkpointTweak);
    setCheckpointTweak("");
  };

  const handleRetrySymbol = async (newSymbol: string) => {
    if (!runId) return;
    const { run_id } = await retryPipelineSymbol(runId, newSymbol);
    setRunId(run_id);
  };

  const handleResume = async () => {
    if (!runId) return;
    await resumePipelineRun(runId);
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Reel → Backtest Pipeline</h1>

      {!runId && (
        <div className="space-y-3">
          <textarea
            className="w-full border rounded p-2"
            rows={6}
            placeholder="Paste a transcript describing a trading strategy..."
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
          />
          <input
            className="w-full border rounded p-2 italic"
            placeholder='Optional: "also try this differently" — a free-text tweak'
            value={tweak}
            onChange={(e) => setTweak(e.target.value)}
          />
          <input
            className="w-full border rounded p-2"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
          />
          <button className="px-4 py-2 rounded bg-indigo-600 text-white" onClick={handleStart}>
            Run pipeline
          </button>
        </div>
      )}

      {error && <div className="text-red-600">{error}</div>}

      {run && (
        <div className="space-y-4">
          <div className="text-sm text-gray-500">Status: {run.status} — {run.stage}</div>

          {run.status === "interrupted" && (
            <div className="border border-amber-400 rounded p-3">
              This run was interrupted (likely a backend restart).
              <button className="ml-2 underline" onClick={handleResume}>Resume</button>
            </div>
          )}

          {run.status === "awaiting_checkpoint" && (
            <div className="border rounded p-3 space-y-2">
              <p>Confirm this strategy, or type a change (60–100s before we auto-proceed):</p>
              <pre className="text-xs bg-gray-100 p-2 rounded">{JSON.stringify(run.ir, null, 2)}</pre>
              <button className="px-3 py-1 rounded bg-indigo-600 text-white" onClick={handleConfirm}>
                Confirm
              </button>
              <div className="flex gap-2">
                <input
                  className="flex-1 border rounded p-2"
                  placeholder="e.g. use a faster EMA crossover"
                  value={checkpointTweak}
                  onChange={(e) => setCheckpointTweak(e.target.value)}
                />
                <button className="px-3 py-1 rounded border" onClick={handleTweakSubmit}>Apply tweak</button>
              </div>
            </div>
          )}

          {run.report && (
            <div className="space-y-3">
              <p className="text-base">{run.report.verdict}</p>
              <div className="flex flex-wrap gap-2">
                {run.report.chips.map((chip) => (
                  <span
                    key={chip.id}
                    className="px-3 py-1 rounded-full border text-sm cursor-pointer"
                    onClick={() => chip.id === "retry_symbol" && handleRetrySymbol(prompt("New symbol?") || run.symbol)}
                  >
                    <span
                      className={`inline-block w-2 h-2 rounded-full mr-2 ${chip.kind === "instant" ? "bg-indigo-500" : "bg-amber-500"}`}
                    />
                    {chip.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire into `App.tsx`**

In `backtester/frontend/src/App.tsx`, find the `page` state type declaration (currently `'backtest' | 'stress'` or similar per CLAUDE.md) and extend it to include `'pipeline'`. Add an import:

```typescript
import PipelinePage from "./components/PipelinePage";
```

Add a nav pill alongside the existing `Backtest`/`Stress`/`Reel Backtest` pills:

```tsx
<button onClick={() => setPage("pipeline")} className={navPillClass(page === "pipeline")}>
  🔁 Full Pipeline
</button>
```

(Match the exact `navPillClass`/button styling already used by the other nav pills — read the surrounding code in `App.tsx` before inserting to copy the exact class names rather than guessing.)

Add the render branch alongside the other `page === '...'` branches:

```tsx
{page === "pipeline" && <PipelinePage userId={identity.email || identity.sessionId} />}
```

(Match whatever the existing identity/session variable is actually called in `App.tsx` — read it first; do not assume `identity.email`/`identity.sessionId` are the exact names without checking.)

- [ ] **Step 5: Manually verify in the browser**

Start both servers per `CLAUDE.md`'s "How to Run" section, open http://localhost:5173, click the new "🔁 Full Pipeline" pill, paste a short transcript (e.g. "Buy Bitcoin every day at 24 hour intervals, invest $100 each time, hold for a week"), click "Run pipeline", and confirm:
1. Status progresses through `running` → `awaiting_checkpoint`.
2. The checkpoint IR renders and "Confirm" advances it to `looping`.
3. Polling eventually reaches `complete` with a verdict line and chips.
4. Clicking "Try this on another symbol" prompts for a symbol and starts a new run.

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\Harshit Kumar\Downloads\TradeVed Backtester"
git add backtester/frontend/src/types.ts backtester/frontend/src/api.ts backtester/frontend/src/components/PipelinePage.tsx backtester/frontend/src/App.tsx
git commit -m "feat(pipeline): add frontend PipelinePage driving the unified pipeline end-to-end"
```

---

## Post-plan note for the implementer

Task 5's `_run_loop_and_beyond` hardcodes a 730-day lookback window and a flat `$10,000` capital for the loop/holdout stages, and Task 7's manual browser check is the only UI-level verification in this plan. These are reasonable defaults to get an end-to-end path working per the approved spec, not final product decisions — flag both to the user after Task 7 lands, since capital and lookback window are exactly the kind of thing real usage will want configurable from the start screen.

**Deviation from spec, noted here for traceability:** the spec's API Surface section lists `GET /api/pipeline/{run_id}/stream` (SSE). Task 6/7 implement `GET /api/pipeline/{run_id}` polled every 2s from the frontend instead. Reasoning: every other SSE endpoint in this codebase (`stress/stream`, `forecast/stream`, `forecast/paper/stream`) streams a fast, tight loop of many events per second from a single blocking computation already running in the request handler. This pipeline's stage transitions are minutes apart (LLM calls, multi-round backtests, a real holdout run) and driven by a detached `asyncio.create_task`, not the request handler itself — there's no long-lived request to hang an SSE response off of without inventing a separate pub/sub layer between the background task and connected clients. Polling is the simpler mechanism for this specific shape of update (rare, DB-backed, cross-request) and costs nothing at current traffic. If UI responsiveness during the loop/holdout stages becomes a real complaint, revisit with a proper SSE broadcast (e.g. an in-memory `asyncio.Queue` per run_id that stage functions push to and the stream endpoint drains) as a follow-up, not a blocker for this plan.
