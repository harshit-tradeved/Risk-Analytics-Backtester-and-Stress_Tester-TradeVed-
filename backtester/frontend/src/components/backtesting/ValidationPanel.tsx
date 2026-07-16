/**
 * ValidationPanel
 * ───────────────
 * Renders out-of-sample validation results so traders can see whether a
 * strategy's backtest numbers hold on data it never "saw".
 *
 * Two modes:
 *   holdout      — in-sample vs out-of-sample metrics side by side + Δ column
 *   walk_forward — per-window table + aggregated OOS metrics
 */
import { ValidationData, ValidationMetrics, WalkForwardWindow } from '../../types';

/* ── Palette ─────────────────────────────────────────────────────────────── */
const GREEN  = 'var(--tv-green)';
const RED    = 'var(--tv-red)';
const ORANGE = 'var(--tv-amber)';
const AMBER  = 'var(--tv-amber)';
const TEXT   = 'var(--tv-text)';
const GREY   = 'var(--tv-muted)';
const DIM    = 'var(--tv-dim)';

interface Props {
  validation: ValidationData;
  currency?:  string;
}

export default function ValidationPanel({ validation: v, currency = '$' }: Props) {
  const locale = currency === '₹' ? 'en-IN' : 'en-US';

  if (v.mode === 'holdout') {
    return <HoldoutView v={v} currency={currency} locale={locale} />;
  }
  if (v.mode === 'walk_forward') {
    return <WalkForwardView v={v} currency={currency} locale={locale} />;
  }
  return null;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Holdout view
   ═══════════════════════════════════════════════════════════════════════════ */
function HoldoutView({ v, currency, locale }: { v: ValidationData; currency: string; locale: string }) {
  const ins = v.in_sample;
  const oos = v.out_of_sample;
  if (!ins || !oos) return null;

  const oosTrades     = oos.num_trades ?? 0;
  const lowTradeCount = oosTrades < 5;

  const verdict     = lowTradeCount ? 'insufficient_data' : (v.verdict ?? 'stable');
  const verdictCfg  = {
    stable:            { color: GREEN,  icon: '✅', msg: 'Out-of-sample results are consistent with in-sample. Strategy appears robust.' },
    degraded:          { color: ORANGE, icon: '⚠️', msg: 'Out-of-sample Sharpe dropped >50% vs in-sample. Results may reflect in-sample bias.' },
    failed:            { color: RED,    icon: '❌', msg: 'Strategy lost money out-of-sample. The in-sample return may not generalize to live trading.' },
    insufficient_data: { color: ORANGE, icon: '⚠️', msg: `Only ${oosTrades} OOS trade${oosTrades !== 1 ? 's' : ''} — Sharpe/Sortino are inflated because the equity curve is nearly flat. Extend the date range or reduce train ratio to get ≥ 5 OOS trades.` },
  }[verdict] ?? { color: DIM, icon: 'ℹ️', msg: '' };

  const fmtPct  = (n: number | undefined) => `${((n ?? 0) >= 0 ? '+' : '')}${(n ?? 0).toFixed(2)}%`;
  const fmtNum  = (n: number | undefined) => (n ?? 0).toFixed(2);
  const retCol  = (n: number | undefined) => ((n ?? 0) >= 0 ? GREEN : RED);
  const shrCol  = (n: number | undefined) => ((n ?? 0) >= 1 ? GREEN : (n ?? 0) >= 0 ? ORANGE : RED);

  const delta = (a: number | undefined, b: number | undefined) => {
    const d = (b ?? 0) - (a ?? 0);
    return { val: d, str: `${d >= 0 ? '+' : ''}${d.toFixed(2)}`, col: d >= 0 ? GREEN : RED };
  };

  const rows: {
    label:    string;
    ins_str:  string;
    oos_str:  string;
    ins_col:  string;
    oos_col:  string;
    delta:    { val: number; str: string; col: string };
  }[] = [
    {
      label:   'Total Return',
      ins_str: fmtPct(ins.total_return_pct),
      oos_str: fmtPct(oos.total_return_pct),
      ins_col: retCol(ins.total_return_pct),
      oos_col: retCol(oos.total_return_pct),
      delta:   delta(ins.total_return_pct, oos.total_return_pct),
    },
    {
      label:   'Ann. Return',
      ins_str: fmtPct(ins.annualised_return_pct),
      oos_str: fmtPct(oos.annualised_return_pct),
      ins_col: retCol(ins.annualised_return_pct),
      oos_col: retCol(oos.annualised_return_pct),
      delta:   delta(ins.annualised_return_pct, oos.annualised_return_pct),
    },
    {
      label:   'Sharpe Ratio',
      ins_str: fmtNum(ins.sharpe_ratio),
      oos_str: lowTradeCount ? `${fmtNum(oos.sharpe_ratio)} ⚠️` : fmtNum(oos.sharpe_ratio),
      ins_col: shrCol(ins.sharpe_ratio),
      oos_col: lowTradeCount ? GREY : shrCol(oos.sharpe_ratio),
      delta:   delta(ins.sharpe_ratio, oos.sharpe_ratio),
    },
    {
      label:   'Sortino Ratio',
      ins_str: fmtNum(ins.sortino_ratio),
      oos_str: lowTradeCount ? `${fmtNum(oos.sortino_ratio)} ⚠️` : fmtNum(oos.sortino_ratio),
      ins_col: shrCol(ins.sortino_ratio),
      oos_col: lowTradeCount ? GREY : shrCol(oos.sortino_ratio),
      delta:   delta(ins.sortino_ratio, oos.sortino_ratio),
    },
    {
      label:   'Max Drawdown',
      ins_str: `${(ins.max_drawdown_pct ?? 0).toFixed(2)}%`,
      oos_str: `${(oos.max_drawdown_pct ?? 0).toFixed(2)}%`,
      ins_col: (ins.max_drawdown_pct ?? 0) < -10 ? RED : ORANGE,
      oos_col: (oos.max_drawdown_pct ?? 0) < -10 ? RED : ORANGE,
      delta:   delta(ins.max_drawdown_pct, oos.max_drawdown_pct),
    },
    {
      label:   'Win Rate',
      ins_str: `${(ins.win_rate ?? 0).toFixed(1)}%`,
      oos_str: `${(oos.win_rate ?? 0).toFixed(1)}%`,
      ins_col: (ins.win_rate ?? 0) >= 50 ? GREEN : RED,
      oos_col: (oos.win_rate ?? 0) >= 50 ? GREEN : RED,
      delta:   delta(ins.win_rate, oos.win_rate),
    },
    {
      label:   'Trades',
      ins_str: String(ins.num_trades ?? 0),
      oos_str: String(oos.num_trades ?? 0),
      ins_col: TEXT,
      oos_col: TEXT,
      delta:   delta(ins.num_trades, oos.num_trades),
    },
  ];

  return (
    <div className="space-y-4 fade-in">
      {/* Header */}
      <div>
        <h3 className="text-sm font-bold tracking-wide mb-1" style={{ color: TEXT }}>
          🔬 Holdout Validation — In-Sample vs Out-of-Sample
        </h3>
        <p className="text-xs" style={{ color: GREY }}>
          Training on {((v.train_ratio ?? 0.7) * 100).toFixed(0)}% of data
          (up to <strong style={{ color: TEXT }}>{v.split_date}</strong>),
          tested on the remaining {((1 - (v.train_ratio ?? 0.7)) * 100).toFixed(0)}% unseen data.
          Same strategy parameters used for both — measures consistency, not over-fitting.
        </p>
      </div>

      {/* Verdict banner */}
      <div className="px-4 py-3 rounded-xl flex items-start gap-3"
        style={{ background: `${verdictCfg.color}18`, border: `1px solid ${verdictCfg.color}55` }}>
        <span className="text-lg">{verdictCfg.icon}</span>
        <div>
          <p className="text-sm font-semibold" style={{ color: verdictCfg.color }}>
            {verdict.replace('_', ' ').replace(/^\w/, c => c.toUpperCase())}
          </p>
          <p className="text-xs mt-0.5" style={{ color: GREY }}>{verdictCfg.msg}</p>
        </div>
      </div>

      {/* Comparison table */}
      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid #23233A' }}>
        <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--tv-s1)' }}>
              <th className="text-left px-4 py-3 text-xs font-semibold"
                style={{ color: GREY, borderBottom: '1px solid #23233A', width: '28%' }}>
                Metric
              </th>
              <th className="text-center px-4 py-3 text-xs font-bold"
                style={{ color: GREEN, borderBottom: '1px solid #23233A' }}>
                📊 In-Sample
                <div className="text-[10px] font-normal mt-0.5" style={{ color: DIM }}>
                  {ins.num_candles} candles
                </div>
              </th>
              <th className="text-center px-4 py-3 text-xs font-bold"
                style={{ color: AMBER, borderBottom: '1px solid #23233A' }}>
                🔬 Out-of-Sample
                <div className="text-[10px] font-normal mt-0.5" style={{ color: DIM }}>
                  {oos.num_candles} candles (unseen)
                </div>
              </th>
              <th className="text-center px-4 py-3 text-xs font-bold"
                style={{ color: GREY, borderBottom: '1px solid #23233A' }}>
                Δ Change
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.label}
                style={{ background: i % 2 === 0 ? 'var(--tv-bg)' : 'var(--tv-bg)' }}>
                <td className="px-4 py-2.5 text-xs font-medium" style={{ color: GREY }}>
                  {row.label}
                </td>
                <td className="px-4 py-2.5 text-center text-sm font-bold" style={{ color: row.ins_col }}>
                  {row.ins_str}
                </td>
                <td className="px-4 py-2.5 text-center text-sm font-bold" style={{ color: row.oos_col }}>
                  {row.oos_str}
                </td>
                <td className="px-4 py-2.5 text-center text-xs font-semibold"
                  style={{ color: row.delta.col }}>
                  {row.delta.str}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Guidance */}
      <div className="text-xs px-3 py-2 rounded-lg space-y-1"
        style={{ background: 'var(--tv-s1)', border: '1px solid #23233A' }}>
        <p style={{ color: GREY }}>
          <span style={{ color: TEXT }}>How to read this:</span> A strategy that makes money in both periods is more trustworthy.
          Large drops in Sharpe or a negative OOS return are red flags. Note that the same parameters are used for both
          periods — walk-forward validation (re-optimises per window) gives a stricter OOS test.
        </p>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Walk-forward view
   ═══════════════════════════════════════════════════════════════════════════ */
