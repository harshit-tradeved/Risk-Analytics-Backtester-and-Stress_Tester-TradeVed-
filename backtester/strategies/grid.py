"""
Grid Strategy — buy when price drops to a lower grid level, sell when it rises.

Logic:
  1. Divide [lower_bound, upper_bound] into N equally spaced (or exponential) levels.
  2. On each candle, check if price crossed any level since the previous candle.
  3. A downward cross of level L triggers a BUY at level L.
  4. An upward cross of level L triggers a SELL at level L (only if we hold inventory).
  5. Quantity per trade = quantity_per_level (fixed).

Parameters:
  upper_bound      : float  — top of grid price range
  lower_bound      : float  — bottom of grid price range
  num_levels       : int    — number of grid levels (3–20)
  spacing          : str    — 'linear' or 'exponential'
  quantity_per_level : float — units to trade at each level crossing
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Param

logger = logging.getLogger(__name__)


class GridStrategy(BaseStrategy):
    """Grid strategy: buy dips and sell rallies within a defined price range."""

    CATEGORY = "classic"

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        return {
            "lower_bound":          Param("number", "Lower Bound", min=0, group="Bounds",
                                          help="Bottom of grid range (auto-detected if 0)."),
            "upper_bound":          Param("number", "Upper Bound", min=0, group="Bounds",
                                          help="Top of grid range (auto-detected if 0)."),
            "num_levels":           Param("number", "Grid Levels", min=2, max=50, step=1, group="Bounds"),
            "spacing":              Param("select", "Spacing", options=["linear", "exponential"], group="Bounds"),
            "invest_per_level_usd": Param("number", "Invest / Level (USD)", min=0, step=50, group="Sizing",
                                          help="Set 0 to use fixed units instead."),
            "quantity_per_level":   Param("number", "Units / Level", min=0, step=0.001, group="Sizing",
                                          depends_on={"field": "invest_per_level_usd", "value": 0}),
        }

    @staticmethod
    def default_params() -> dict[str, Any]:
        return {
            "upper_bound":          45_000.0,
            "lower_bound":          35_000.0,
            "num_levels":           5,
            "spacing":              "linear",   # 'linear' | 'exponential'
            # Dollar-based sizing (preferred) — set to 0 to use quantity_per_level instead
            "invest_per_level_usd": 500.0,      # USD to invest per grid level crossing
            # Fixed-unit fallback (only used when invest_per_level_usd == 0)
            "quantity_per_level":   0.001,
        }

    def _validate_params(self, params: dict):
        if params["lower_bound"] >= params["upper_bound"]:
            raise ValueError("lower_bound must be < upper_bound")
        if not (2 <= params["num_levels"] <= 50):
            raise ValueError("num_levels must be between 2 and 50")
        if params.get("invest_per_level_usd", 0) == 0 and params["quantity_per_level"] <= 0:
            raise ValueError("invest_per_level_usd or quantity_per_level must be positive")

    # ── Core signal generation ────────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        levels = self._build_levels()
        logger.info(
            "Grid levels (%s): %s",
            self.spacing,
            [round(l, 2) for l in levels],
        )

        signals  = ["HOLD"] * len(df)
        qtys     = [0.0]   * len(df)
        meta     = [{}]    * len(df)

        prev_price: float | None = None

        for i, row in df.iterrows():
            price = float(row["close"])

            if prev_price is None:
                prev_price = price
                continue

            signal, qty, triggered_levels = self._check_crossings(
                prev_price, price, levels, price
            )

            signals[i] = signal
            qtys[i]    = qty
            meta[i]    = {"triggered_levels": triggered_levels}

            prev_price = price

        df["signal"]   = signals
        df["quantity"] = qtys
        df["meta"]     = meta
        return df

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_levels(self) -> list[float]:
        if self.spacing == "exponential":
            log_low  = np.log(self.lower_bound)
            log_high = np.log(self.upper_bound)
            return list(np.exp(np.linspace(log_low, log_high, self.num_levels)))
        else:
            return list(np.linspace(self.lower_bound, self.upper_bound, self.num_levels))

    def _qty(self, price: float, count: int = 1) -> float:
        """Return quantity to trade: dollar-based if invest_per_level_usd > 0, else fixed units."""
        invest = getattr(self, "invest_per_level_usd", 0)
        if invest > 0 and price > 0:
            return invest * count / price
        return self.quantity_per_level * count

    def _check_crossings(
        self,
        prev:   float,
        curr:   float,
        levels: list[float],
        price:  float,
    ) -> tuple[str, float, list[float]]:
        """Detect level crossings and return aggregated signal."""
        buy_levels  = [l for l in levels if prev > l >= curr]   # price dropped through
        sell_levels = [l for l in levels if prev < l <= curr]   # price rose through

        if sell_levels:
            return "SELL", self._qty(price, len(sell_levels)), sell_levels
        if buy_levels:
            return "BUY",  self._qty(price, len(buy_levels)),  buy_levels
        return "HOLD", 0.0, []
