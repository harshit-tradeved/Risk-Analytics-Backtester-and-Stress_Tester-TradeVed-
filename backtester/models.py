"""
SQLAlchemy ORM models for the backtester system.

Tables:
  - ohlcv_data       : raw market data
  - backtests        : backtest job metadata
  - backtest_results : aggregated performance metrics
  - trades           : individual trade records
"""
import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Date,
    Text, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from database import Base


class OHLCVData(Base):
    """Stores raw OHLCV candle data fetched from external sources."""
    __tablename__ = "ohlcv_data"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", "source", name="uq_ohlcv"),
        Index("ix_ohlcv_symbol_ts", "symbol", "timestamp"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    symbol       = Column(String(20), nullable=False)
    timestamp    = Column(DateTime, nullable=False)
    open         = Column(Float, nullable=False)
    high         = Column(Float, nullable=False)
    low          = Column(Float, nullable=False)
    close        = Column(Float, nullable=False)
    volume       = Column(Float, nullable=False)
    source       = Column(String(20), default="binance")
    quality_score = Column(Float, default=100.0)
    created_at   = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat(),
            "open":   self.open,
            "high":   self.high,
            "low":    self.low,
            "close":  self.close,
            "volume": self.volume,
        }


class Backtest(Base):
    """Tracks each backtest run (metadata / job record)."""
    __tablename__ = "backtests"

    id         = Column(String(36), primary_key=True)   # UUID
    symbol     = Column(String(20), nullable=False)
    strategy   = Column(String(20), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date   = Column(Date, nullable=False)
    capital    = Column(Float, nullable=False)
    params     = Column(Text)          # JSON-encoded strategy params
    status     = Column(String(20), default="pending")   # pending/running/done/error
    error_msg  = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    result = relationship("BacktestResult", back_populates="backtest", uselist=False)
    trades = relationship("Trade", back_populates="backtest")

    @property
    def params_dict(self):
        return json.loads(self.params) if self.params else {}


class BacktestResult(Base):
    """Aggregated performance metrics for a finished backtest."""
    __tablename__ = "backtest_results"

    backtest_id       = Column(String(36), ForeignKey("backtests.id"), primary_key=True)
    total_return      = Column(Float)
    total_return_pct  = Column(Float)
    sharpe_ratio      = Column(Float)
    sortino_ratio     = Column(Float)
    max_drawdown      = Column(Float)
    profit_factor     = Column(Float)
    win_rate          = Column(Float)
    num_trades        = Column(Integer)
    trades_per_day    = Column(Float)
    avg_trade_duration = Column(Float)   # hours
    best_trade        = Column(Float)
    worst_trade       = Column(Float)
    results_json      = Column(Text)     # full JSON blob (equity curve, drawdowns, …)

    backtest = relationship("Backtest", back_populates="result")

    @property
    def results_dict(self):
        return json.loads(self.results_json) if self.results_json else {}

    def to_dict(self):
        return {
            "backtest_id":        self.backtest_id,
            "total_return":       self.total_return,
            "total_return_pct":   self.total_return_pct,
            "sharpe_ratio":       self.sharpe_ratio,
            "sortino_ratio":      self.sortino_ratio,
            "max_drawdown":       self.max_drawdown,
            "profit_factor":      self.profit_factor,
            "win_rate":           self.win_rate,
            "num_trades":         self.num_trades,
            "trades_per_day":     self.trades_per_day,
            "avg_trade_duration": self.avg_trade_duration,
            "best_trade":         self.best_trade,
            "worst_trade":        self.worst_trade,
        }


class Trade(Base):
    """Individual trade records linked to a backtest."""
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_backtest", "backtest_id"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    backtest_id = Column(String(36), ForeignKey("backtests.id"), nullable=False)
    entry_time  = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_time   = Column(DateTime)
    exit_price  = Column(Float)
    quantity    = Column(Float)
    pnl         = Column(Float)
    pnl_pct     = Column(Float)
    fees        = Column(Float)
    side        = Column(String(10), default="LONG")

    backtest = relationship("Backtest", back_populates="trades")

    def to_dict(self):
        return {
            "entry_time":  self.entry_time.isoformat() if self.entry_time else None,
            "entry_price": self.entry_price,
            "exit_time":   self.exit_time.isoformat() if self.exit_time else None,
            "exit_price":  self.exit_price,
            "quantity":    self.quantity,
            "pnl":         self.pnl,
            "pnl_pct":     self.pnl_pct,
            "fees":        self.fees,
            "side":        self.side,
        }


class AnalyticsEvent(Base):
    """User interaction events for usage tracking."""
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_created", "created_at"),
        Index("ix_analytics_session", "session_id"),
    )

    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), nullable=False)
    user_name  = Column(String(100))
    user_email = Column(String(200))
    event_type = Column(String(20), nullable=False)   # page_view | action | error | api
    event_name = Column(String(100), nullable=False)
    page       = Column(String(50))
    props      = Column(Text)                          # JSON-encoded extra properties
    user_agent = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)


class StrategyOutcome(Base):
    """Append-only log of every backtest's {strategy, params, regime, outcome}.

    This is the seed of the strategy-intelligence moat (ROADMAP Track 2 / Phase 0):
    a growing, proprietary dataset that a future gradient-boosting ranker trains on
    to answer "which strategy suits this asset/regime?". Written on every backtest
    run; cheap now, compounding later. Never read on the hot path.
    """
    __tablename__ = "strategy_outcomes"
    __table_args__ = (
        Index("ix_outcome_strategy", "strategy"),
        Index("ix_outcome_symbol", "symbol"),
        Index("ix_outcome_created", "created_at"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    backtest_id = Column(String(36))                  # FK-ish link to backtests.id (nullable for stress/forecast)
    strategy    = Column(String(20), nullable=False)
    category    = Column(String(20))                  # classic | indicator | custom
    symbol      = Column(String(20), nullable=False)
    source      = Column(String(20))
    interval    = Column(String(10))
    start_date  = Column(Date)
    end_date    = Column(Date)
    capital     = Column(Float)
    params      = Column(Text)                        # JSON-encoded strategy params
    # ── Outcome metrics ──
    total_return_pct = Column(Float)
    sharpe_ratio     = Column(Float)
    sortino_ratio    = Column(Float)
    max_drawdown_pct = Column(Float)
    win_rate         = Column(Float)
    profit_factor    = Column(Float)
    num_trades       = Column(Integer)
    # ── Market context ──
    regime_mix  = Column(Text)                         # JSON: {bull, bear, sideways} candle counts
    created_at  = Column(DateTime, default=datetime.utcnow)


class Feedback(Base):
    """In-app feedback submitted by testers."""
    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_created", "created_at"),
    )

    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), nullable=False)
    user_name  = Column(String(100))
    user_email = Column(String(200))
    category   = Column(String(20), nullable=False)   # bug | idea | praise | other
    rating     = Column(Integer)                       # 1–5, nullable
    message    = Column(Text, nullable=False)
    page       = Column(String(50))
    context    = Column(Text)                          # JSON: symbol, strategy, backtest_id, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