function WalkForwardView({ v, currency, locale }: { v: ValidationData; currency: string; locale: string }) {
  const agg  = v.out_of_sample;
  const wins = v.windows ?? [];

  const fmtPct = (n: number | undefined) => `${((n ?? 0) >= 0 ? '+' : '')}${(n ?? 0).toFixed(2)}%`;
  const fmtNum = (n: number | undefined) => (n ?? 0).toFixed(2);
  const retCol = (n: number | undefined) => ((n ?? 0) >= 0 ? GREEN : RED);
  const shrCol = (n: number | undefined) => ((n ?? 0) >= 1 ? GREEN : (n ?? 0) >= 0 ? ORANGE : RED);

  // Sharpe/Sortino are unreliable when fewer than 5 OOS trades: equity curve
  // is mostly flat, std of daily returns ≈ 0, so mean/std inflates arbitrarily.
  const oosTrades       = agg?.num_trades ?? 0;
  const lowTradeCount   = oosTrades < 5;
  const numWindows      = v.num_windows ?? 0;
  const avgTradesPerWin = numWindows > 0 ? oosTrades / numWindows : 0;
  const tinyWindows     = numWindows > 20 && avgTradesPerWin < 2;

  return (
    <div className="space-y-4 fade-in">
      {/* Header */}
      <div>
        <h3 className="text-sm font-bold tracking-wide mb-1" style={{ color: TEXT }}>
          🔬 Walk-Forward Validation
        </h3>
        <p className="text-xs" style={{ color: GREY }}>
          {v.num_windows} windows ·{' '}
          each trained on {v.window} candles, tested on {v.step} unseen candles.
          Parameters re-optimised per window — the strictest out-of-sample test.
          All test segments stitched into one OOS equity curve.
        </p>
      </div>

      {/* Tiny-windows warning (step too small) */}
      {tinyWindows && (
        <div className="px-4 py-3 rounded-xl flex items-start gap-3"
          style={{ background: '#FF990018', border: '1px solid #FF990055' }}>
          <span className="text-lg">⚠️</span>
          <div>
            <p className="text-sm font-semibold" style={{ color: ORANGE }}>
              Step size too small — {numWindows} windows, avg {avgTradesPerWin.toFixed(1)} trades/window
            </p>
            <p className="text-xs mt-0.5" style={{ color: GREY }}>
              Each OOS window is too short for the strategy to complete a full trade cycle.
              Increase Step (e.g. 63 for 1d data) so each window spans at least 1–2 months.
              With {numWindows} windows averaging {avgTradesPerWin.toFixed(1)} trades, all metrics are noise.
            </p>
          </div>
        </div>
      )}

      {/* Low-trade warning */}
      {lowTradeCount && (
        <div className="px-4 py-3 rounded-xl flex items-start gap-3"
          style={{ background: '#FF990018', border: '1px solid #FF990055' }}>
          <span className="text-lg">⚠️</span>
          <div>
            <p className="text-sm font-semibold" style={{ color: ORANGE }}>
              Metrics unreliable — only {oosTrades} OOS trade{oosTrades !== 1 ? 's' : ''}
            </p>
            <p className="text-xs mt-0.5" style={{ color: GREY }}>
              Sharpe and Sortino are mathematically inflated when the equity curve is nearly flat.
              With {oosTrades} trade{oosTrades !== 1 ? 's' : ''} over {agg?.num_candles ?? v.step} candles, the daily-return std ≈ 0,
              making mean/std → large. Need ≥ 5 trades for these ratios to mean anything.
              Extend the date range or reduce the step size to get more OOS trades.
            </p>
          </div>
        </div>
      )}

      {/* Aggregate OOS metrics */}
      {agg && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {[
            { label: 'OOS Total Return',   val: fmtPct(agg.total_return_pct),       col: retCol(agg.total_return_pct),  warn: false },
            { label: 'OOS Ann. Return',    val: fmtPct(agg.annualised_return_pct),  col: retCol(agg.annualised_return_pct), warn: false },
            { label: 'OOS Sharpe',         val: fmtNum(agg.sharpe_ratio),           col: lowTradeCount ? GREY : shrCol(agg.sharpe_ratio), warn: lowTradeCount },
            { label: 'OOS Max Drawdown',   val: `${(agg.max_drawdown_pct ?? 0).toFixed(2)}%`, col: (agg.max_drawdown_pct ?? 0) < -10 ? RED : ORANGE, warn: false },
            { label: 'OOS Win Rate',       val: `${(agg.win_rate ?? 0).toFixed(1)}%`, col: lowTradeCount ? GREY : ((agg.win_rate ?? 0) >= 50 ? GREEN : RED), warn: lowTradeCount },
            { label: 'OOS Total Trades',   val: String(oosTrades),                  col: lowTradeCount ? RED : TEXT,    warn: false },
            { label: 'OOS Sortino',        val: fmtNum(agg.sortino_ratio),          col: lowTradeCount ? GREY : shrCol(agg.sortino_ratio), warn: lowTradeCount },
            { label: 'Windows',            val: String(v.num_windows ?? 0),         col: TEXT,                          warn: false },
          ].map(m => (
            <div key={m.label} className="rounded-xl p-3 flex flex-col gap-0.5"
              style={{ background: 'var(--tv-bg)', border: `1px solid ${m.warn ? '#FF990055' : '#23233A'}` }}>
              <span className="text-xs font-medium" style={{ color: GREY }}>{m.label}</span>
              <span className="text-base font-bold" style={{ color: m.col }}>
                {m.val}{m.warn ? ' ⚠️' : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Per-window table */}
      {wins.length > 0 && (
        <div className="rounded-xl overflow-hidden" style={{ border: '1px solid #23233A' }}>
          <div className="px-4 py-2 text-xs font-semibold tracking-wide uppercase"
            style={{ background: 'var(--tv-s1)', color: GREY, borderBottom: '1px solid #23233A' }}>
            Per-Window OOS Results
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" style={{ borderCollapse: 'collapse', minWidth: '700px' }}>
              <thead>
                <tr style={{ background: 'var(--tv-bg)' }}>
                  {['#', 'Train Period', 'Test Period', 'Best Params', 'Train Sharpe', 'OOS Return', 'OOS Sharpe', 'OOS Max DD', 'Trades'].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-semibold"
                      style={{ color: GREY, borderBottom: '1px solid #23233A' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {wins.map((w: WalkForwardWindow, i: number) => {
                  const fewTrades = (w.num_trades ?? 0) < 3;
                  return (
                    <tr key={i} style={{ background: i % 2 === 0 ? 'var(--tv-bg)' : 'var(--tv-bg)' }}>
                      <td className="px-3 py-2" style={{ color: DIM }}>{w.window_num}</td>
                      <td className="px-3 py-2" style={{ color: DIM }}>{w.train_period}</td>
                      <td className="px-3 py-2" style={{ color: TEXT }}>{w.test_period}</td>
                      <td className="px-3 py-2 font-mono" style={{ color: DIM, maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {w.best_params}
                      </td>
                      <td className="px-3 py-2 text-right" style={{ color: shrCol(w.train_sharpe) }}>
                        {(w.train_sharpe ?? 0).toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right font-bold" style={{ color: retCol(w.return_pct) }}>
                        {fmtPct(w.return_pct)}
                      </td>
                      <td className="px-3 py-2 text-right" style={{ color: fewTrades ? GREY : shrCol(w.sharpe) }}>
                        {(w.sharpe ?? 0).toFixed(2)}{fewTrades ? ' ⚠️' : ''}
                      </td>
                      <td className="px-3 py-2 text-right"
                        style={{ color: (w.max_dd_pct ?? 0) < -10 ? RED : ORANGE }}>
                        {(w.max_dd_pct ?? 0).toFixed(2)}%
                      </td>
                      <td className="px-3 py-2 text-right" style={{ color: fewTrades ? RED : TEXT }}>
                        {w.num_trades ?? 0}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {wins.length === 0 && (
        <div className="p-4 rounded-xl" style={{ background: '#EF444418', border: '1px solid #EF444455' }}>
          <p className="text-sm font-semibold mb-1" style={{ color: RED }}>
            ❌ No OOS windows completed
          </p>
          <p className="text-xs" style={{ color: GREY }}>
            Need at least <strong style={{ color: TEXT }}>{(v.window ?? 252) + (v.step ?? 63)} candles</strong>{' '}
            (window {v.window} + step {v.step}) but your date range appears shorter.
          </p>
          <p className="text-xs mt-1.5 font-medium" style={{ color: TEXT }}>
            Fix options:
          </p>
          <ul className="text-xs mt-0.5 space-y-0.5 list-disc list-inside" style={{ color: GREY }}>
            <li>Extend date range to cover at least {Math.ceil(((v.window ?? 252) + (v.step ?? 63)) / 252 * 12)} months of daily data</li>
            <li>Reduce Window (e.g. 126 ≈ 6 months) and Step (e.g. 42 ≈ 2 months)</li>
            <li>Use a finer interval (1h instead of 1d gives ~6× more candles)</li>
          </ul>
        </div>
      )}

      {/* Guidance */}
      <div className="text-xs px-3 py-2 rounded-lg"
        style={{ background: 'var(--tv-s1)', border: '1px solid #23233A' }}>
        <p style={{ color: GREY }}>
          <span style={{ color: TEXT }}>Walk-forward is the gold standard:</span>{' '}
          params are optimised on each train window then applied to the next unseen step — no look-ahead bias.
          Consistent OOS returns across windows mean the strategy logic works in different market conditions,
          not just the specific dates of the overall backtest.
        </p>
      </div>
    </div>
  );
}
