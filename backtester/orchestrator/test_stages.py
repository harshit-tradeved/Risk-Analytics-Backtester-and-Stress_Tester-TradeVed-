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
