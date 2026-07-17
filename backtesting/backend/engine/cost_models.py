"""
Transaction Cost Models for the TradeVed Backtester.

Two models:
  1. SimpleCostModel   — percentage fee (existing crypto-style)
  2. IndianCostModel   — precise Indian market charges (STT, exchange, GST, stamp)

All rates as per SEBI / Finance Ministry circulars effective from Budget 2024
(1 October 2024 onwards).

Reference:
  STT Budget 2024 changes: https://www.sebi.gov.in
  NSE Circular: NSCCL/CMPT/56264/2024
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

MarketType      = Literal["equity_delivery", "equity_intraday", "futures", "options"]
BrokerageModel  = Literal["flat", "percentage", "zero"]


# ─────────────────────────────────────────────────────────────────────────────
# Cost breakdown dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CostBreakdown:
    """Itemised cost breakdown for a single trade leg (all in ₹)."""
    brokerage:        float = 0.0
    stt:              float = 0.0   # Securities Transaction Tax
    exchange_charges: float = 0.0   # NSE/BSE transaction charges
    sebi_charges:     float = 0.0   # SEBI regulatory fee
    gst:              float = 0.0   # 18% on brokerage + exchange + SEBI
    stamp_duty:       float = 0.0   # State stamp duty (Maharashtra)
    total:            float = 0.0

    def as_dict(self) -> dict:
        return {k: round(v, 4) for k, v in asdict(self).items()}


# ─────────────────────────────────────────────────────────────────────────────
# Simple percentage cost model (existing behaviour — crypto + generic equity)
# ─────────────────────────────────────────────────────────────────────────────

class SimpleCostModel:
    """
    Flat percentage fee per trade leg.  Works for crypto and as a fallback.
    """
    def __init__(self, fee_pct: float = 0.001):
        self.fee_pct = fee_pct

    def calculate(self, turnover: float, side: str) -> float:
        """Returns total cost (₹ / $) for one trade leg."""
        return round(turnover * self.fee_pct, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Indian market cost model
# ─────────────────────────────────────────────────────────────────────────────

class IndianCostModel:
    """
    Precise Indian market transaction cost calculator.

    Applies to NSE / BSE equity and derivatives trades.

    ┌──────────────────────────────────────────────────────────────────────────┐
    │ Component               Equity Delivery  Intraday   Futures   Options   │
    ├──────────────────────────────────────────────────────────────────────────┤
    │ STT — Buy               0.1%             0%         0%        0%        │
    │ STT — Sell              0.1%             0.025%     0.02%     0.1%      │
    │ Exchange charges (NSE)  0.00297%         0.00297%   0.00173%  0.03503%  │
    │ SEBI charges            0.0001%          0.0001%    0.0001%   0.0001%   │
    │ GST (on brok+exch+SEBI) 18%              18%        18%       18%       │
    │ Stamp — Buy             0.015%           0.003%     0.003%    0.003%    │
    └──────────────────────────────────────────────────────────────────────────┘

    Brokerage presets:
      flat         ₹20/order (Zerodha / Groww / Upstox)
      percentage   % of turnover (legacy full-service brokers)
      zero         ₹0 brokerage (Angel One free delivery)
    """

    # ── STT rates (Budget 2024, effective 1 Oct 2024) ─────────────────────────
    _STT_RATES = {
        "equity_delivery_buy":  0.001,     # 0.1% on turnover
        "equity_delivery_sell": 0.001,     # 0.1% on turnover
        "equity_intraday_sell": 0.00025,   # 0.025% on turnover
        "futures_sell":         0.0002,    # 0.02% on turnover  (raised from 0.01%)
        "options_sell":         0.001,     # 0.1% on premium    (raised from 0.0625%)
    }

    # ── NSE Exchange Transaction Charges ─────────────────────────────────────
    # (as of NSE circular 2024, on total turnover)
    _ETC = {
        "equity":  0.0000297,   # ₹2.97 per lakh  = 0.00297%
        "futures": 0.0000173,   # ₹1.73 per lakh  = 0.00173%
        "options": 0.0003503,   # ₹35.03 per lakh = 0.03503% (on premium)
    }

    # ── SEBI charges ──────────────────────────────────────────────────────────
    _SEBI = 0.000001    # ₹10 per crore = 0.0001%

    # ── GST on regulatory charges ─────────────────────────────────────────────
    _GST = 0.18          # 18%

    # ── Stamp duty (Maharashtra / NSE) ───────────────────────────────────────
    _STAMP = {
        "equity_delivery": 0.00015,   # 0.015%
        "equity_intraday": 0.00003,   # 0.003%
        "futures":         0.00003,   # 0.003%
        "options":         0.00003,   # 0.003%
    }

    def calculate(
        self,
        turnover:        float,                    # trade value in ₹
        side:            str,                      # 'BUY' or 'SELL'
        market_type:     MarketType = "equity_delivery",
        brokerage_model: BrokerageModel = "flat",
        brokerage_flat:  float = 20.0,             # ₹ per order
        brokerage_pct:   float = 0.005,            # 0.5% for traditional brokers
    ) -> CostBreakdown:
        """
        Calculate itemised transaction cost for a single trade leg.

        Args:
            turnover:        Trade value (price × qty), in ₹
            side:            'BUY' or 'SELL'
            market_type:     See MarketType literals above
            brokerage_model: How brokerage is charged
            brokerage_flat:  ₹ amount for flat-fee brokers
            brokerage_pct:   % rate for percentage-fee brokers

        Returns:
            CostBreakdown with itemised costs and a .total
        """
        cb = CostBreakdown()
        if turnover <= 0:
            return cb

        # ── 1. Brokerage ─────────────────────────────────────────────────────
        if brokerage_model == "flat":
            if market_type == "equity_delivery":
                # Zerodha: 0.1% or ₹20 whichever is lower (delivery)
                cb.brokerage = min(brokerage_flat, turnover * 0.001)
            else:
                # Intraday / F&O: flat per order, capped at 2.5% (SEBI rule)
                cb.brokerage = min(brokerage_flat, turnover * 0.025)
        elif brokerage_model == "percentage":
            cb.brokerage = turnover * brokerage_pct
        elif brokerage_model == "zero":
            cb.brokerage = 0.0

        # ── 2. STT ───────────────────────────────────────────────────────────
        key = f"{market_type}_{side.lower()}"
        cb.stt = turnover * self._STT_RATES.get(key, 0.0)

        # ── 3. Exchange transaction charges ──────────────────────────────────
        if market_type in ("equity_delivery", "equity_intraday"):
            cb.exchange_charges = turnover * self._ETC["equity"]
        elif market_type == "futures":
            cb.exchange_charges = turnover * self._ETC["futures"]
        else:  # options
            cb.exchange_charges = turnover * self._ETC["options"]

        # ── 4. SEBI charges ──────────────────────────────────────────────────
        cb.sebi_charges = turnover * self._SEBI

        # ── 5. GST on (brokerage + exchange charges + SEBI) ──────────────────
        cb.gst = (cb.brokerage + cb.exchange_charges + cb.sebi_charges) * self._GST

        # ── 6. Stamp duty (buy side only) ────────────────────────────────────
        if side.upper() == "BUY":
            cb.stamp_duty = turnover * self._STAMP.get(market_type, 0.0)

        cb.total = (
            cb.brokerage
            + cb.stt
            + cb.exchange_charges
            + cb.sebi_charges
            + cb.gst
            + cb.stamp_duty
        )
        return cb

    def effective_pct(
        self,
        market_type:     MarketType = "equity_delivery",
        brokerage_model: BrokerageModel = "flat",
        brokerage_flat:  float = 20.0,
        sample_turnover: float = 100_000.0,   # ₹1 lakh — representative trade
    ) -> float:
        """
        Round-trip effective cost as a percentage of turnover.
        Useful for displaying to users ("total cost ≈ X% per round trip").
        """
        buy  = self.calculate(sample_turnover, "BUY",  market_type, brokerage_model, brokerage_flat)
        sell = self.calculate(sample_turnover, "SELL", market_type, brokerage_model, brokerage_flat)
        return round((buy.total + sell.total) / sample_turnover * 100, 3)


# ── Aggregate cost breakdown summary ─────────────────────────────────────────

def aggregate_cost_breakdown(breakdowns: list[CostBreakdown]) -> dict:
    """Sum up a list of per-trade CostBreakdown objects into totals."""
    totals = CostBreakdown()
    for cb in breakdowns:
        totals.brokerage        += cb.brokerage
        totals.stt              += cb.stt
        totals.exchange_charges += cb.exchange_charges
        totals.sebi_charges     += cb.sebi_charges
        totals.gst              += cb.gst
        totals.stamp_duty       += cb.stamp_duty
        totals.total            += cb.total
    return totals.as_dict()
