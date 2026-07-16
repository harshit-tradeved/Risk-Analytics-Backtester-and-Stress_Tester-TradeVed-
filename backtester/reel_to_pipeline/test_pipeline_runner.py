import asyncio
import json
import uuid

import pandas as pd
import pytest

from database import SessionLocal, init_db
import models
from reel_to_pipeline import pipeline


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

    from reel_to_pipeline import stages

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


def test_run_loop_and_beyond_reverts_to_best_ir_when_improved_round_scores_worse(monkeypatch):
    """
    Regression test (live run 3498ef3d): the loop replaces `ir` with the
    critique's improved IR at the END of each iteration, BEFORE the next
    round scores it. When the improved IR scores WORSE (round 1: 0.5583,
    round 2: 0.5062), the plateau check breaks the loop but `ir` still
    holds the worse round-2 IR — so holdout, paper trading, and the report
    all ran on an IR inferior to round 1's. The fix tracks the best-scoring
    (score, ir) pair and reverts to it after the loop; build_report must
    also surface the BEST score, not blindly scores[-1].
    """
    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    round1_ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}
    round2_ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 250}}
    db.add(models.PipelineRun(
        id=run_id, user_id="best@example.com", status="looping", stage="loop_round_1",
        ir_json=json.dumps(round1_ir),
        symbol="BTC/USDT", timeframe="1d", capital=10000.0,
        loop_round=0, composite_scores_json=json.dumps([]),
    ))
    db.commit()
    db.close()

    round_irs = []
    round_scores = [0.5583, 0.5062]  # round 2 (the "improved" IR) scores worse

    def fake_run_loop_round(df, ir, capital, sim_kwargs, symbol, interval):
        round_irs.append(json.loads(json.dumps(ir)))
        return {"score": round_scores[len(round_irs) - 1], "metrics": {"num_trades": 1}}

    holdout_irs = []

    def fake_run_holdout_check(df, ir, capital, sim_kwargs):
        holdout_irs.append(json.loads(json.dumps(ir)))
        return {"verdict": "stable"}

    async def fake_paper_trading(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "fetch_with_source_fallback", lambda *a, **k: (_synthetic_df(), "binance"))
    monkeypatch.setattr(pipeline, "run_loop_round", fake_run_loop_round)
    monkeypatch.setattr(pipeline, "run_holdout_check", fake_run_holdout_check)
    monkeypatch.setattr(pipeline, "critique_and_improve", lambda *a, **k: {"improved_ir": round2_ir})
    monkeypatch.setattr(pipeline, "validate_and_normalize", lambda ir: (ir, []))
    monkeypatch.setattr(pipeline, "_run_paper_trading", fake_paper_trading)

    try:
        asyncio.run(pipeline._run_loop_and_beyond(run_id))

        # Both rounds ran: round 1 on the original IR, round 2 on the improved one.
        assert len(round_irs) == 2
        assert round_irs[0] == round1_ir
        assert round_irs[1] == round2_ir

        # Holdout must have used the round-1 (best-scoring) IR, not round 2's.
        assert holdout_irs == [round1_ir]

        db = SessionLocal()
        row = db.query(models.PipelineRun).filter_by(id=run_id).first()
        # Persisted IR reverted to the best-scoring one.
        assert json.loads(row.ir_json) == round1_ir
        # Report surfaces the BEST score, and the raw round history is untouched.
        report = json.loads(row.report_json)
        assert report["last_score"] == pytest.approx(0.5583)
        scores = json.loads(row.composite_scores_json)
        assert [s["score"] for s in scores] == round_scores
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
