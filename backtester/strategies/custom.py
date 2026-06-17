"""
Custom Strategy — user-composed rule builder.

A generic strategy whose entry/exit logic is defined by lists of conditions
over the indicator engine, combined with AND/OR. This is the backend for the
frontend RuleBuilder: "strategies we can create".

Rule shape (JSON-friendly):
    {
      "left":  {"indicator": "rsi", "params": {"length": 14}, "output": "rsi"},
      "operator": "<",                       # > >= < <= cross_above cross_below
      "right": {"value": 30}                 # OR {"indicator": ..., "params": ..., "output": ...}
    }
    # `left` may also be {"price": "close"} to reference a raw OHLCV column.

Parameters:
  entry_rules : list[rule]  — conditions that, when satisfied, open a long.
  exit_rules  : list[rule]  — conditions that, when satisfied, close the long.
  logic       : 'AND' | 'OR' — how to combine multiple rules within entry/exit.
  invest_per_trade_usd : USD per entry (0 → fixed units)
  quantity    : fixed units fallback
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from engine.indicators import compute, CATALOG_BY_KEY
from strategies.base import BaseStrategy, Param, signals_from_masks

_PRICE_COLS = ("open", "high", "low", "close", "volume")
_OPERATORS = (">", ">=", "<", "<=", "cross_above", "cross_below")


class CustomStrategy(BaseStrategy):
    """User-composed rules over the indicator engine (AND/OR of conditions)."""

    CATEGORY = "custom"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        # Rules are edited by the dedicated RuleBuilder UI, not the generic form,
        # so they are typed as 'array' (hidden from the simple form renderer).
        return {
            "entry_rules":          Param("array", "Entry Rules", group="Rules"),
            "exit_rules":           Param("array", "Exit Rules", group="Rules"),
            "logic":                Param("select", "Combine With", options=["AND", "OR"], group="Rules"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "entry_rules": [
                {"left": {"indicator": "rsi", "params": {"length": 14}, "output": "rsi"},
                 "operator": "<", "right": {"value": 30}},
            ],
            "exit_rules": [
                {"left": {"indicator": "rsi", "params": {"length": 14}, "output": "rsi"},
                 "operator": ">", "right": {"value": 70}},
            ],
            "logic": "AND",
            "invest_per_trade_usd": 1000.0,
            "quantity": 0.01,
        }

    def _validate_params(self, params: dict):
        if not params.get("entry_rules"):
            raise ValueError("CustomStrategy requires at least one entry rule")
        if str(params.get("logic", "AND")).upper() not in ("AND", "OR"):
            raise ValueError("logic must be 'AND' or 'OR'")
        for grp in ("entry_rules", "exit_rules"):
            for rule in params.get(grp, []) or []:
                op = rule.get("operator")
                if op not in _OPERATORS:
                    raise ValueError(f"Unknown operator '{op}'. Allowed: {_OPERATORS}")

    # ── Operand / rule evaluation ───────────────────────────────────────────

    def _resolve(self, df: pd.DataFrame, operand: dict) -> pd.Series | float:
        """Resolve a rule operand to a Series (indicator/price) or a scalar."""
        if operand is None:
            raise ValueError("rule operand is missing")
        if "value" in operand:
            return float(operand["value"])
        if "price" in operand:
            col = operand["price"]
            if col not in _PRICE_COLS:
                raise ValueError(f"Unknown price column '{col}'")
            return df[col].astype(float)
        if "indicator" in operand:
            key = operand["indicator"]
            meta = CATALOG_BY_KEY.get(key)
            if meta is None:
                raise ValueError(f"Unknown indicator '{key}'")
            params = operand.get("params", {}) or {}
            out = compute(df, key, **params)
            col = operand.get("output") or meta["outputs"][0]
            if col not in out.columns:
                raise ValueError(f"Indicator '{key}' has no output '{col}'")
            return out[col]
        raise ValueError(f"Invalid operand: {operand}")

    def _eval_rule(self, df: pd.DataFrame, rule: dict) -> pd.Series:
        left = self._resolve(df, rule.get("left"))
        right = self._resolve(df, rule.get("right"))
        op = rule["operator"]

        left_s = left if isinstance(left, pd.Series) else pd.Series(left, index=df.index)
        right_s = right if isinstance(right, pd.Series) else pd.Series(right, index=df.index)

        if op == ">":
            return left_s > right_s
        if op == ">=":
            return left_s >= right_s
        if op == "<":
            return left_s < right_s
        if op == "<=":
            return left_s <= right_s
        if op == "cross_above":
            return (left_s.shift(1) <= right_s.shift(1)) & (left_s > right_s)
        if op == "cross_below":
            return (left_s.shift(1) >= right_s.shift(1)) & (left_s < right_s)
        raise ValueError(f"Unknown operator '{op}'")

    def _combine(self, df: pd.DataFrame, rules: list[dict]) -> pd.Series:
        if not rules:
            return pd.Series(False, index=df.index)
        masks = [self._eval_rule(df, r).fillna(False) for r in rules]
        combined = masks[0]
        use_or = str(self.logic).upper() == "OR"
        for m in masks[1:]:
            combined = (combined | m) if use_or else (combined & m)
        return combined

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        entry = self._combine(df, self.entry_rules)
        exit_ = self._combine(df, self.exit_rules or [])
        return signals_from_masks(df, entry, exit_,
                                  invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                  qty_fallback=getattr(self, "quantity", 0.01))
