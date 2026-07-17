import json

from reel_to_backtest.backend import reel_extractor


def test_suggest_fallback_ir_returns_disclaimer_and_decoded_ir_from_llm(monkeypatch):
    def fake_llm(system, user, max_tokens=1200, response_schema=None):
        return json.dumps({
            "disclaimer": "This video describes buying near support zones, which isn't a precise numeric rule.",
            "strategy_ir": {"strategy": "RSI", "params": '{"rsi_period": 14, "oversold": 30, "invest_per_trade_usd": 1000}'},
            "suggested_symbol": "ETH/USDT",
            "suggested_source": "binance",
            "suggested_interval": "1d",
        })

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor.suggest_fallback_ir("buy near support", "", ["no precise entry rule"])

    assert "support" in result["disclaimer"]
    assert result["strategy_ir"]["strategy"] == "RSI"
    assert isinstance(result["strategy_ir"]["params"], dict)
    assert result["strategy_ir"]["params"]["rsi_period"] == 14
    assert result["suggested_symbol"] == "ETH/USDT"


def test_suggest_fallback_ir_falls_back_to_dca_default_on_llm_failure(monkeypatch):
    """Regression: even a total LLM failure (timeout, malformed response,
    provider outage) must never leave the user with nothing — a safe generic
    DCA default plus an honest disclaimer is always returned."""
    def fake_llm(system, user, max_tokens=1200, response_schema=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor.suggest_fallback_ir("some vague video", "", [])

    assert result["strategy_ir"]["strategy"] == "DCA"
    assert result["strategy_ir"]["params"]["invest_per_buy_usd"] > 0
    assert isinstance(result["disclaimer"], str) and result["disclaimer"]
