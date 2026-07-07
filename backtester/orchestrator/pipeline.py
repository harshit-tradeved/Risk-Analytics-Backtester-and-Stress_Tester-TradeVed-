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
from typing import Optional

from sqlalchemy.orm import Session

import models
from database import SessionLocal
from improvement_agent import critique_and_improve
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
LOOKBACK_DAYS = 730
DEFAULT_CAPITAL = 10_000.0

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
            date.today() - timedelta(days=LOOKBACK_DAYS), date.today(),
        )
        sim_kwargs = {"symbol": row.symbol}
        capital = DEFAULT_CAPITAL
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
        symbol=symbol, interval=timeframe, start_date=date.today() - timedelta(days=365),
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
