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
