import json

import reel_extractor


def test_normalize_to_ir_with_retry_uses_first_result_when_non_null(monkeypatch):
    calls = []

    def fake_llm(system, user, max_tokens=1200):
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

    def fake_llm(system, user, max_tokens=1200):
        calls.append(system)
        return responses.pop(0)

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor._normalize_to_ir_with_retry({"entry_conditions": ["something vague"]})
    assert result["strategy_ir"]["strategy"] == "CUSTOM"
    assert len(calls) == 2
    assert "RETRY NOTICE" in calls[1]


def test_normalize_to_ir_with_retry_gives_up_after_two_nulls(monkeypatch):
    def fake_llm(system, user, max_tokens=1200):
        return json.dumps({"strategy_ir": None, "gaps": ["genuinely not a strategy"]})

    monkeypatch.setattr(reel_extractor, "_llm", fake_llm)
    result = reel_extractor._normalize_to_ir_with_retry({"entry_conditions": []})
    assert result["strategy_ir"] is None
