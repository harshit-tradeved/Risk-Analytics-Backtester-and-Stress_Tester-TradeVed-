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
        return {
            "entry_rules":          Param("array",  "Entry Rules",          group="Rules"),
            "exit_rules":           Param("array",  "Exit Rules",           group="Rules"),
            "logic":                Param("select", "Combine With",         options=["AND", "OR"], group="Rules"),
            "invest_per_trade_usd": Param("number", "Invest / Trade (USD)", min=0,   step=50,    group="Sizing",
                                          help="Set 0 to use fixed units."),
            "quantity":             Param("number", "Units / Trade",        min=0,   step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_trade_usd", "value": 0}),
            "stop_loss_pct":        Param("number", "Stop Loss %",          min=0,   max=50,  step=0.5, group="Exit",
                                          help="Exit when price drops this % below entry. 0 = disabled."),
            "take_profit_pct":      Param("number", "Take Profit %",        min=0,   max=500, step=0.5, group="Exit",
                                          help="Exit when price rises this % above entry. 0 = disabled."),
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
            "stop_loss_pct": 0.0,
            "take_profit_pct": 0.0,
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
        entry_mask = self._combine(df, self.entry_rules)
        exit_mask  = self._combine(df, self.exit_rules or [])

        sl_pct = float(getattr(self, "stop_loss_pct",   0) or 0)
        tp_pct = float(getattr(self, "take_profit_pct", 0) or 0)

        if not sl_pct and not tp_pct:
            return signals_from_masks(df, entry_mask, exit_mask,
                                      invest_usd=getattr(self, "invest_per_trade_usd", 0),
                                      qty_fallback=getattr(self, "quantity", 0.01))

        # Custom signal loop: rule-based exit OR stop-loss OR take-profit
        invest_usd   = float(getattr(self, "invest_per_trade_usd", 0) or 0)
        qty_fallback = float(getattr(self, "quantity", 0.01) or 0.01)

        df_out = df.copy()
        close  = df_out["close"].astype(float).to_numpy()
        low    = df_out["low"].astype(float).to_numpy()
        high   = df_out["high"].astype(float).to_numpy()
        em     = entry_mask.fillna(False).to_numpy().astype(bool)
        xm     = exit_mask.fillna(False).to_numpy().astype(bool)
        n      = len(df_out)

        signals  = ["HOLD"] * n
        qtys     = [0.0]    * n
        meta     = [{}]     * n
        in_pos   = False
        held_qty = 0.0
        entry_px = 0.0

        for i in range(n):
            price = close[i]
            if not in_pos:
                if em[i]:
                    qty = (invest_usd / price) if (invest_usd > 0 and price > 0) else qty_fallback
                    if qty > 0:
                        signals[i]  = "BUY"
                        qtys[i]     = qty
                        meta[i]     = {"entry": True}
                        in_pos, held_qty, entry_px = True, qty, price
            else:
                # Check SL on bar low (can be hit intrabar), TP on bar high
                sl_hit = sl_pct > 0 and low[i]  <= entry_px * (1 - sl_pct / 100)
                tp_hit = tp_pct > 0 and high[i] >= entry_px * (1 + tp_pct / 100)
                rule_exit = xm[i]

                if sl_hit or tp_hit or rule_exit:
                    exit_price = (entry_px * (1 - sl_pct / 100) if sl_hit else
                                  entry_px * (1 + tp_pct / 100) if tp_hit else price)
                    signals[i] = "SELL"
                    qtys[i]    = held_qty
                    meta[i]    = {
                        "exit": True,
                        "exit_reason": "stop_loss" if sl_hit else "take_profit" if tp_hit else "rule",
                        "pnl_pct": round((exit_price - entry_px) / entry_px * 100, 2) if entry_px else 0.0,
                    }
                    in_pos, held_qty, entry_px = False, 0.0, 0.0

        df_out["signal"]   = signals
        df_out["quantity"] = qtys
        df_out["meta"]     = meta
        return df_out
