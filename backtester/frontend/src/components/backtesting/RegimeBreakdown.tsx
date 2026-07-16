/**
 * RegimeBreakdown
 * ─────────────────
 * Shows how a strategy performed across bull / bear / sideways market conditions.
 * Helps retail traders understand whether a backtest result is regime-dependent
 * ("only works in a bull market") or genuinely robust.
 *
 * Rendered directly below MetricsGrid in App.tsx whenever result.results.regimes
 * is present.
 */
import { MetricsResults, RegimeBreakdownData, RegimeStat } from '../../types';

const GREEN  = 'var(--tv-green)';
const RED    = 'var(--tv-red)';
const ORANGE = 'var(--tv-amber)';
const AMBER  = 'var(--tv-amber)';
const TEXT   = 'var(--tv-text)';
const GREY   = 'var(--tv-muted)';
const DIM    = 'var(--tv-dim)';

interface Props {
  results:   MetricsResults;
  currency?: string;
}

export default function RegimeBreakdown({ results, currency = '$' }: Props) {
  const data: RegimeBreakdownData | undefined = results.regimes;
  if (!data) return null;

  const locale = currency === '₹' ? 'en-IN' : 'en-US';
  const fmt    = (n: number, d = 2) => (n ?? 0).toFixed(d);
  const fmtMoney = (n: number) =>
    `${currency}${n >= 0 ? '' : '-'}${Math.abs(n).toLocaleString(locale, { maximumFractionDigits: 0 })}`;
  const retColor  = (v: number) => v >= 0 ? GREEN : RED;
  const shrColor  = (v: number) => v >= 1 ? GREEN : v >= 0 ? ORANGE : RED;

  const totalCandles =
    (data.regime_counts?.bull ?? 0) +
    (data.regime_counts?.bear ?? 0) +
    (data.regime_counts?.sideways ?? 0);

  const regimes: { key: 'bull' | 'bear' | 'sideways'; label: string; emoji: string; headerColor: string }[] = [
    { key: 'bull',     label: 'Bull Market',  emoji: '📈', headerColor: GREEN  },
    { key: 'bear',     label: 'Bear Market',  emoji: '📉', headerColor: RED    },
    { key: 'sideways', label: 'Sideways',     emoji: '↔️', headerColor: AMBER  },
  ];

  const rows: { label: string; fmt: (s: RegimeStat) => string; color?: (s: RegimeStat) => string }[] = [
    {
      label: 'Return',
      fmt: s => `${(s.total_return_pct ?? 0) >= 0 ? '+' : ''}${fmt(s.total_return_pct)}%`,
      color: s => retColor(s.total_return_pct),
    },
    {
      label: 'Sharpe',
      fmt: s => fmt(s.sharpe_ratio),
      color: s => shrColor(s.sharpe_ratio),
    },
    {
      label: 'Sortino',
      fmt: s => fmt(s.sortino_ratio),
      color: s => shrColor(s.sortino_ratio),
    },
    {
      label: 'Max Drawdown',
      fmt: s => `${fmt(s.max_drawdown_pct)}%`,
      color: s => s.max_drawdown_pct < -10 ? RED : s.max_drawdown_pct < -5 ? ORANGE : GREEN,
    },
    {
      label: 'Volatility',
      fmt: s => `${fmt(s.volatility_pct)}%`,
    },
    {
      label: 'Win Rate',
      fmt: s => `${fmt(s.win_rate, 1)}%`,
      color: s => s.win_rate >= 60 ? GREEN : s.win_rate >= 40 ? ORANGE : RED,
    },
    {
      label: 'Trades',
      fmt: s => String(s.num_trades ?? 0),
    },
    {
      label: 'Avg Trade P&L',
      fmt: s => fmtMoney(s.avg_trade_pnl ?? 0),
      color: s => retColor(s.avg_trade_pnl),
    },
    {
      label: '% of Period',
      fmt: s => `${fmt(s.pct_of_period, 1)}%`,
    },
  ];

  return (
    <div className="fade-in" style={{ marginTop: '1rem' }}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-bold tracking-wide" style={{ color: TEXT }}>
          🌐 Performance by Market Regime
        </span>
        <span className="text-xs px-2 py-0.5 rounded-full"
          style={{ background: 'var(--tv-border)', color: GREY }}>
          MA-trend · {totalCandles} candles classified
        </span>
        <span className="text-xs" style={{ color: DIM }}>
          Are the returns spread across conditions, or only from one regime?
        </span>
      </div>

      {/* Table */}
      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid #23233A' }}>
        <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--tv-s1)' }}>
              <th className="text-left px-4 py-2.5 text-xs font-semibold tracking-wide"
                style={{ color: GREY, width: '28%', borderBottom: '1px solid #23233A' }}>
                Metric
              </th>
              {regimes.map(r => (
                <th key={r.key}
                  className="text-center px-4 py-2.5 text-xs font-bold tracking-wide"
                  style={{ color: r.headerColor, borderBottom: '1px solid #23233A' }}>
                  {r.emoji} {r.label}
                  <div className="text-[10px] font-normal mt-0.5" style={{ color: DIM }}>
                    {data.regime_counts?.[r.key] ?? 0} candles ·{' '}
                    {data[r.key]?.pct_of_period?.toFixed(1) ?? 0}%
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.label}
                style={{ background: i % 2 === 0 ? 'var(--tv-bg)' : 'var(--tv-bg)' }}>
                <td className="px-4 py-2 text-xs font-medium" style={{ color: GREY }}>
                  {row.label}
                </td>
                {regimes.map(r => {
                  const stat = data[r.key];
                  const val  = row.fmt(stat);
                  const col  = row.color ? row.color(stat) : TEXT;
                  return (
                    <td key={r.key} className="px-4 py-2 text-center text-xs font-semibold"
                      style={{ color: col }}>
                      {val}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Interpretation hint */}
      <RegimeInterpretation data={data} />
    </div>
  );
}

function RegimeInterpretation({ data }: { data: RegimeBreakdownData }) {
  const bullRet  = data.bull?.total_return_pct  ?? 0;
  const bearRet  = data.bear?.total_return_pct  ?? 0;
  const sideRet  = data.sideways?.total_return_pct ?? 0;
  const bullPct  = data.bull?.pct_of_period ?? 0;
  const bearPct  = data.bear?.pct_of_period ?? 0;

  const msgs: { text: string; color: string }[] = [];

  if (bullRet > 5 && bearRet < -5) {
    msgs.push({ text: '⚠️ Strategy profits mainly in bull markets — be cautious entering during downtrends.', color: ORANGE });
  }
  if (bearRet > 0 && sideRet > 0) {
    msgs.push({ text: '✅ Strategy generated positive returns in all three regimes — strong consistency signal.', color: GREEN });
  }
  if (bearRet > 0 && bullRet > 0) {
    msgs.push({ text: '✅ Positive return in both bull and bear periods — shows some regime robustness.', color: GREEN });
  }
  if (bullPct < 20 && bearPct < 20) {
    msgs.push({ text: 'ℹ️ Short backtest period — few candles classified as bull/bear. Longer date ranges give more reliable regime stats.', color: DIM });
  }
  if (msgs.length === 0) {
    msgs.push({ text: 'ℹ️ Compare returns across regimes to judge whether this strategy suits the current market environment.', color: DIM });
  }

  return (
    <div className="mt-2 space-y-1">
      {msgs.map((m, i) => (
        <p key={i} className="text-xs px-3 py-1.5 rounded-lg"
          style={{ color: m.color, background: 'rgba(255,255,255,0.03)' }}>
          {m.text}
        </p>
      ))}
    </div>
  );
}
