"""
DCA Strategy — Dollar-Cost Averaging.

Logic:
  1. Every `buy_interval_hours` hours, BUY `buy_quantity` units.
  2. After accumulating for `hold_days`, SELL the entire position.
  3. Repeat until data ends.

Parameters:
  buy_interval_hours : int   — hours between each automated buy (default 24 = daily)
  buy_quantity       : float — units to buy at each interval
  hold_days          : int   — total holding period before selling (cycles)
  exit_type          : str   — 'time' (sell after hold_days) or 'profit' (sell at profit_target)
  profit_target_pct  : float — profit % to trigger exit when exit_type='profit'
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backtesting.strategies.base import BaseStrategy, Param

logger = logging.getLogger(__name__)


class DCAStrategy(BaseStrategy):
    """DCA strategy: regular interval buys with time-based or profit-target exit."""

    CATEGORY = "classic"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "buy_interval_hours": Param("number", "Buy Interval (hours)", min=1, step=1, group="Schedule"),
            "invest_per_buy_usd": Param("number", "Invest / Buy (USD)", min=0, step=50, group="Sizing",
                                        help="Set 0 to use fixed units instead."),
            "buy_quantity":       Param("number", "Units / Buy", min=0, step=0.001, group="Sizing",
                                        depends_on={"field": "invest_per_buy_usd", "value": 0}),
            "hold_days":          Param("number", "Hold Days", min=1, step=1, group="Schedule"),
            "exit_type":          Param("select", "Exit Type", options=["time", "profit"], group="Exit"),
            "profit_target_pct":  Param("number", "Profit Target %", min=0.1, step=0.5, group="Exit",
                                        depends_on={"field": "exit_type", "value": "profit"}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "buy_interval_hours":  24,
            # Dollar-based (preferred): invest this many USD per scheduled buy
            "invest_per_buy_usd":  200.0,
            # Fixed-unit fallback (used only when invest_per_buy_usd == 0)
            "buy_quantity":        0.001,
            "hold_days":           30,
            "exit_type":           "time",     # 'time' | 'profit'
            "profit_target_pct":   10.0,
        }

    def _validate_params(self, params: dict):
        if params["buy_interval_hours"] <= 0:
            raise ValueError("buy_interval_hours must be > 0")
        if params.get("invest_per_buy_usd", 0) == 0 and params.get("buy_quantity", 0) <= 0:
            raise ValueError("invest_per_buy_usd or buy_quantity must be positive")
        if params["hold_days"] <= 0:
            raise ValueError("hold_days must be > 0")

    # ── Core signal generation ────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        n = len(df)
        signals  = ["HOLD"] * n
        qtys     = [0.0]   * n
        meta     = [{}]    * n

        # Determine buy interval in candle-steps
        # Infer candle granularity from median time diff
        if n > 1:
            diffs = df["timestamp"].diff().dropna()
            median_hours = diffs.median().total_seconds() / 3600
        else:
            median_hours = 24.0

        buy_every_n = max(1, round(self.buy_interval_hours / median_hours))
        hold_candles = max(1, round(self.hold_days * 24 / median_hours))

        position_open = False
        position_start_idx = 0
        avg_entry_price = 0.0
        accumulated_qty = 0.0

        i = 0
        while i < n:
            # ── BUY phase: accumulate ─────────────────────────────────────
            phase_end = min(i + hold_candles, n)
            buy_count = 0

            for j in range(i, phase_end):
                candle_offset = j - i
                if candle_offset % buy_every_n == 0:
                    price = float(df.iloc[j]["close"])
                    invest = getattr(self, "invest_per_buy_usd", 0)
                    qty = (invest / price) if (invest > 0 and price > 0) else self.buy_quantity
                    signals[j]  = "BUY"
                    qtys[j]     = qty
                    meta[j]     = {"dca_buy_count": buy_count + 1}

                    # Track running average
                    total_cost   = avg_entry_price * accumulated_qty + price * qty
                    accumulated_qty += qty
                    avg_entry_price  = total_cost / accumulated_qty if accumulated_qty > 0 else price
                    buy_count += 1

            # ── SELL phase: exit one candle AFTER the hold window ────────
            # Using phase_end (not phase_end-1) guarantees the sell candle is
            # strictly after all buy candles, preventing the SELL signal from
            # overwriting the last BUY signal when hold_candles == 1.
            sell_idx = min(phase_end, n - 1)
            if accumulated_qty > 0:
                price = float(df.iloc[sell_idx]["close"])

                if self.exit_type == "profit":
                    # Scan for profit target within the hold window
                    for k in range(i, min(phase_end + 1, n)):
                        p = float(df.iloc[k]["close"])
                        if avg_entry_price > 0 and (p - avg_entry_price) / avg_entry_price * 100 >= self.profit_target_pct:
                            sell_idx = k
                            price    = p
                            break

                signals[sell_idx]  = "SELL"
                qtys[sell_idx]     = accumulated_qty
                meta[sell_idx]     = {
                    "dca_sell": True,
                    "avg_entry": round(avg_entry_price, 4),
                    "qty_sold":  round(accumulated_qty, 6),
                    "pnl_pct":   round((price - avg_entry_price) / avg_entry_price * 100, 2)
                                 if avg_entry_price > 0 else 0,
                }

                # Reset for next cycle
                avg_entry_price = 0.0
                accumulated_qty = 0.0

            # Advance past the sell candle so next cycle's buys don't collide
            i = sell_idx + 1

        df["signal"]   = signals
        df["quantity"] = qtys
        df["meta"]     = meta

        total_buys  = sum(1 for s in signals if s == "BUY")
        total_sells = sum(1 for s in signals if s == "SELL")
        logger.info("DCA signals — buys: %d | sells: %d", total_buys, total_sells)
        return df
