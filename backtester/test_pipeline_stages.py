import pandas as pd
from reel_to_pipeline.backend.stages import (
    validate_and_normalize, run_loop_round, build_report,
    apply_default_position_size, validate_and_repair, resolve_run_target,
    build_fallback_suggestion,
)


def test_build_fallback_suggestion_delegates_to_reel_extractor(monkeypatch):
    from reel_to_backtest.backend import reel_extractor

    def fake_suggest(transcript, caption, gaps):
        assert transcript == "buy near support"
        assert gaps == ["no numeric entry"]
        return {
            "disclaimer": "too vague", "strategy_ir": {"strategy": "DCA", "params": {}},
            "suggested_symbol": None, "suggested_source": None, "suggested_interval": None,
        }

    monkeypatch.setattr(reel_extractor, "suggest_fallback_ir", fake_suggest)
    result = build_fallback_suggestion("buy near support", "", ["no numeric entry"])
    assert result["disclaimer"] == "too vague"
    assert result["strategy_ir"]["strategy"] == "DCA"


def test_resolve_run_target_uses_explicit_values_when_given():
    symbol, source, interval = resolve_run_target(
        "ETH/USDT", "binance", "4h",
        {"suggested_symbol": "BTC/USDT", "suggested_source": "yfinance", "suggested_interval": "1h"},
    )
    assert (symbol, source, interval) == ("ETH/USDT", "binance", "4h")


def test_resolve_run_target_falls_back_to_extraction_suggestions_when_unset():
    """Regression test: extract_strategy_ir() computes suggested_symbol/
    suggested_source/suggested_interval from the transcript (e.g. a reel
    about an NSE stock), but nothing downstream ever read them — the run
    just silently used whatever the caller defaulted symbol/source/interval
    to, ignoring what the video actually described."""
    symbol, source, interval = resolve_run_target(
        None, None, None,
        {"suggested_symbol": "RELIANCE", "suggested_source": "nse", "suggested_interval": "1d"},
    )
    assert (symbol, source, interval) == ("RELIANCE", "nse", "1d")


def test_resolve_run_target_falls_back_to_hardcoded_defaults_when_nothing_suggested():
    symbol, source, interval = resolve_run_target(None, None, None, {})
    assert (symbol, source, interval) == ("BTC/USDT", "binance", "1d")


def test_resolve_run_target_sanitizes_llm_suggested_source_casing():
    """Regression test: live E2E run on a forex YouTube video (2026-07-10) —
    the extraction LLM suggested source "BINANCE" (uppercase). The fetcher's
    source registry is lowercase-keyed, so fetchers.get("BINANCE") returned
    None for every source and the run failed with the baffling
    'All data sources failed ... Last error: None'."""
    symbol, source, interval = resolve_run_target(
        None, None, None,
        {"suggested_symbol": "SOL/USDT", "suggested_source": "BINANCE", "suggested_interval": "1H"},
    )
    assert source == "binance"
    assert interval == "1h"


def test_resolve_run_target_maps_unknown_source_to_auto():
    """A suggested source outside {binance,yfinance,nse,bse,auto} (e.g.
    "forex", "oanda") must degrade to "auto" (binance→yfinance chain), never
    reach the fetcher verbatim."""
    _, source, _ = resolve_run_target(
        None, None, None,
        {"suggested_symbol": "SPY", "suggested_source": "alpaca", "suggested_interval": "1h"},
    )
    assert source == "auto"


def test_resolve_run_target_routes_forex_pairs_to_yfinance():
    """Same live run: symbol AUDCAD with source binance can never succeed —
    Binance has no fiat forex pairs. Currency-pair symbols must route to
    yfinance (which serves them as AUDCAD=X) regardless of the suggested
    source."""
    symbol, source, _ = resolve_run_target(
        None, None, None,
        {"suggested_symbol": "AUDCAD", "suggested_source": "BINANCE", "suggested_interval": "1h"},
    )
    assert symbol == "AUDCAD"
    assert source == "yfinance"


def test_fetch_with_source_fallback_retries_on_auto(monkeypatch):
    """If the resolved source fails outright, retry once with source='auto'
    (binance→yfinance chain) before failing the whole run."""
    import reel_to_pipeline.backend.stages as stages
    from datetime import date

    calls = []

    def fake_fetch(symbol, source, interval, start, end):
        calls.append(source)
        if source == "binance":
            raise ValueError("All data sources failed for 'AUDCAD'. Last error: None")
        return pd.DataFrame({"close": [1.0]})

    monkeypatch.setattr(stages, "fetch_and_validate_data", fake_fetch)
    df, used = stages.fetch_with_source_fallback("AUDCAD", "binance", "1h", date(2024, 1, 1), date(2025, 1, 1))
    assert calls == ["binance", "auto"]
    assert used == "auto"
    assert not df.empty


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
    from reel_to_backtest.backend import improvement_agent

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
    from reel_to_backtest.backend import improvement_agent

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
