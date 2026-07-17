"""
Chart generators using Plotly.
All functions return a Plotly Figure or its JSON representation.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


# ── Colour palette ─────────────────────────────────────────────────────────────
BLUE   = "#1E88E5"
GREEN  = "#26A69A"
RED    = "#EF5350"
YELLOW = "#FFA726"
PURPLE = "#AB47BC"
GREY   = "#78909C"
BG     = "#0F1419"
CARD   = "#1A1F28"
TEXT   = "#E0E0E0"

_TEMPLATE = {
    "layout": {
        "paper_bgcolor": BG,
        "plot_bgcolor":  CARD,
        "font":          {"color": TEXT, "family": "Arial, sans-serif"},
        "xaxis":         {"gridcolor": "#2D3748", "zerolinecolor": "#2D3748"},
        "yaxis":         {"gridcolor": "#2D3748", "zerolinecolor": "#2D3748"},
    }
}


def _base_layout(**kwargs) -> dict:
    base = {
        "paper_bgcolor": BG,
        "plot_bgcolor":  CARD,
        "font":          {"color": TEXT, "family": "Arial"},
        "margin":        {"t": 60, "b": 40, "l": 60, "r": 30},
        "legend":        {"bgcolor": CARD, "bordercolor": "#2D3748"},
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. Equity Curve
# ─────────────────────────────────────────────────────────────────────────────

def equity_curve_chart(metrics: dict) -> go.Figure:
    timestamps = metrics.get("timestamps", [])
    equity     = metrics.get("equity_curve", [])
    initial    = metrics.get("initial_capital", equity[0] if equity else 10_000)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=equity,
        mode="lines",
        name="Portfolio Equity",
        line=dict(color=BLUE, width=2),
        fill="tozeroy",
        fillcolor="rgba(30,136,229,0.08)",
    ))
    fig.add_hline(y=initial, line=dict(dash="dash", color=GREY, width=1),
                  annotation_text="Initial Capital", annotation_font_color=GREY)

    pct = metrics.get("total_return_pct", 0)
    color = GREEN if pct >= 0 else RED
    fig.update_layout(
        **_base_layout(
            title=dict(text=f"📈 Equity Curve  ({pct:+.2f}%)", font=dict(color=color, size=16)),
            xaxis_title="Date",
            yaxis_title="Portfolio Value ($)",
            height=420,
        )
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 2. Drawdown Chart
# ─────────────────────────────────────────────────────────────────────────────

def drawdown_chart(metrics: dict) -> go.Figure:
    timestamps = metrics.get("timestamps", [])
    drawdowns  = metrics.get("drawdowns",  [])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=drawdowns,
        mode="lines",
        name="Drawdown",
        line=dict(color=RED, width=1.5),
        fill="tozeroy",
        fillcolor="rgba(239,83,80,0.15)",
    ))

    max_dd = metrics.get("max_drawdown_pct", 0)
    fig.update_layout(
        **_base_layout(
            title=dict(text=f"📉 Drawdown (Max: {max_dd:.2f}%)", font=dict(color=RED, size=16)),
            xaxis_title="Date",
            yaxis_title="Drawdown (%)",
            height=300,
        )
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 3. Trade Return Distribution
# ─────────────────────────────────────────────────────────────────────────────

def trade_distribution_chart(metrics: dict) -> go.Figure:
    trades  = metrics.get("trades", [])
    pnl_pct = [t["pnl_pct"] * 100 for t in trades if "pnl_pct" in t]

    fig = go.Figure()
    if pnl_pct:
        winners = [p for p in pnl_pct if p >= 0]
        losers  = [p for p in pnl_pct if p <  0]

        if winners:
            fig.add_trace(go.Histogram(
                x=winners, name="Winners", nbinsx=20,
                marker_color=GREEN, opacity=0.8,
            ))
        if losers:
            fig.add_trace(go.Histogram(
                x=losers, name="Losers", nbinsx=20,
                marker_color=RED, opacity=0.8,
            ))
        fig.add_vline(x=0, line=dict(dash="dash", color=GREY))
    else:
        fig.add_annotation(text="No trades", showarrow=False,
                           font=dict(color=GREY, size=18))

    fig.update_layout(
        **_base_layout(
            title=dict(text="📊 Trade Return Distribution", font=dict(size=16)),
            xaxis_title="P&L (%)",
            yaxis_title="Number of Trades",
            barmode="overlay",
            height=350,
        )
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 4. Monthly Returns Heatmap
# ─────────────────────────────────────────────────────────────────────────────

def monthly_returns_chart(metrics: dict) -> go.Figure:
    trades = metrics.get("trades", [])
    if not trades:
        fig = go.Figure()
        fig.add_annotation(text="No trades to display", showarrow=False,
                           font=dict(color=GREY, size=18))
        fig.update_layout(**_base_layout(title="Monthly Returns", height=300))
        return fig

    rows = []
    for t in trades:
        try:
            ts  = pd.Timestamp(t["exit_time"])
            rows.append({"year": ts.year, "month": ts.month, "pnl": t["pnl"]})
        except Exception:
            pass

    if not rows:
        fig = go.Figure()
        fig.update_layout(**_base_layout(title="Monthly Returns", height=300))
        return fig

    df = pd.DataFrame(rows)
    pivot = df.groupby(["year", "month"])["pnl"].sum().unstack(fill_value=0)

    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    z      = pivot.values.tolist()
    y_labs = [str(y) for y in pivot.index.tolist()]
    x_labs = [month_names[m - 1] for m in pivot.columns.tolist()]

    max_abs = max(abs(v) for row in z for v in row) or 1

    fig = go.Figure(go.Heatmap(
        z=z, x=x_labs, y=y_labs,
        colorscale=[[0, RED], [0.5, CARD], [1, GREEN]],
        zmid=0, zmin=-max_abs, zmax=max_abs,
        text=[[f"${v:,.0f}" for v in row] for row in z],
        texttemplate="%{text}",
        hovertemplate="Year: %{y}<br>Month: %{x}<br>P&L: $%{z:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        **_base_layout(
            title=dict(text="📅 Monthly P&L Heatmap", font=dict(size=16)),
            height=300,
        )
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 5. Price chart with trade markers
# ─────────────────────────────────────────────────────────────────────────────

def price_with_trades_chart(
    ohlcv_df: pd.DataFrame,
    metrics:  dict,
) -> go.Figure:
    trades = metrics.get("trades", [])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ohlcv_df["timestamp"], y=ohlcv_df["close"],
        mode="lines", name="Price",
        line=dict(color=GREY, width=1.2),
    ))

    entries = [t for t in trades]
    if entries:
        fig.add_trace(go.Scatter(
            x=[t["entry_time"] for t in entries],
            y=[t["entry_price"] for t in entries],
            mode="markers", name="Entry",
            marker=dict(symbol="triangle-up", size=10, color=GREEN),
        ))
        exits = [t for t in trades if t.get("exit_time")]
        fig.add_trace(go.Scatter(
            x=[t["exit_time"]  for t in exits],
            y=[t["exit_price"] for t in exits],
            mode="markers", name="Exit",
            marker=dict(symbol="triangle-down", size=10, color=RED),
        ))

    fig.update_layout(
        **_base_layout(
            title=dict(text="💹 Price Chart with Trade Markers", font=dict(size=16)),
            xaxis_title="Date",
            yaxis_title="Price ($)",
            height=450,
        )
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Helper: figure → JSON string (for embedding in HTML)
# ─────────────────────────────────────────────────────────────────────────────

def fig_to_json(fig: go.Figure) -> str:
    return fig.to_json()
