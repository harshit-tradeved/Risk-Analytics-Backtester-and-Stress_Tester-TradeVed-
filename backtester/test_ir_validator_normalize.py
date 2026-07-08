from ir_validator import normalize_ir, validate_ir


def test_normalize_ir_hoists_flat_custom_shape_into_strategy_params():
    """Regression test: a real reel (Turtle Trading Instagram video) made
    the extraction LLM emit entry_rules/exit_rules as top-level siblings of
    params, with invented extra keys, instead of the required
    {strategy, params} schema — even after prompt hardening and an LLM
    repair retry. This is deterministic-fixable without another LLM call."""
    drifted = {
        "name": "Donchian 20 Breakout with 10-Bar Low Exit",
        "long_short": "long",
        "suggested_interval": "3m",
        "entry_rules": [
            {"left": {"indicator": "close"}, "operator": "cross_above",
             "right": {"indicator": "donchian", "params": {"length": 20}, "output": "dc_upper"}},
        ],
        "exit_rules": [
            {"left": {"indicator": "close"}, "operator": "cross_below",
             "right": {"indicator": "donchian", "params": {"length": 10}, "output": "dc_lower"}},
        ],
        "params": {"stop_loss_pct": 5, "take_profit_pct": 10, "invest_per_trade_usd": 1000},
        "instrument": "REQUIRES_SPECIFICATION",
    }
    fixed = normalize_ir(drifted)
    assert fixed["strategy"] == "CUSTOM"
    assert fixed["params"]["stop_loss_pct"] == 5
    assert len(fixed["params"]["entry_rules"]) == 1
    assert len(fixed["params"]["exit_rules"]) == 1
    assert validate_ir(fixed) == []


def test_normalize_ir_leaves_already_valid_shape_untouched():
    ir = {"strategy": "DCA", "params": {"buy_interval_hours": 24, "invest_per_buy_usd": 100}}
    assert normalize_ir(ir) == ir


def test_normalize_ir_does_not_touch_dicts_with_no_rule_keys():
    ir = {"foo": "bar"}
    assert normalize_ir(ir) == {"foo": "bar"}


def test_normalize_ir_fixes_verbose_type_wrapper_operand_shapes():
    """Regression test: same Turtle Trading reel, a different LLM sampling
    run produced rule operands as {"type": "price", "source": "close"} and
    {"type": "indicator", "name": "donchian", ...} plus "op" instead of
    "operator" — all in the same response. Each is an unambiguous rename."""
    ir = {
        "strategy": "CUSTOM",
        "params": {
            "entry_rules": [{
                "left": {"type": "price", "source": "close"},
                "op": "cross_above",
                "right": {"type": "indicator", "name": "donchian", "params": {"length": 20}, "output": "dc_upper"},
            }],
            "exit_rules": [],
            "logic": "AND",
        },
    }
    fixed = normalize_ir(ir)
    rule = fixed["params"]["entry_rules"][0]
    assert rule["left"] == {"price": "close"}
    assert rule["operator"] == "cross_above"
    assert rule["right"] == {"indicator": "donchian", "params": {"length": 20}, "output": "dc_upper"}
    assert validate_ir(fixed) == []
