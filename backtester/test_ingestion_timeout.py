import asyncio
import time

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def test_pipeline_start_times_out_instead_of_hanging(monkeypatch):
    def _slow_handle_url(url):
        time.sleep(2)
        return {"transcript": "should never get here"}

    monkeypatch.setattr("reel_to_backtest.ingestion.handle_url", _slow_handle_url)
    monkeypatch.setattr(main, "INGESTION_TIMEOUT_SECS", 0.3)

    resp = client.post("/api/pipeline/start", json={
        "user_id": "timeout-test@example.com",
        "url": "https://www.youtube.com/watch?v=fake",
    })
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()


def test_reel_analyze_times_out_instead_of_hanging(monkeypatch):
    def _slow_handle_url(url):
        time.sleep(2)
        return {"transcript": "should never get here"}

    monkeypatch.setattr("reel_to_backtest.ingestion.handle_url", _slow_handle_url)
    monkeypatch.setattr(main, "INGESTION_TIMEOUT_SECS", 0.3)

    resp = client.post("/api/reel/analyze", json={
        "url": "https://www.youtube.com/watch?v=fake",
    })
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()
