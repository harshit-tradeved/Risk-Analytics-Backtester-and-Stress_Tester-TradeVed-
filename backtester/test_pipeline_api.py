from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_pipeline_start_requires_input():
    resp = client.post("/api/pipeline/start", json={"user_id": "t@example.com"})
    assert resp.status_code == 400


def test_pipeline_start_returns_run_id():
    resp = client.post("/api/pipeline/start", json={
        "user_id": "start-only@example.com",
        "transcript": "Buy BTC every day and hold for a week.",
    })
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert run_id

    from database import SessionLocal
    import models
    db = SessionLocal()
    db.query(models.PipelineRun).filter_by(id=run_id).delete()
    db.commit()
    db.close()


def test_pipeline_start_blocks_second_active_run():
    """
    Seeds a 'running' row directly rather than starting a real run and
    racing against real extraction: this test is for assert_no_active_run's
    DB check, not for how fast a real LLM extraction call resolves. Racing
    real timing here was flaky — a second client.post() could land after
    the background task had already finished (or, in a dev environment with
    another server process also polling the same SQLite file, after a
    different process's sweep had already reinterpreted the row).
    """
    import uuid
    from database import SessionLocal, init_db
    import models

    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(id=run_id, user_id="dup2@example.com", status="running", stage="extracting"))
    db.commit()
    db.close()

    try:
        resp = client.post("/api/pipeline/start", json={
            "user_id": "dup2@example.com",
            "transcript": "Something else entirely.",
        })
        assert resp.status_code == 409
    finally:
        db = SessionLocal()
        db.query(models.PipelineRun).filter_by(id=run_id).delete()
        db.commit()
        db.close()


def test_get_pipeline_run_not_found_returns_404():
    resp = client.get("/api/pipeline/does-not-exist")
    assert resp.status_code == 404


def test_pipeline_checkpoint_confirm_does_not_500():
    """
    Regression test: pipeline_checkpoint/retry_symbol/resume must be `async
    def`, not sync `def`. FastAPI runs sync routes in a worker thread with
    no running asyncio event loop, so any orchestrator call that does
    asyncio.create_task() (submit_checkpoint_response, retry_with_new_symbol,
    resume_run) raised "RuntimeError: no running event loop" when these
    routes were plain `def`. Confirmed live via manual browser/curl testing
    before this test existed.
    """
    import json
    import uuid
    from database import SessionLocal, init_db
    import models

    init_db()
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    db.add(models.PipelineRun(
        id=run_id, user_id="checkpoint-regression@example.com",
        status="awaiting_checkpoint", stage="checkpoint",
        ir_json=json.dumps({"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}),
        symbol="BTC/USDT", timeframe="1d",
    ))
    db.commit()
    db.close()

    try:
        resp = client.post(f"/api/pipeline/{run_id}/checkpoint", json={"action": "confirm"})
        assert resp.status_code == 200
    finally:
        db = SessionLocal()
        db.query(models.PipelineRun).filter_by(id=run_id).delete()
        db.commit()
        db.close()
