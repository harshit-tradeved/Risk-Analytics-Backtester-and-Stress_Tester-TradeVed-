"""
Trade Simulator — processes BUY/SELL/HOLD signals from any strategy and
simulates realistic execution with fees, slippage, and partial fills.

Position accounting uses weighted-average cost basis (WACB).
Equity curve is updated after every candle.

Cost models:
  SimpleCostModel   — flat % fee per trade leg (crypto / generic)
  IndianCostModel   — itemised STT + exchange charges + GST + stamp duty

Lot-size enforcement:
  For F&O, quantities are rounded DOWN to the nearest lot (e.g., lot_size=50
  means you can only buy 50 / 100 / 150 units, not 73).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from config import DEFAULT_FEE_PERCENT, DEFAULT_SLIPPAGE_PERCENT
from engine.cost_models import (
    IndianCostModel, SimpleCostModel, CostBreakdown, aggregate_cost_breakdown
)

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Position:
    symbol:      str
    quantity:    float
    avg_price:   float
    entry_time:  datetime
    entry_price: float      # price at first fill (not average)
    buy_fees:    float = 0.0  # accumulated entry-side costs, prorated into trade PnL on exit

    @property
    def total_cost(self) -> float:
        return self.quantity * self.avg_price


@dataclass
class TradeRecord:
    entry_time:  datetime
    entry_price: float
    exit_time:   datetime
    exit_price:  float
    quantity:    float
    pnl:         float
    pnl_pct:     float
    fees:        float
    side:        str = "LONG"

    def to_dict(self) -> dict:
        return {
            "entry_time":  (self.entry_time.isoformat()
                            if hasattr(self.entry_time, "isoformat")
                            else str(self.entry_time)),
            "entry_price": round(self.entry_price, 6),
            "exit_time":   (self.exit_time.isoformat()
                            if hasattr(self.exit_time, "isoformat")
                            else str(self.exit_time)),
            "exit_price":  round(self.exit_price,  6),
            "quantity":    round(self.quantity,    6),
            "pnl":         round(self.pnl,         4),
            "pnl_pct":     round(self.pnl_pct,     4),
            "fees":        round(self.fees,         4),
            "side":        self.side,
        }


# ── Simulator ─────────────────────────────────────────────────────────────────

class TradeSimulator:
    """
    Simulates trade execution from a DataFrame of signals.

    Args:
        symbol:            Asset symbol (for logging)
        capital:           Initial cash
        fee_percent:       Legacy % fee per leg (used when use_indian_costs=False)
        slippage_percent:  Market-impact slippage (applied as price adjustment)
        use_indian_costs:  If True, use IndianCostModel instead of fee_percent
        market_type:       'equity_delivery' | 'equity_intraday' | 'futures' | 'options'
        brokerage_model:   'flat' | 'percentage' | 'zero'
        brokerage_flat:    ₹ per order for flat brokerage (default 20 = Zerodha)
        brokerage_pct:     % of turnover for percentage brokerage
        lot_size:          F&O lot size (1 = equity, ≥2 = futures/options)

    Usage:
        # Crypto / US stocks:
        sim = TradeSimulator("BTC/USDT", capital=10_000)
        results = sim.run(signals_df)

        # Indian equity delivery (Zerodha):
        sim = TradeSimulator(
            "RELIANCE.NS", capital=500_000,
            use_indian_costs=True, market_type="equity_delivery",
            brokerage_model="flat", brokerage_flat=20,
        )
        results = sim.run(signals_df)
    """

    def __init__(
        self,
        symbol:            str   = "BTC/USDT",
        capital:           float = 10_000.0,
        fee_percent:       float = DEFAULT_FEE_PERCENT,
        slippage_percent:  float = DEFAULT_SLIPPAGE_PERCENT,
        # Indian market options
        use_indian_costs:  bool  = False,
        market_type:       str   = "equity_delivery",
        brokerage_model:   str   = "flat",
        brokerage_flat:    float = 20.0,
        brokerage_pct:     float = 0.005,
        lot_size:          int   = 1,
    ):
        self.symbol           = symbol
        self.initial_capital  = capital
        self.fee_percent      = fee_percent
        self.slippage_percent = slippage_percent
        self.use_indian_costs = use_indian_costs
        self.market_type      = market_type
        self.brokerage_model  = brokerage_model
        self.brokerage_flat   = brokerage_flat
        self.brokerage_pct    = brokerage_pct
        self.lot_size         = max(1, int(lot_size))

        # Cost model instances
        self._indian_calc = IndianCostModel() if use_indian_costs else None
        self._simple_calc = SimpleCostModel(fee_percent)

        self._reset()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> dict:
        """
        Iterate over every row in df and process BUY/SELL/HOLD signals.

        df must have columns: timestamp, close, signal, quantity
        Returns a results dict consumed by the metrics engine.
        """
        self._reset()

        for _, row in df.iterrows():
            ts    = row["timestamp"]
            price = float(row["close"])
            sig   = row.get("signal", "HOLD")
            qty   = float(row.get("quantity", 0))

            # Enforce lot-size rounding for F&O
            if self.lot_size > 1 and qty > 0:
                qty = math.floor(qty / self.lot_size) * self.lot_size
                if qty <= 0:
                    # Sub-lot SELL while holding ≥1 lot: trade the minimum lot
                    # instead of silently stranding the position until force-close.
                    if sig == "SELL" and self._position and self._position.quantity >= self.lot_size:
                        qty = float(self.lot_size)
                    else:
                        # Requested quantity is below the minimum lot size — track and skip
                        if sig == "BUY":
                            self._lot_size_skips += 1
                        self._equity_curve.append(self._mark_equity(price))
                        self._timestamps.append(ts)
                        continue

            if sig == "BUY" and qty > 0:
                self._execute_buy(price, qty, ts)
            elif sig == "SELL" and qty > 0:
                self._execute_sell(price, qty, ts)

            self._equity_curve.append(self._mark_equity(price))
            self._timestamps.append(ts)

        # Close any open positions at the last candle's close price
        if self._position and len(df):
            last_row = df.iloc[-1]
            self._execute_sell(
                float(last_row["close"]),
                self._position.quantity,
                last_row["timestamp"],
            )
            # The last equity point was marked before this forced close; replace
            # it with realized cash so final equity is net of exit fees/slippage.
            if self._position is None and self._equity_curve:
                self._equity_curve[-1] = round(self._cash, 4)

        return {
            "equity_curve":       self._equity_curve,
            "timestamps":         [str(t) for t in self._timestamps],
            "trades":             [t.to_dict() for t in self._trades],
            "final_equity":       self._equity_curve[-1] if self._equity_curve else self.initial_capital,
            "total_fees_paid":    round(self._total_fees, 4),
            "position":           self._position,
            # How many BUY signals were skipped because qty < lot_size (F&O only)
            "lot_size_skips":     self._lot_size_skips,
            # Indian cost breakdown (populated only when use_indian_costs=True)
            "cost_breakdown":     (
                aggregate_cost_breakdown(self._cost_breakdowns)
                if self.use_indian_costs and self._cost_breakdowns
                else {}
            ),
        }

    # ── Cost calculation ──────────────────────────────────────────────────────

    def _calculate_cost(self, turnover: float, side: str, track: bool = True) -> float:
        """
        Dispatch to the appropriate cost model and return total cost.

        Args:
            turnover: Trade value
            side:     'BUY' or 'SELL'
            track:    If True, record the breakdown for cost_breakdown summary.
                      Pass False for provisional/trial calculations that may be discarded.
        """
        if self._indian_calc is not None:
            cb = self._indian_calc.calculate(
                turnover        = turnover,
                side            = side,
                market_type     = self.market_type,
                brokerage_model = self.brokerage_model,
                brokerage_flat  = self.brokerage_flat,
                brokerage_pct   = self.brokerage_pct,
            )
            if track:
                self._cost_breakdowns.append(cb)
            return cb.total
        else:
            return self._simple_calc.calculate(turnover, side)

    # ── Execution ─────────────────────────────────────────────────────────────

    def _execute_buy(self, price: float, quantity: float, timestamp) -> float:
        """Buy `quantity` units at `price` (with slippage & fee). Returns actual qty bought."""
        actual_price = price * (1 + self.slippage_percent)
        cost         = quantity * actual_price
        # Provisional cost estimate — NOT yet tracked in cost_breakdowns
        fee          = self._calculate_cost(cost, "BUY", track=False)
        total_cost   = cost + fee

        # Partial fill if insufficient cash
        if total_cost > self._cash:
            if self._cash <= 0:
                return 0.0
            # Back-solve for how much we can afford
            if self.use_indian_costs:
                # Approximate: iterate to find affordable qty
                # (STT and other charges are non-linear w.r.t. qty, so approximate with 95%)
                affordable = self._cash * 0.97 / actual_price
                if self.lot_size > 1:
                    affordable = math.floor(affordable / self.lot_size) * self.lot_size
                if affordable <= 0:
                    return 0.0
                quantity   = affordable
                cost       = quantity * actual_price
                fee        = self._calculate_cost(cost, "BUY", track=True)   # final qty — track it
                total_cost = cost + fee
            else:
                quantity   = self._cash / (actual_price * (1 + self.fee_percent))
                if self.lot_size > 1:
                    quantity = math.floor(quantity / self.lot_size) * self.lot_size
                    if quantity <= 0:
                        return 0.0
                cost       = quantity * actual_price
                fee        = self._calculate_cost(cost, "BUY", track=True)   # final qty — track it
                total_cost = cost + fee
        else:
            # No partial fill — provisional cost IS the actual cost; record the breakdown now
            self._calculate_cost(cost, "BUY", track=True)

        self._cash        -= total_cost
        self._total_fees  += fee

        if self._position is None:
            self._position = Position(
                symbol      = self.symbol,
                quantity    = quantity,
                avg_price   = actual_price,
                entry_time  = timestamp,
                entry_price = actual_price,
                buy_fees    = fee,
            )
        else:
            self._position.buy_fees += fee
            # Weighted-average cost basis (WACB)
            old_qty = self._position.quantity
            old_avg = self._position.avg_price
            new_qty = old_qty + quantity
            new_avg = (old_qty * old_avg + quantity * actual_price) / new_qty
            self._position.quantity  = new_qty
            self._position.avg_price = new_avg

        logger.debug("BUY  %.6f @ %.4f | fee: %.4f | cash left: %.2f",
                     quantity, actual_price, fee, self._cash)
        return quantity

    def _execute_sell(self, price: float, quantity: float, timestamp) -> float:
        """Sell `quantity` units (min of requested and held). Returns actual qty sold."""
        if self._position is None or self._position.quantity <= 0:
            return 0.0

        quantity     = min(quantity, self._position.quantity)
        actual_price = price * (1 - self.slippage_percent)
        proceeds     = quantity * actual_price
        fee          = self._calculate_cost(proceeds, "SELL")
        net_proceeds = proceeds - fee

        # P&L = (exit - entry) × qty - sell fee - prorated share of the buy
        # fees for this portion. Cash already absorbed buy fees at entry; the
        # proration only affects the per-trade PnL/win-rate accounting.
        pos_qty_before = self._position.quantity
        buy_fee_part   = (self._position.buy_fees * (quantity / pos_qty_before)
                          if pos_qty_before > 0 else 0.0)
        pnl     = (actual_price - self._position.avg_price) * quantity - fee - buy_fee_part
        pnl_pct = (pnl / (self._position.avg_price * quantity)
                   if self._position.avg_price > 0 else 0.0)

        self._trades.append(TradeRecord(
            entry_time  = self._position.entry_time,
            entry_price = self._position.avg_price,
            exit_time   = timestamp,
            exit_price  = actual_price,
            quantity    = quantity,
            pnl         = pnl,
            pnl_pct     = pnl_pct,
            fees        = fee + buy_fee_part,   # full round-trip cost on this portion
        ))

        self._cash       += net_proceeds
        self._total_fees += fee

        self._position.buy_fees -= buy_fee_part
        self._position.quantity -= quantity
        if self._position.quantity <= 1e-10:
            self._position = None

        logger.debug("SELL %.6f @ %.4f | pnl: %.4f | fee: %.4f | cash: %.2f",
                     quantity, actual_price, pnl, fee, self._cash)
        return quantity

    # ── Equity ────────────────────────────────────────────────────────────────

    def _mark_equity(self, current_price: float) -> float:
        """Cash + mark-to-market value of open position."""
        mtm = 0.0
        if self._position:
            mtm = self._position.quantity * current_price
        return round(self._cash + mtm, 4)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def _reset(self):
        self._cash:             float                  = self.initial_capital
        self._position:         Optional[Position]     = None
        self._trades:           list[TradeRecord]      = []
        self._equity_curve:     list[float]            = [self.initial_capital]
        self._timestamps:       list                   = []
        self._total_fees:       float                  = 0.0
        self._cost_breakdowns:  list[CostBreakdown]    = []
        self._lot_size_skips:   int                    = 0   # BUY signals killed by lot rounding
