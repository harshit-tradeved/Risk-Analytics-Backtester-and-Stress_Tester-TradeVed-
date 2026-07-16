"""
PLA Strategy — Price-Level Averaging with EMA crossover.

Logic:
  1. Compute fast EMA and slow EMA on closing prices.
  2. When fast EMA crosses ABOVE slow EMA → enter LONG position:
       - Buy entry_quantities[0] immediately (level 1)
       - Buy entry_quantities[1] if price dips to entry_levels[1] below entry (level 2)
       - … (cascading entries average down)
  3. When fast EMA crosses BELOW slow EMA → EXIT entire position.
  4. Alternatively exit on stop_loss_pct or take_profit_pct.

Parameters:
  fast_ema          : int   — fast EMA period (default 12)
  slow_ema          : int   — slow EMA period (default 26)
  entry_levels      : list  — price-drop percentages for cascading entries [0, -1, -2, -3]
  entry_quantities  : list  — quantity to buy at each level [0.001, 0.001, 0.002, 0.003]
  exit_type         : str   — 'crossover' | 'take_profit' | 'stop_loss'
  take_profit_pct   : float — TP % above average entry
  stop_loss_pct     : float — SL % below average entry
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backtesting.strategies.base import BaseStrategy, Param

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


class PLAStrategy(BaseStrategy):
    """PLA strategy: EMA crossover entries with cascading position averaging."""

    CATEGORY = "classic"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "fast_ema":             Param("number", "Fast EMA", min=2, max=200, step=1, group="Signal"),
            "slow_ema":             Param("number", "Slow EMA", min=3, max=400, step=1, group="Signal"),
            "entry_levels":         Param("array", "Entry Levels (% drop)", group="Entries",
                                          help="Price-drop %% from signal for each cascading buy."),
            "invest_per_level_usd": Param("array", "Invest / Level (USD)", group="Sizing"),
            "entry_quantities":     Param("array", "Units / Level", group="Sizing"),
            "exit_type":            Param("select", "Exit Type",
                                          options=["crossover", "take_profit", "stop_loss"], group="Exit"),
            "take_profit_pct":      Param("number", "Take Profit %", min=0.1, step=0.5, group="Exit",
                                          depends_on={"field": "exit_type", "value": "take_profit"}),
            "stop_loss_pct":        Param("number", "Stop Loss %", min=0.1, step=0.5, group="Exit",
                                          depends_on={"field": "exit_type", "value": "stop_loss"}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "fast_ema":    12,
            "slow_ema":    26,
            # entry_levels: % drop from signal price to trigger each cascading buy
            "entry_levels": [0.0, -1.0, -2.5, -4.0],
            # Dollar-based sizing (preferred) — USD to invest at each cascading level
            "invest_per_level_usd": [300.0, 300.0, 600.0, 900.0],
            # Fixed-unit fallback (used when invest_per_level_usd is empty or all zeros)
            "entry_quantities": [0.001, 0.001, 0.002, 0.003],
            "exit_type":        "crossover",
            "take_profit_pct":  5.0,
            "stop_loss_pct":    3.0,
        }

    def _validate_params(self, params: dict):
        if params["fast_ema"] >= params["slow_ema"]:
            raise ValueError("fast_ema must be < slow_ema")
        if len(params["entry_levels"]) != len(params.get("entry_quantities", params.get("invest_per_level_usd", []))):
            pass  # allow mismatch; _qty will handle it

    def _qty(self, price: float, level_idx: int) -> float:
        """Return quantity for the given level, preferring dollar-based sizing."""
        invest_list = getattr(self, "invest_per_level_usd", [])
        # Scalar invest_per_level_usd (user passed a single number) → treat as uniform per level
        if isinstance(invest_list, (int, float)):
            invest_list = [float(invest_list)] * max(len(getattr(self, "entry_levels", [0])), 1)
        if invest_list and level_idx < len(invest_list) and invest_list[level_idx] > 0 and price > 0:
            return invest_list[level_idx] / price
        qty_list = getattr(self, "entry_quantities", [0.001])
        return qty_list[level_idx] if level_idx < len(qty_list) else qty_list[-1]

    # ── Core signal generation ────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema_fast"] = _ema(df["close"], self.fast_ema)
        df["ema_slow"] = _ema(df["close"], self.slow_ema)
        df["ema_diff"] = df["ema_fast"] - df["ema_slow"]

        n = len(df)
        signals  = ["HOLD"] * n
        qtys     = [0.0]   * n
        meta     = [{}]    * n

        in_position    = False
        entry_price    = 0.0     # price at crossover (level 0)
        avg_entry      = 0.0
        total_qty      = 0.0
        levels_filled  = set()   # which cascading levels have been bought

        for i in range(1, n):
            prev_diff = df.iloc[i - 1]["ema_diff"]
            curr_diff = df.iloc[i]["ema_diff"]
            price     = float(df.iloc[i]["close"])

            # ── Entry: fast crosses above slow ──────────────────────────────
            if not in_position and prev_diff <= 0 and curr_diff > 0:
                # Level 0 entry
                qty0       = self._qty(price, 0)
                signals[i] = "BUY"
                qtys[i]    = qty0
                meta[i]    = {"pla_level": 0, "ema_cross": "golden"}

                in_position   = True
                entry_price   = price
                avg_entry     = price
                total_qty     = qty0
                levels_filled = {0}
                continue

            # ── Cascading entries (averaging down) ───────────────────────────
            if in_position:
                for lvl_idx, (pct, qty) in enumerate(
                    zip(self.entry_levels[1:], [self._qty(price, i+1) for i in range(len(self.entry_levels)-1)]),
                    start=1,
                ):
                    if lvl_idx in levels_filled:
                        continue
                    target_price = entry_price * (1 + pct / 100)
                    if price <= target_price:
                        # New avg entry
                        new_cost   = avg_entry * total_qty + price * qty
                        total_qty += qty
                        avg_entry  = new_cost / total_qty

                        # Only one level per candle (pick the deepest triggered)
                        if signals[i] != "BUY":
                            signals[i] = "BUY"
                            qtys[i]    = qty
                            meta[i]    = {"pla_level": lvl_idx, "avg_entry": round(avg_entry, 4)}
                        else:
                            qtys[i] += qty
                            meta[i]["pla_level"] = lvl_idx

                        levels_filled.add(lvl_idx)

            # ── Exit conditions ───────────────────────────────────────────────
            if in_position:
                exit_triggered = False
                exit_reason    = ""

                if self.exit_type == "crossover" and prev_diff >= 0 and curr_diff < 0:
                    exit_triggered = True
                    exit_reason    = "death_cross"

                elif self.exit_type == "take_profit" and avg_entry > 0:
                    if (price - avg_entry) / avg_entry * 100 >= self.take_profit_pct:
                        exit_triggered = True
                        exit_reason    = "take_profit"

                elif self.exit_type == "stop_loss" and avg_entry > 0:
                    if (avg_entry - price) / avg_entry * 100 >= self.stop_loss_pct:
                        exit_triggered = True
                        exit_reason    = "stop_loss"

                # Crossover exit always overrides cascading entry on same candle
                if exit_triggered:
                    signals[i] = "SELL"
                    qtys[i]    = total_qty
                    meta[i]    = {
                        "pla_exit":  exit_reason,
                        "avg_entry": round(avg_entry, 4),
                        "qty_sold":  round(total_qty, 6),
                        "pnl_pct":   round((price - avg_entry) / avg_entry * 100, 2)
                                     if avg_entry > 0 else 0.0,
                    }
                    in_position   = False
                    entry_price   = 0.0
                    avg_entry     = 0.0
                    total_qty     = 0.0
                    levels_filled = set()

        df["signal"]   = signals
        df["quantity"] = qtys
        df["meta"]     = meta

        buys     = sum(1 for s in signals if s == "BUY")
        sells    = sum(1 for s in signals if s == "SELL")
        lvl0     = sum(1 for m in meta if isinstance(m, dict) and m.get("pla_level") == 0)
        cascades = sum(1 for m in meta if isinstance(m, dict) and m.get("pla_level", 0) > 0)
        logger.info(
            "PLA signals — buys: %d (L0 entries: %d, cascades: %d) | sells: %d | "
            "entry_levels: %s | invest_per_level: %s",
            buys, lvl0, cascades, sells,
            self.entry_levels,
            getattr(self, "invest_per_level_usd", "n/a"),
        )
        if cascades == 0 and lvl0 > 0:
            logger.warning(
                "PLA: 0 cascading entries triggered. "
                "Likely causes: (1) price never dipped %.1f%%/%.1f%%/%.1f%% after any golden cross "
                "on this timeframe; (2) invest_per_level_usd is so small each cascade "
                "rounds to 0 units after lot-size flooring.",
                abs(self.entry_levels[1]) if len(self.entry_levels) > 1 else 0,
                abs(self.entry_levels[2]) if len(self.entry_levels) > 2 else 0,
                abs(self.entry_levels[3]) if len(self.entry_levels) > 3 else 0,
            )
        return df
