import asyncio
import json
import uuid

import pandas as pd
import pytest

from database import SessionLocal, init_db
import models
from orchestrator import pipeline


def _cleanup(run_id: str):
    db = SessionLocal()
    db.query(models.PipelineRun).filter_by(id=run_id).delete()
    db.commit()
    db.close()


def _synthetic_df(n=300):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    price = 100 + (pd.Series(range(n)) * 0.1).values
    return pd.DataFrame({
        "timestamp": dates, "open": price, "high": price * 1.01,
        "low": price * 0.99, "close": price, "volume": 1000.0,
    })


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


def test_sweep_once_does_not_interrupt_a_fresh_unexpired_checkpoint():
    """
    Regression test: a run resting at 'awaiting_checkpoint' has no live task
    by design (the task that opened the checkpoint already returned). Before
    the fix, sweep_once's orphan check treated any active-status row with no
    live task as interrupted, which meant EVERY run got marked interrupted
    the instant it reached a checkpoint, even with time still left on the
    clock. This confirms that no longer happens for a fresh, unexpired one.
    """
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(
        id=run_id, user_id="fresh@example.com", status="awaiting_checkpoint", stage="checkpoint",
        ir_json=json.dumps({"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}),
        symbol="BTC/USDT", timeframe="1d",
        checkpoint_opened_at=pipeline._utcnow_minus_seconds(5), checkpoint_timeout_secs=90,
    ))
    db.commit()
    db.close()
    try:
        pipeline.sweep_once()
        db = SessionLocal()
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        assert row.status == "awaiting_checkpoint"
        db.close()
    finally:
        _cleanup(run_id)


def test_run_loop_and_beyond_uses_run_capital_not_hardcoded_default(monkeypatch):
    """
    Regression test: the user's actual submitted capital (req.capital at
    /api/pipeline/start) was correctly used for extraction-time position
    sizing, but _run_loop_and_beyond hardcoded the module-level
    DEFAULT_CAPITAL constant (10_000.0) for every backtest after the
    checkpoint stage — silently ignoring whatever the user actually
    submitted, because the checkpoint boundary starts a fresh async chain
    with no captured capital variable.
    """
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(
        id=run_id, user_id="cap@example.com", status="looping", stage="loop_round_1",
        ir_json=json.dumps({"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}),
        symbol="BTC/USDT", timeframe="1d", capital=55555.0,
        loop_round=0, composite_scores_json=json.dumps([]),
    ))
    db.commit()
    db.close()

    captured_capital = []

    def fake_run_loop_round(df, ir, capital, sim_kwargs, symbol, interval):
        captured_capital.append(capital)
        return {"score": 1.0, "metrics": {"num_trades": 1}}

    monkeypatch.setattr(pipeline, "fetch_and_validate_data", lambda *a, **k: _synthetic_df())
    monkeypatch.setattr(pipeline, "run_loop_round", fake_run_loop_round)
    monkeypatch.setattr(pipeline, "run_holdout_check", lambda *a, **k: {"verdict": "stable"})
    monkeypatch.setattr(pipeline, "critique_and_improve", lambda *a, **k: {"improved_ir": None})

    try:
        asyncio.run(pipeline._run_loop_and_beyond(run_id))
        assert captured_capital
        assert captured_capital[0] == 55555.0
    finally:
        _cleanup(run_id)


def test_run_pipeline_uses_fallback_suggestion_instead_of_dead_ending_on_extraction_failure(monkeypatch):
    """
    Regression test / new behavior: when extraction genuinely fails
    (strategy_ir is None even after its own internal retry — e.g.
    discretionary/visual content), the run must NOT just dead-end into
    status="failed". It should fall back to a practical LLM-generated
    disclaimer plus a best-choice minimal-viable IR, land at the same
    checkpoint the normal path uses, and let the user review/edit it there.
    """
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(
        id=run_id, user_id="fallback@example.com", status="running", stage="extracting",
        symbol="BTC/USDT", timeframe="1d", source="binance", capital=10000.0,
    ))
    db.commit()
    db.close()

    from orchestrator import stages

    def fake_extract_ir(transcript, caption, tweak=None):
        return {"strategy_ir": None, "gaps": ["no numeric entry condition"], "confidence": 0.1}

    def fake_build_fallback_suggestion(transcript, caption, gaps):
        return {
            "disclaimer": "This video describes a discretionary support-zone entry, not a numeric rule.",
            "strategy_ir": {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 1000}},
            "suggested_symbol": None, "suggested_source": None, "suggested_interval": None,
        }

    monkeypatch.setattr(pipeline, "extract_ir", fake_extract_ir)
    monkeypatch.setattr(pipeline, "build_fallback_suggestion", fake_build_fallback_suggestion)

    try:
        asyncio.run(pipeline._run_pipeline(run_id, "buy near support", "", None, None, 10000.0, None))
        db = SessionLocal()
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        assert row.status == "awaiting_checkpoint"
        assert "discretionary" in row.disclaimer
        ir = json.loads(row.ir_json)
        assert ir["strategy"] == "DCA"
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
