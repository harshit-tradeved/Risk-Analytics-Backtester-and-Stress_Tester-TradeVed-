import json

from reel_to_backtest import reel_extractor


def test_normalize_to_ir_with_retry_uses_first_result_when_non_null(monkeypatch):
    calls = []

    def fake_llm(system, user, max_tokens=1200, response_schema=None):
        calls.append(system)
        return json.dumps({"strategy_ir": {"strategy": "RSI", "params": {}}, "gaps": []})

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor._normalize_to_ir_with_retry({"entry_conditions": ["rsi(14) < 30"]})
    assert result["strategy_ir"]["strategy"] == "RSI"
    assert len(calls) == 1  # no retry needed


def test_normalize_to_ir_with_retry_retries_once_on_null_and_succeeds(monkeypatch):
    responses = [
        json.dumps({"strategy_ir": None, "gaps": ["too vague"]}),
        json.dumps({"strategy_ir": {"strategy": "CUSTOM", "params": {"entry_rules": []}}, "gaps": ["defaulted"]}),
    ]
    calls = []

    def fake_llm(system, user, max_tokens=1200, response_schema=None):
        calls.append(system)
        return responses.pop(0)

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor._normalize_to_ir_with_retry({"entry_conditions": ["something vague"]})
    assert result["strategy_ir"]["strategy"] == "CUSTOM"
    assert len(calls) == 2
    assert "RETRY NOTICE" in calls[1]


def test_normalize_to_ir_decodes_params_json_string_from_schema_response(monkeypatch):
    """The strict response schema forces strategy_ir.params to be a
    JSON-encoded string (Azure/OpenAI strict mode rejects a genuinely
    open-ended nested object) — _normalize_to_ir must decode it back to a
    dict before returning, so every downstream caller sees the normal
    IR shape unchanged."""
    def fake_llm(system, user, max_tokens=1200, response_schema=None):
        return json.dumps({
            "strategy_ir": {"strategy": "CUSTOM", "params": '{"entry_rules": [], "stop_loss_pct": 3}'},
            "gaps": [],
        })

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor._normalize_to_ir({"entry_conditions": ["x"]})
    assert isinstance(result["strategy_ir"]["params"], dict)
    assert result["strategy_ir"]["params"]["stop_loss_pct"] == 3


def test_normalize_to_ir_with_retry_gives_up_after_two_nulls(monkeypatch):
    def fake_llm(system, user, max_tokens=1200, response_schema=None):
        return json.dumps({"strategy_ir": None, "gaps": ["genuinely not a strategy"]})

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor._normalize_to_ir_with_retry({"entry_conditions": []})
    assert result["strategy_ir"] is None
