import pandas as pd
from orchestrator.stages import (
    validate_and_normalize, run_loop_round, build_report,
    apply_default_position_size, validate_and_repair,
)


def test_validate_and_repair_passes_through_when_already_valid():
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}
    normalized, errors = validate_and_repair(ir)
    assert errors == []
    assert normalized["strategy"] == "DCA"


def test_validate_and_repair_fixes_schema_drift_via_llm_repair(monkeypatch):
    """Regression test: a real reel once produced an IR with invented
    top-level keys (name/version/market/direction) instead of the exact
    {strategy, params} schema. validate_and_repair should catch that via
    validate_ir's errors and fix it with one improvement_agent.repair_improved_ir()
    call rather than failing outright."""
    import improvement_agent

    drifted_ir = {"name": "my_strategy", "entry_rules": [], "direction": "long"}
    fixed_ir = {
        "strategy": "CUSTOM",
        "params": {
            "entry_rules": [{"left": {"indicator": "rsi", "params": {}, "output": "rsi"}, "operator": "<", "right": {"value": 30}}],
            "exit_rules": [], "logic": "AND",
        },
    }

    def fake_repair(ir, errors, original_ir):
        assert ir is drifted_ir
        return fixed_ir

    monkeypatch.setattr(improvement_agent, "repair_improved_ir", fake_repair)
    normalized, errors = validate_and_repair(drifted_ir)
    assert errors == []
    assert normalized["strategy"] == "CUSTOM"


def test_validate_and_repair_gives_up_if_repair_still_invalid(monkeypatch):
    import improvement_agent

    drifted_ir = {"totally": "wrong"}
    monkeypatch.setattr(improvement_agent, "repair_improved_ir", lambda ir, errors, original_ir: {"still": "wrong"})
    normalized, errors = validate_and_repair(drifted_ir)
    assert len(errors) > 0


def test_apply_default_position_size_fills_missing_invest_per_trade_usd():
    ir = {"strategy": "CUSTOM", "params": {"entry_rules": [], "exit_rules": [], "logic": "AND"}}
    result = apply_default_position_size(ir, capital=10000)
    assert result["params"]["invest_per_trade_usd"] > 0


def test_apply_default_position_size_preserves_explicit_value():
    ir = {"strategy": "RSI", "params": {"invest_per_trade_usd": 250}}
    result = apply_default_position_size(ir, capital=10000)
    assert result["params"]["invest_per_trade_usd"] == 250


def test_apply_default_position_size_ignores_classic_strategies():
    """DCA/GRID/PLA already get full sane defaults merged in at run time via
    default_params() — this helper only needs to cover CUSTOM/indicator
    presets, whose invest_per_trade_usd field is what reel_extractor's own
    gap-filling prompt targets but doesn't always reliably set."""
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24}}
    result = apply_default_position_size(ir, capital=10000)
    assert "invest_per_trade_usd" not in result["params"]


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
