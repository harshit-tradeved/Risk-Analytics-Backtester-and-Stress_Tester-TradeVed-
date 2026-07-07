import asyncio
import json
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
