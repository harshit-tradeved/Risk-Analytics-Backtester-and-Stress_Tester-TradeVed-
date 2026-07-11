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


def test_normalize_ir_fixes_preset_name_paired_with_custom_params():
    """Regression test: after constraining the extraction schema's "strategy"
    field to a valid enum (to stop the model inventing names like
    "long_only"), the model started picking a real preset name (e.g.
    DONCHIAN) that matched the described indicator but still filled params
    with CUSTOM's rule-builder fields (entry_rules/exit_rules) rather than
    that preset's actual schema. Only CUSTOM ever has those fields."""
    ir = {
        "strategy": "DONCHIAN",
        "params": {
            "entry_rules": [{"left": {"price": "close"}, "operator": "cross_above",
                              "right": {"indicator": "donchian", "params": {"length": 20}, "output": "dc_upper"}}],
            "exit_rules": [],
            "stop_loss_pct": 3,
            "take_profit_pct": 6,
        },
    }
    fixed = normalize_ir(ir)
    assert fixed["strategy"] == "CUSTOM"
    assert validate_ir(fixed) == []


def test_normalize_ir_fixes_string_shorthand_operands():
    """Regression test: live E2E run on the Turtle Trading Instagram reel
    (2026-07-10) — the extraction LLM emitted rule operands as bare strings
    with call-style indicator params and a separate right_output key:
      {"left": "close", "op": "cross_above",
       "right": "donchian(20)", "right_output": "dc_upper"}
    which failed validation with 'rule must be a dict' (on a sibling sampling
    that emitted whole rules as strings) / operand errors. Every piece is an
    unambiguous mechanical rename, so it must be fixed deterministically."""
    ir = {
        "strategy": "DONCHIAN",
        "params": {
            "entry_rules": [
                {"left": "close", "op": "cross_above",
                 "right": "donchian(20)", "right_output": "dc_upper"},
            ],
            "exit_rules": [
                {"left": "close", "op": "cross_below",
                 "right": "donchian(10)", "right_output": "dc_lower"},
            ],
            "stop_loss_pct": 2, "take_profit_pct": 4, "invest_per_trade_usd": 1000,
        },
    }
    fixed = normalize_ir(ir)
    assert fixed["strategy"] == "CUSTOM"
    entry = fixed["params"]["entry_rules"][0]
    assert entry["left"] == {"price": "close"}
    assert entry["operator"] == "cross_above"
    assert entry["right"] == {"indicator": "donchian", "params": {"length": 20}, "output": "dc_upper"}
    exit_ = fixed["params"]["exit_rules"][0]
    assert exit_["right"] == {"indicator": "donchian", "params": {"length": 10}, "output": "dc_lower"}
    assert validate_ir(fixed) == []


def test_normalize_ir_decodes_json_string_rules_and_numeric_operands():
    """Rules double-encoded as JSON strings, bare numeric strings, and
    multi-arg call-style indicators must all normalize deterministically."""
    ir = {
        "strategy": "CUSTOM",
        "params": {
            "entry_rules": [
                '{"left": "rsi(14)", "operator": "cross_above", "right": "50"}',
                {"left": "supertrend(10, 3)", "operator": "<", "right": "close",
                 "left_output": "supertrend"},
            ],
            "exit_rules": [],
        },
    }
    fixed = normalize_ir(ir)
    r0, r1 = fixed["params"]["entry_rules"]
    assert r0["left"] == {"indicator": "rsi", "params": {"length": 14}}
    assert r0["right"] == {"value": 50.0}
    assert r1["left"] == {"indicator": "supertrend", "params": {"length": 10, "multiplier": 3},
                          "output": "supertrend"}
    assert r1["right"] == {"price": "close"}
    assert validate_ir(fixed) == []


def test_normalize_ir_parses_dsl_expression_string_rules():
    """Regression test: live E2E run (2026-07-10) — /api/reel/analyze returned
    entry_rules=["rsi(14) < 30"] and exit_rules=["rsi(14) cross_above 70"] as
    plain DSL strings, so validate_ir reported 'rule must be a dict' and the
    frontend rendered '? undefined ?'. Simple <operand> <op> <operand>
    expressions are deterministically parseable."""
    from ir_validator import _normalize_rule

    assert _normalize_rule("rsi(14) < 30") == {
        "left": {"indicator": "rsi", "params": {"length": 14}},
        "operator": "<",
        "right": {"value": 30.0},
    }
    assert _normalize_rule("rsi(14) cross_above 70") == {
        "left": {"indicator": "rsi", "params": {"length": 14}},
        "operator": "cross_above",
        "right": {"value": 70.0},
    }
    assert _normalize_rule("close > sma(50)") == {
        "left": {"price": "close"},
        "operator": ">",
        "right": {"indicator": "sma", "params": {"length": 50}},
    }
    assert _normalize_rule("macd() cross_above 0") == {
        "left": {"indicator": "macd"},
        "operator": "cross_above",
        "right": {"value": 0.0},
    }
    # Word-operator variant and bare "price" keyword.
    assert _normalize_rule("price crosses above ema(21)") == {
        "left": {"price": "close"},
        "operator": "cross_above",
        "right": {"indicator": "ema", "params": {"length": 21}},
    }
    # Output-series shorthand resolves to the owning indicator.
    assert _normalize_rule("macd_signal < 0") == {
        "left": {"indicator": "macd", "output": "macd_signal"},
        "operator": "<",
        "right": {"value": 0.0},
    }


def test_normalize_ir_leaves_unparseable_strings_unchanged():
    """Garbage / ambiguous strings must pass through untouched so validate_ir
    reports them exactly as before."""
    from ir_validator import _normalize_rule

    assert _normalize_rule("buy the dip when it feels right") == \
        "buy the dip when it feels right"
    assert _normalize_rule("frobnicator(9) < 30") == "frobnicator(9) < 30"  # unknown indicator
    assert _normalize_rule("rsi(14) < 30 < 70") == "rsi(14) < 30 < 70"      # two operators


def test_normalize_ir_end_to_end_on_live_dsl_string_ir():
    """The exact live IR from the E2E run: CUSTOM strategy with plain DSL
    string rules must come out validate_ir-clean."""
    ir = {
        "strategy": "CUSTOM",
        "params": {
            "entry_rules": ["rsi(14) < 30"],
            "exit_rules":  ["rsi(14) cross_above 70"],
        },
    }
    fixed = normalize_ir(ir)
    assert fixed["params"]["entry_rules"] == [{
        "left": {"indicator": "rsi", "params": {"length": 14}},
        "operator": "<",
        "right": {"value": 30.0},
    }]
    assert fixed["params"]["exit_rules"] == [{
        "left": {"indicator": "rsi", "params": {"length": 14}},
        "operator": "cross_above",
        "right": {"value": 70.0},
    }]
    assert validate_ir(fixed) == []


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
