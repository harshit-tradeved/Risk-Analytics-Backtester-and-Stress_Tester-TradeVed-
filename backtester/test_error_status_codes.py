import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

_BASE_BT = dict(
    symbol="BTC/USDT", source="kraken", interval="1d",
    start_date="2023-01-01", end_date="2023-02-01",
    capital=10000, strategy="DCA", market_type="equity_delivery",
    params={"buy_interval_hours": 24, "invest_per_buy_usd": 500,
            "hold_days": 10, "exit_type": "time"},
)


def test_backtest_run_unknown_source_is_422_not_500():
    resp = client.post("/api/backtest/run", json=_BASE_BT)
    assert resp.status_code == 422, resp.text
    assert "kraken" in resp.json()["detail"]


def test_stress_run_unknown_source_is_422_not_500():
    body = dict(_BASE_BT)
    body.pop("strategy")
    resp = client.post("/api/stress/run", json={
        **body,
        "strategy": "DCA",
        "scenario_key": "luna_collapse",
        "severity": 1.0,
        "monte_carlo_runs": 2,
    })
    assert resp.status_code == 422, resp.text
    assert "kraken" in resp.json()["detail"]


def test_backtest_run_custom_strategy_unknown_indicator_is_422_not_500():
    body = dict(_BASE_BT)
    body["source"] = "binance"
    body["strategy"] = "CUSTOM"
    body["params"] = {
        "entry_rules": [{
            "left": {"indicator": "nonexistent_indicator_xyz", "params": {}, "output": "value"},
            "operator": "<",
            "right": {"value": 30},
        }],
        "exit_rules": [],
        "logic": "AND",
        "invest_per_trade_usd": 500,
    }
    resp = client.post("/api/backtest/run", json=body)
    assert resp.status_code == 422, resp.text
    assert "nonexistent_indicator_xyz" in resp.json()["detail"]
