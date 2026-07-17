"""
HTML Report Generator — creates a fully self-contained, professional
dark-theme backtest report with embedded Plotly charts.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import REPORTS_DIR
from backtesting.backend.reporting.charts import (
    equity_curve_chart,
    drawdown_chart,
    trade_distribution_chart,
    monthly_returns_chart,
    price_with_trades_chart,
    fig_to_json,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Main report builder
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(
    backtest_id:  str,
    symbol:       str,
    strategy:     str,
    params:       dict,
    metrics:      dict,
    ohlcv_df:     pd.DataFrame,
    reports_dir:  Path | None = None,
) -> Path:
    """
    Build a standalone HTML report and write it to disk.

    Returns the file path.
    """
    reports_dir = Path(reports_dir or REPORTS_DIR)
    reports_dir.mkdir(exist_ok=True)

    # Generate chart JSON blobs
    eq_json   = fig_to_json(equity_curve_chart(metrics))
    dd_json   = fig_to_json(drawdown_chart(metrics))
    dist_json = fig_to_json(trade_distribution_chart(metrics))
    mo_json   = fig_to_json(monthly_returns_chart(metrics))
    px_json   = fig_to_json(price_with_trades_chart(ohlcv_df, metrics))

    html = _build_html(
        backtest_id=backtest_id,
        symbol=symbol,
        strategy=strategy,
        params=params,
        metrics=metrics,
        eq_json=eq_json,
        dd_json=dd_json,
        dist_json=dist_json,
        mo_json=mo_json,
        px_json=px_json,
    )

    out_file = reports_dir / f"report_{backtest_id}.html"
    out_file.write_text(html, encoding="utf-8")
    logger.info("Report saved → %s", out_file)
    return out_file


# ─────────────────────────────────────────────────────────────────────────────
# HTML template
# ─────────────────────────────────────────────────────────────────────────────

def _build_html(
    backtest_id: str,
    symbol: str,
    strategy: str,
    params: dict,
    metrics: dict,
    eq_json: str,
    dd_json: str,
    dist_json: str,
    mo_json: str,
    px_json: str,
) -> str:

    total_ret  = metrics.get("total_return_pct",      0)
    sharpe     = metrics.get("sharpe_ratio",           0)
    sortino    = metrics.get("sortino_ratio",          0)
    max_dd     = metrics.get("max_drawdown_pct",       0)
    win_rate   = metrics.get("win_rate",               0)
    num_trades = metrics.get("num_trades",             0)
    pf         = metrics.get("profit_factor",          0)
    ann_ret    = metrics.get("annualised_return_pct",  0)
    best       = metrics.get("best_trade",             0)
    worst      = metrics.get("worst_trade",            0)
    avg_dur    = metrics.get("avg_trade_duration",     0)
    vol        = metrics.get("volatility_pct",         0)
    calmar     = metrics.get("calmar_ratio",           0)
    final_eq   = metrics.get("final_equity",           metrics.get("initial_capital", 10_000))
    init_cap   = metrics.get("initial_capital",        10_000)

    ret_color   = "#26A69A" if total_ret >= 0 else "#EF5350"
    ret_sign    = "+" if total_ret >= 0 else ""
    ann_color   = "#26A69A" if ann_ret  >= 0 else "#EF5350"
    ann_sign    = "+" if ann_ret  >= 0 else ""

    trades      = metrics.get("trades", [])
    trade_rows  = _build_trade_rows(trades)
    param_rows  = _build_param_rows(params)

    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    pf_display = f"{pf:.4f}" if pf != float("inf") else "∞"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Backtest Report — {symbol} {strategy} | TradeVed</title>
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg:      #0F1419;
      --card:    #1A1F28;
      --card2:   #222836;
      --border:  #2D3748;
      --text:    #E0E0E0;
      --muted:   #78909C;
      --blue:    #1E88E5;
      --green:   #26A69A;
      --red:     #EF5350;
      --yellow:  #FFA726;
      --purple:  #AB47BC;
    }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', Arial, sans-serif;
      font-size: 14px;
      line-height: 1.6;
    }}
    a {{ color: var(--blue); text-decoration: none; }}

    /* ── Header ── */
    .header {{
      background: linear-gradient(135deg, #0D1B2A 0%, #1A1F28 100%);
      border-bottom: 1px solid var(--border);
      padding: 28px 40px;
    }}
    .header h1 {{
      font-size: 24px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 6px;
    }}
    .header .sub {{
      font-size: 13px;
      color: var(--muted);
    }}
    .badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      margin-left: 10px;
      background: var(--blue);
      color: #fff;
    }}

    /* ── Layout ── */
    .container {{ max-width: 1400px; margin: 0 auto; padding: 28px 40px; }}
    .section {{ margin-bottom: 36px; }}
    .section-title {{
      font-size: 15px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 16px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}

    /* ── Metric cards ── */
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(175px, 1fr));
      gap: 14px;
    }}
    .metric-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 20px;
      transition: transform .15s;
    }}
    .metric-card:hover {{ transform: translateY(-2px); }}
    .metric-label {{
      font-size: 11px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .8px;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.5px;
    }}
    .metric-sub {{
      font-size: 11px;
      color: var(--muted);
      margin-top: 4px;
    }}
    .green  {{ color: var(--green);  }}
    .red    {{ color: var(--red);    }}
    .blue   {{ color: var(--blue);   }}
    .yellow {{ color: var(--yellow); }}
    .purple {{ color: var(--purple); }}
    .white  {{ color: #fff;          }}

    /* ── Charts ── */
    .chart-container {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      margin-bottom: 16px;
      overflow: hidden;
    }}
    .chart-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    @media (max-width: 900px) {{ .chart-row {{ grid-template-columns: 1fr; }} }}

    /* ── Tables ── */
    .table-wrap {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    thead {{ background: var(--card2); }}
    th {{
      padding: 12px 14px;
      text-align: left;
      font-size: 11px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .8px;
    }}
    td {{ padding: 10px 14px; border-top: 1px solid var(--border); }}
    tr:hover td {{ background: rgba(255,255,255,.02); }}
    .pnl-pos {{ color: var(--green); font-weight: 600; }}
    .pnl-neg {{ color: var(--red);   font-weight: 600; }}

    /* ── Config table ── */
    .config-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 10px;
    }}
    .config-item {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .config-key   {{ color: var(--muted); font-size: 12px; }}
    .config-value {{ font-weight: 600; color: #fff; font-size: 13px; }}

    /* ── Footer ── */
    .footer {{
      text-align: center;
      padding: 24px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--border);
      margin-top: 20px;
    }}
  </style>
</head>
<body>

<!-- ── HEADER ── -->
<div class="header">
  <h1>
    TradeVed Backtester
    <span class="badge">{strategy}</span>
  </h1>
  <div class="sub">
    Symbol: <strong style="color:#fff">{symbol}</strong> &nbsp;|&nbsp;
    ID: <code style="color:var(--muted)">{backtest_id}</code> &nbsp;|&nbsp;
    Generated: {generated_at}
  </div>
</div>

<div class="container">

<!-- ── KEY METRICS ── -->
<div class="section">
  <div class="section-title">Performance Overview</div>
  <div class="metrics-grid">

    <div class="metric-card">
      <div class="metric-label">Total Return</div>
      <div class="metric-value" style="color:{ret_color}">{ret_sign}{total_ret:.2f}%</div>
      <div class="metric-sub">${metrics.get('total_return_usd', 0):+,.2f}</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Annualised Return</div>
      <div class="metric-value" style="color:{ann_color}">{ann_sign}{ann_ret:.2f}%</div>
      <div class="metric-sub">CAGR</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Sharpe Ratio</div>
      <div class="metric-value {'green' if sharpe >= 1 else 'yellow' if sharpe >= 0 else 'red'}">{sharpe:.2f}</div>
      <div class="metric-sub">Risk-adjusted return</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Sortino Ratio</div>
      <div class="metric-value {'green' if sortino >= 1 else 'yellow' if sortino >= 0 else 'red'}">{sortino:.2f}</div>
      <div class="metric-sub">Downside deviation</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value red">{max_dd:.2f}%</div>
      <div class="metric-sub">Peak-to-trough</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Calmar Ratio</div>
      <div class="metric-value {'green' if calmar >= 1 else 'yellow'}">{calmar:.2f}</div>
      <div class="metric-sub">Ann. return / Max DD</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Win Rate</div>
      <div class="metric-value {'green' if win_rate >= 50 else 'red'}">{win_rate:.1f}%</div>
      <div class="metric-sub">{num_trades} total trades</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Profit Factor</div>
      <div class="metric-value {'green' if pf > 1 else 'red'}">{pf_display}</div>
      <div class="metric-sub">Gross profit / loss</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Volatility</div>
      <div class="metric-value yellow">{vol:.2f}%</div>
      <div class="metric-sub">Annualised</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Best Trade</div>
      <div class="metric-value green">${best:+,.2f}</div>
      <div class="metric-sub">Single trade P&L</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Worst Trade</div>
      <div class="metric-value red">${worst:+,.2f}</div>
      <div class="metric-sub">Single trade P&L</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Final Equity</div>
      <div class="metric-value white">${final_eq:,.2f}</div>
      <div class="metric-sub">Started: ${init_cap:,.2f}</div>
    </div>

  </div>
</div>

<!-- ── EQUITY CURVE ── -->
<div class="section">
  <div class="section-title">Equity Curve</div>
  <div class="chart-container">
    <div id="chart-equity" style="height:420px;"></div>
  </div>
</div>

<!-- ── DRAWDOWN + DISTRIBUTION ── -->
<div class="section">
  <div class="chart-row">
    <div class="chart-container">
      <div id="chart-drawdown" style="height:300px;"></div>
    </div>
    <div class="chart-container">
      <div id="chart-dist" style="height:300px;"></div>
    </div>
  </div>
</div>

<!-- ── PRICE + TRADES ── -->
<div class="section">
  <div class="section-title">Price Chart with Trade Markers</div>
  <div class="chart-container">
    <div id="chart-price" style="height:450px;"></div>
  </div>
</div>

<!-- ── MONTHLY RETURNS ── -->
<div class="section">
  <div class="section-title">Monthly P&L Heatmap</div>
  <div class="chart-container">
    <div id="chart-monthly" style="height:300px;"></div>
  </div>
</div>

<!-- ── TRADE LOG ── -->
<div class="section">
  <div class="section-title">Trade Log ({num_trades} trades)</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Entry Time</th>
          <th>Entry Price</th>
          <th>Exit Time</th>
          <th>Exit Price</th>
          <th>Quantity</th>
          <th>P&L ($)</th>
          <th>P&L (%)</th>
          <th>Fees ($)</th>
          <th>Duration</th>
        </tr>
      </thead>
      <tbody>
        {trade_rows}
      </tbody>
    </table>
  </div>
</div>

<!-- ── STRATEGY CONFIG ── -->
<div class="section">
  <div class="section-title">Strategy Configuration</div>
  <div class="config-grid">
    {param_rows}
  </div>
</div>

</div><!-- /container -->

<div class="footer">
  TradeVed Backtester &mdash; Report ID: {backtest_id} &mdash; {generated_at}<br/>
  <em>Past performance is not indicative of future results. For educational purposes only.</em>
</div>

<!-- ── Plotly chart rendering ── -->
<script>
  var cfg = {{responsive: true, displayModeBar: false}};

  Plotly.newPlot('chart-equity',   {eq_json},   {{}}, cfg);
  Plotly.newPlot('chart-drawdown', {dd_json},   {{}}, cfg);
  Plotly.newPlot('chart-dist',     {dist_json}, {{}}, cfg);
  Plotly.newPlot('chart-price',    {px_json},   {{}}, cfg);
  Plotly.newPlot('chart-monthly',  {mo_json},   {{}}, cfg);
</script>

</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build HTML rows
# ─────────────────────────────────────────────────────────────────────────────

def _build_trade_rows(trades: list[dict]) -> str:
    if not trades:
        return '<tr><td colspan="10" style="text-align:center;color:#78909C;">No trades</td></tr>'

    rows = []
    for i, t in enumerate(trades, 1):
        pnl     = t.get("pnl", 0)
        pnl_pct = t.get("pnl_pct", 0) * 100
        cls     = "pnl-pos" if pnl >= 0 else "pnl-neg"
        sign    = "+" if pnl >= 0 else ""

        # Duration
        try:
            entry_ts = pd.Timestamp(t["entry_time"])
            exit_ts  = pd.Timestamp(t["exit_time"])
            dur_hrs  = (exit_ts - entry_ts).total_seconds() / 3600
            dur_str  = f"{dur_hrs:.1f}h" if dur_hrs < 48 else f"{dur_hrs/24:.1f}d"
        except Exception:
            dur_str = "—"

        rows.append(f"""
        <tr>
          <td>{i}</td>
          <td>{t.get('entry_time','')[:19]}</td>
          <td>${t.get('entry_price',0):,.4f}</td>
          <td>{t.get('exit_time','')[:19]}</td>
          <td>${t.get('exit_price',0):,.4f}</td>
          <td>{t.get('quantity',0):.6f}</td>
          <td class="{cls}">{sign}${pnl:,.4f}</td>
          <td class="{cls}">{sign}{pnl_pct:.2f}%</td>
          <td>${t.get('fees',0):,.4f}</td>
          <td>{dur_str}</td>
        </tr>""")

    return "\n".join(rows)


def _build_param_rows(params: dict) -> str:
    rows = []
    for k, v in params.items():
        key_label = k.replace("_", " ").title()
        rows.append(f"""
        <div class="config-item">
          <span class="config-key">{key_label}</span>
          <span class="config-value">{v}</span>
        </div>""")
    return "\n".join(rows)
