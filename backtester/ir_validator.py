"""
Deterministic IR (Intermediate Representation) validator.

Validates a Strategy IR dict against the live STRATEGY_REGISTRY and
INDICATOR_CATALOG before it is compiled into a backtest run. No LLM involved —
pure structural checks so errors are reported clearly to the user.

Exported:
    validate_ir(ir: dict) -> list[str]   — returns list of error strings (empty = valid)
"""
from __future__ import annotations

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

def _normalize_operand(operand: Any) -> Any:
    # Bare numeric literal instead of {"value": N}
    if isinstance(operand, (int, float)):
        return {"value": float(operand)}
    if not isinstance(operand, dict):
        return operand
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


def _normalize_rule(rule: Any) -> Any:
    if not isinstance(rule, dict):
        return rule
    if "left" in rule:
        rule["left"] = _normalize_operand(rule["left"])
    if "right" in rule:
        rule["right"] = _normalize_operand(rule["right"])
    return rule


def normalize_ir(ir: dict) -> dict:
    """Mutates and returns `ir`, auto-fixing unambiguous LLM operand-shape
    mistakes in CUSTOM entry_rules/exit_rules before validate_ir() runs."""
    if not isinstance(ir, dict):
        return ir
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
