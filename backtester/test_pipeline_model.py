from backtesting.engine.metrics import score_backtest


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


def test_run_segment_backtest_alias_exists():
    from backtesting.engine.validation import run_segment_backtest, _segment_metrics
    assert run_segment_backtest is _segment_metrics


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
