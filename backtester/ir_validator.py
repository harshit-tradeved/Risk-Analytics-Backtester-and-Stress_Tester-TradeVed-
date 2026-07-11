"""
Deterministic IR (Intermediate Representation) validator.

Validates a Strategy IR dict against the live STRATEGY_REGISTRY and
INDICATOR_CATALOG before it is compiled into a backtest run. No LLM involved —
pure structural checks so errors are reported clearly to the user.

Exported:
    validate_ir(ir: dict) -> list[str]   — returns list of error strings (empty = valid)
"""
from __future__ import annotations

import json
import re
from typing import Any

from engine.indicators import CATALOG_BY_KEY
from strategies import STRATEGY_REGISTRY

_CLASSIC = {"GRID", "DCA", "PLA"}
_OPERATORS = {">", ">=", "<", "<=", "cross_above", "cross_below"}
_PRICE_COLS = {"open", "high", "low", "close", "volume"}


# ── IR normalization (auto-fix common LLM shape mistakes before validation) ──
# Found via reel_pipeline_test_results_100.xlsx (148-URL run): the extraction/
# critique LLM occasionally emits operand shapes that are unambiguous mistakes
# rather than genuine ambiguity, so it's safe to auto-correct instead of
# hard-failing validation.

# "donchian(20)" / "supertrend(10, 3)" — call-style indicator shorthand.
_CALL_STYLE_RE = re.compile(r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?$")

# "rsi(14) < 30" — a whole rule expressed as a single DSL string (live
# /api/reel/analyze run, 2026-07-10: entry_rules=["rsi(14) < 30"],
# exit_rules=["rsi(14) cross_above 70"]). Split on exactly one comparison
# operator; word variants ("crosses above") are canonicalised first.
_DSL_OP_RE = re.compile(r"\s*(cross_above|cross_below|>=|<=|==|>|<)\s*", re.IGNORECASE)
_CROSS_ABOVE_RE = re.compile(r"cross(?:es)?[\s_]+above", re.IGNORECASE)
_CROSS_BELOW_RE = re.compile(r"cross(?:es)?[\s_]+below", re.IGNORECASE)


def _coerce_number(text: str) -> Any:
    try:
        f = float(text)
    except (TypeError, ValueError):
        return text
    return int(f) if f.is_integer() else f


def _normalize_operand(operand: Any) -> Any:
    # Bare numeric literal instead of {"value": N}
    if isinstance(operand, (int, float)):
        return {"value": float(operand)}
    # Bare string shorthand — found via live E2E run on a real Instagram reel
    # (2026-07-10): {"left": "close", "op": "cross_above", "right":
    # "donchian(20)", "right_output": "dc_upper"}. Price columns, numeric
    # literals, and call-style indicator params are all mechanical renames.
    if isinstance(operand, str):
        s = operand.strip()
        if s.lower() in _PRICE_COLS:
            return {"price": s.lower()}
        num = _coerce_number(s)
        if not isinstance(num, str):
            return {"value": float(num)}
        if s.lower() == "price":
            # Bare "price" — unqualified price reference means the close.
            return {"price": "close"}
        m = _CALL_STYLE_RE.match(s)
        if m:
            tok = m.group(1).lower()
            key = tok if tok in CATALOG_BY_KEY else None
            output = None
            if key is None:
                # Output-series shorthand, e.g. "macd_signal" / "dc_upper(20)"
                # — resolve to the owning indicator only if the output name is
                # unique across the catalog (it currently always is).
                owners = [k for k, e in CATALOG_BY_KEY.items() if tok in e["outputs"]]
                if len(owners) == 1:
                    key, output = owners[0], tok
            if key is not None:
                out: dict[str, Any] = {"indicator": key}
                args = [a.strip() for a in (m.group(2) or "").split(",") if a.strip()]
                if args:
                    names = [p["name"] for p in CATALOG_BY_KEY[key]["params"]]
                    out["params"] = {name: _coerce_number(arg) for name, arg in zip(names, args)}
                if output:
                    out["output"] = output
                return out
        return operand
    if not isinstance(operand, dict):
        return operand
    # {"type": "price", "source"/"field": "close"} — a verbose wrapper style
    # seen on real reel extractions instead of the plain {"price": "close"}.
    if operand.get("type") == "price":
        col = operand.get("source") or operand.get("field") or operand.get("price")
        if col:
            return {"price": col}
    # {"type": "indicator", "name": "<key>", "params": {...}, "output": "<col>"}
    # — same verbose-wrapper drift, indicator variant.
    if operand.get("type") == "indicator" and "name" in operand:
        out = {"indicator": operand["name"]}
        if "params" in operand:
            out["params"] = operand["params"]
        if "output" in operand:
            out["output"] = operand["output"]
        return out
    # {"indicator": "close"} etc. — LLM confused a raw price column with an
    # indicator key (INDICATOR_CATALOG has no "close"/"open"/... entries).
    if "indicator" in operand and operand.get("indicator") in _PRICE_COLS and "price" not in operand:
        return {"price": operand["indicator"]}
    # {"left": {...}} with no value/price/indicator of its own — LLM nested a
    # second comparison operand inside a "left" wrapper instead of giving it
    # directly (seen on the atr(5) < atr(20) volatility-contraction pattern).
    if "left" in operand and not ({"value", "price", "indicator"} & operand.keys()):
        return _normalize_operand(operand["left"])
    return operand


def _parse_dsl_rule(text: str) -> Any:
    """
    Deterministically parse a whole-rule DSL string like "rsi(14) < 30" or
    "close > sma(50)" into the structured {left, operator, right} dict that
    CustomStrategy expects. Only converts when the parse is unambiguous —
    exactly one operator, and both operands resolve to a known indicator,
    price column, or numeric literal. Anything else is returned unchanged so
    validate_ir reports it (as today).
    """
    s = _CROSS_ABOVE_RE.sub("cross_above", text)
    s = _CROSS_BELOW_RE.sub("cross_below", s)
    parts = _DSL_OP_RE.split(s.strip())
    if len(parts) != 3 or not parts[0].strip() or not parts[2].strip():
        return text
    left  = _normalize_operand(parts[0].strip())
    right = _normalize_operand(parts[2].strip())
    if isinstance(left, str) or isinstance(right, str):
        return text  # an operand didn't resolve — leave for validate_ir
    return {"left": left, "operator": parts[1].lower(), "right": right}


def _normalize_rule(rule: Any) -> Any:
    # Whole rule double-encoded as a JSON string — decode and normalize.
    if isinstance(rule, str):
        try:
            decoded = json.loads(rule)
        except (TypeError, ValueError):
            # Not JSON — try the "rsi(14) < 30" DSL-expression form instead.
            return _parse_dsl_rule(rule)
        if isinstance(decoded, dict):
            return _normalize_rule(decoded)
        return rule
    if not isinstance(rule, dict):
        return rule
    # "op" used instead of "operator" — another observed key-name variant.
    if "operator" not in rule and "op" in rule:
        rule["operator"] = rule.pop("op")
    for side in ("left", "right"):
        if side in rule:
            rule[side] = _normalize_operand(rule[side])
        # "left_output"/"right_output" sibling keys instead of "output" inside
        # the operand — same live-run drift as the string shorthand above.
        out_key = f"{side}_output"
        if out_key in rule:
            out_val = rule.pop(out_key)
            operand = rule.get(side)
            if isinstance(operand, dict) and "indicator" in operand and "output" not in operand and out_val:
                operand["output"] = out_val
    return rule


def _hoist_flat_custom_shape(ir: dict) -> dict:
    """
    Auto-fix for a recurring extraction-LLM drift: instead of
    {"strategy": "CUSTOM", "params": {"entry_rules": [...], ...}}, the model
    sometimes emits entry_rules/exit_rules as top-level siblings of a
    "params" dict that only holds the numeric fields (stop_loss_pct etc),
    often with extra invented keys (name/version/metadata/direction/
    long_short/instrument/...). Seen live even after prompt hardening and a
    repair-LLM retry both failed to correct it — this is exactly the kind of
    unambiguous, describable shape mistake this module already auto-fixes
    for rule operands, so it gets the same deterministic treatment rather
    than a third LLM call: if "strategy" is missing but entry_rules/exit_rules
    exist at the top level, it's unambiguously a mis-shaped CUSTOM strategy.
    """
    if "strategy" in ir:
        return ir
    if "entry_rules" not in ir and "exit_rules" not in ir:
        return ir
    existing_params = ir.get("params") if isinstance(ir.get("params"), dict) else {}
    merged_params = {
        "entry_rules": ir.get("entry_rules", []),
        "exit_rules":  ir.get("exit_rules", []),
        "logic": existing_params.get("logic", "AND"),
        **{k: v for k, v in existing_params.items() if k not in ("entry_rules", "exit_rules", "logic")},
    }
    return {"strategy": "CUSTOM", "params": merged_params}


def _fix_preset_name_with_custom_params(ir: dict) -> dict:
    """
    Auto-fix: only CUSTOM ever has entry_rules/exit_rules in its params (see
    strategies/custom.py) — no known preset (DONCHIAN, RSI, MACROSS, ...)
    takes those fields. Seen live: constraining "strategy" to a valid enum
    of registry names (to stop the model inventing names like "long_only")
    just moved the drift one level down — the model now sometimes picks a
    real preset name that happens to match the described indicator, but
    still fills params with rule-builder fields instead of that preset's
    actual schema. If params has entry_rules/exit_rules and strategy isn't
    already CUSTOM, the strategy name is unambiguously wrong — force it.
    """
    if ir.get("strategy") == "CUSTOM":
        return ir
    params = ir.get("params")
    if isinstance(params, dict) and ("entry_rules" in params or "exit_rules" in params):
        ir["strategy"] = "CUSTOM"
    return ir


def normalize_ir(ir: dict) -> dict:
    """Mutates and returns `ir`, auto-fixing unambiguous LLM shape mistakes
    (top-level structure, then per-rule operand shapes) before validate_ir()
    runs."""
    if not isinstance(ir, dict):
        return ir
    ir = _hoist_flat_custom_shape(ir)
    ir = _fix_preset_name_with_custom_params(ir)
    params = ir.get("params")
    if not isinstance(params, dict):
        return ir
    for key in ("entry_rules", "exit_rules"):
        rules = params.get(key)
        if isinstance(rules, list):
            params[key] = [_normalize_rule(r) for r in rules]
    return ir


def _validate_operand(operand: Any, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(operand, dict):
        errors.append(f"{path}: operand must be a dict, got {type(operand).__name__}")
        return errors

    keys = set(operand.keys())

    if "value" in keys:
        try:
            float(operand["value"])
        except (TypeError, ValueError):
            errors.append(f"{path}.value must be numeric, got {operand['value']!r}")

    elif "price" in keys:
        if operand["price"] not in _PRICE_COLS:
            errors.append(f"{path}.price must be one of {sorted(_PRICE_COLS)}, got {operand['price']!r}")

    elif "indicator" in keys:
        key = operand.get("indicator")
        if key not in CATALOG_BY_KEY:
            errors.append(f"{path}.indicator '{key}' not in INDICATOR_CATALOG. "
                          f"Valid keys: {sorted(CATALOG_BY_KEY)}")
        else:
            meta = CATALOG_BY_KEY[key]
            out = operand.get("output")
            if out and out not in meta["outputs"]:
                errors.append(f"{path}.output '{out}' not valid for '{key}'. "
                               f"Valid outputs: {meta['outputs']}")
            params = operand.get("params", {}) or {}
            if not isinstance(params, dict):
                errors.append(f"{path}.params must be a dict")
            else:
                # Unknown param keys were previously accepted silently and just
                # ignored by compute() — reel_pipeline_test_results_large.xlsx
                # (95-URL run) found an extracted IR with a bogus "timeframe"
                # param key that passed validation but silently produced a
                # duplicate/no-op rule instead of a clear error.
                allowed = {p["name"] for p in meta["params"]}
                for pk in params:
                    if pk not in allowed:
                        errors.append(
                            f"{path}.params has unknown key '{pk}' for indicator '{key}'. "
                            f"Valid params: {sorted(allowed)}"
                        )

    else:
        errors.append(f"{path}: operand must have 'value', 'price', or 'indicator' key")

    return errors


def _validate_rule(rule: Any, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(rule, dict):
        errors.append(f"{path}: rule must be a dict")
        return errors

    op = rule.get("operator")
    if op not in _OPERATORS:
        errors.append(f"{path}.operator '{op}' invalid. Allowed: {sorted(_OPERATORS)}")

    errors.extend(_validate_operand(rule.get("left"), f"{path}.left"))
    errors.extend(_validate_operand(rule.get("right"), f"{path}.right"))
    return errors


def validate_ir(ir: dict) -> list[str]:
    """
    Validate a Strategy IR. Returns a list of human-readable error strings.
    Empty list means the IR is valid and ready to run.
    """
    if not isinstance(ir, dict):
        return ["IR must be a JSON object (dict)"]

    errors: list[str] = []
    strategy = str(ir.get("strategy", "")).upper()

    if not strategy:
        errors.append("IR missing 'strategy' field")
        return errors

    if strategy not in STRATEGY_REGISTRY:
        errors.append(f"Unknown strategy '{strategy}'. Valid strategies: {sorted(STRATEGY_REGISTRY)}")
        return errors

    params = ir.get("params", {}) or {}
    if not isinstance(params, dict):
        errors.append("IR 'params' must be a JSON object (dict)")
        return errors

    if strategy == "CUSTOM":
        entry_rules = params.get("entry_rules", [])
        exit_rules  = params.get("exit_rules",  [])

        if not entry_rules:
            errors.append("CUSTOM strategy requires at least one entry rule")

        logic = str(params.get("logic", "AND")).upper()
        if logic not in ("AND", "OR"):
            errors.append(f"logic must be 'AND' or 'OR', got '{logic}'")

        for i, rule in enumerate(entry_rules or []):
            errors.extend(_validate_rule(rule, f"entry_rules[{i}]"))
        for i, rule in enumerate(exit_rules or []):
            errors.extend(_validate_rule(rule, f"exit_rules[{i}]"))

    elif strategy not in _CLASSIC:
        # Indicator preset — validate params against the strategy's own schema
        cls = STRATEGY_REGISTRY[strategy]
        schema = cls.param_schema()
        for k, v in params.items():
            if k not in schema:
                errors.append(f"Unknown param '{k}' for strategy '{strategy}'")

    return errors
