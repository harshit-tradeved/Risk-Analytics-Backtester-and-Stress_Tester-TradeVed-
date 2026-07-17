import { MetricsResults } from '@app/types';

/* ── TradeVed palette refs ─────────────────────────────────────────────── */
const GREEN  = 'var(--tv-green)';
const RED    = 'var(--tv-red)';
const ORANGE = 'var(--tv-amber)';
const TEXT   = 'var(--tv-text)';
const GREY   = 'var(--tv-muted)';
const DIM    = 'var(--tv-dim)';
const ACCENT = 'var(--tv-accent)';

interface Props {
  results:   MetricsResults;
  currency?: string;   // '$' or '₹'
}

export default function MetricsGrid({ results: r, currency = '$' }: Props) {
  const pf      = r.profit_factor;
  const pfStr   = pf === Infinity || pf > 999 ? '∞' : pf.toFixed(2);
  const retColor = r.total_return_pct >= 0 ? GREEN : RED;
  const ddColor  = r.max_drawdown_pct < -10 ? RED : r.max_drawdown_pct < -5 ? ORANGE : GREEN;
  // Use Indian number grouping (1,00,000) for ₹, US grouping (100,000) for $
  const locale  = currency === '₹' ? 'en-IN' : 'en-US';
  const fmt     = (n: number, decimals = 0) => n.toLocaleString(locale, { maximumFractionDigits: decimals });
  const fmtMoney = (n: number) => `${currency}${n >= 0 ? '' : '-'}${fmt(Math.abs(n))}`;
  const fmtMoneySign = (n: number) => `${currency}${n >= 0 ? '+' : ''}${fmt(n, 2)}`;

  return (
    <div className="space-y-3 fade-in">
      {/* Row 1 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard
          label="Total Return"
          value={`${r.total_return_pct >= 0 ? '+' : ''}${r.total_return_pct.toFixed(2)}%`}
          sub={r.total_return_usd != null ? fmtMoneySign(r.total_return_usd) : '—'}
          valueColor={retColor}
        />
        <MetricCard
          label="Ann. Return"
          value={`${(r.annualised_return_pct ?? r.annualised_return) >= 0 ? '+' : ''}${(r.annualised_return_pct ?? r.annualised_return).toFixed(2)}%`}
          sub="CAGR"
          valueColor={(r.annualised_return_pct ?? 0) >= 0 ? GREEN : RED}
        />
        <MetricCard
          label="Sharpe Ratio"
          value={r.sharpe_ratio.toFixed(2)}
          sub={r.sharpe_ratio >= 2 ? 'Excellent' : r.sharpe_ratio >= 1 ? 'Good' : r.sharpe_ratio >= 0 ? 'Acceptable' : 'Poor'}
          valueColor={r.sharpe_ratio >= 1 ? GREEN : r.sharpe_ratio >= 0 ? ORANGE : RED}
        />
        <MetricCard
          label="Max Drawdown"
          value={`${r.max_drawdown_pct.toFixed(2)}%`}
          sub="Peak → trough"
          valueColor={ddColor}
        />
        <MetricCard
          label="Win Rate"
          value={`${r.win_rate.toFixed(1)}%`}
          sub={`${r.num_trades} trades`}
          valueColor={r.win_rate >= 60 ? GREEN : r.win_rate >= 40 ? ORANGE : RED}
        />
        <MetricCard
          label="Profit Factor"
          value={pfStr}
          sub="Gross profit / loss"
          valueColor={pf >= 1.5 ? GREEN : pf >= 1 ? ORANGE : RED}
        />
      </div>

      {/* Row 2 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Sortino Ratio"  value={r.sortino_ratio.toFixed(2)}  sub="Downside adj." />
        <MetricCard label="Calmar Ratio"   value={r.calmar_ratio.toFixed(2)}   sub="Return/Max DD" />
        <MetricCard label="Volatility"     value={`${r.volatility_pct?.toFixed(2) ?? '—'}%`} sub="Annualised" />
        <MetricCard label="Best Trade"
          value={fmtMoneySign(r.best_trade ?? 0)}
          valueColor={GREEN}
        />
        <MetricCard label="Worst Trade"
          value={fmtMoney(r.worst_trade ?? 0)}
          valueColor={r.worst_trade < 0 ? RED : GREEN}
        />
        <MetricCard label="Final Equity"
          value={fmtMoney(r.final_equity)}
          sub={`Started: ${fmtMoney(r.initial_capital ?? 0)}`}
          valueColor={ACCENT}
          highlight
        />
      </div>

      {/* Info chips */}
      <div className="flex flex-wrap gap-2 text-xs" style={{ color: GREY }}>
        <InfoChip label="Total Fees"   value={fmtMoney(r.total_fees_paid ?? 0)} />
        <InfoChip label="Avg Trade"    value={fmtMoneySign(r.avg_trade_pnl ?? 0)} />
        <InfoChip label="Avg Duration" value={`${(r.avg_trade_duration ?? 0).toFixed(1)}h`} />
        <InfoChip label="Gross Profit" value={fmtMoney(r.gross_profit ?? 0)}  color={GREEN} />
        <InfoChip label="Gross Loss"   value={fmtMoney(r.gross_loss   ?? 0)}  color={RED}   />
        {r.data_quality_score !== undefined && (
          <InfoChip label="Data Quality" value={`${r.data_quality_score.toFixed(0)}/100`}
            color={r.data_quality_score >= 90 ? GREEN : r.data_quality_score >= 70 ? ORANGE : RED} />
        )}
      </div>

      {/* Indian cost breakdown (only when Indian costs are present) */}
      {r.cost_breakdown && r.cost_breakdown.total > 0 && (
        <div className="mt-2 p-3 rounded-xl text-xs"
          style={{ background: 'rgba(168,236,58,0.05)', border: '1px solid rgba(168,236,58,0.2)' }}>
          <p className="font-bold text-[10px] tracking-widest uppercase mb-2" style={{ color: GREEN }}>
            🇮🇳 Indian Transaction Cost Breakdown (total round-trip)
          </p>
          <div className="flex flex-wrap gap-3">
            {[
              { label: 'Brokerage',     val: r.cost_breakdown.brokerage },
              { label: 'STT',           val: r.cost_breakdown.stt },
              { label: 'Exch. Charges', val: r.cost_breakdown.exchange_charges },
              { label: 'SEBI',          val: r.cost_breakdown.sebi_charges },
              { label: 'GST',           val: r.cost_breakdown.gst },
              { label: 'Stamp Duty',    val: r.cost_breakdown.stamp_duty },
            ].map(c => (
              <span key={c.label} style={{ color: GREY }}>
                {c.label}: <span style={{ color: TEXT }}>{fmtMoney(c.val)}</span>
              </span>
            ))}
            <span style={{ color: ORANGE, fontWeight: 600 }}>
              Total: {fmtMoney(r.cost_breakdown.total)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Metric card ────────────────────────────────────────────────────────── */
function MetricCard({ label, value, sub, valueColor = TEXT, highlight = false }: {
  label: string; value: string; sub?: string; valueColor?: string; highlight?: boolean;
}) {
  return (
    <div className="rounded-2xl p-4 flex flex-col gap-1 transition-transform hover:-translate-y-0.5 tv-soft-shadow"
      style={{
        background: highlight ? 'var(--tv-pastel-green)' : 'var(--tv-s1)',
      }}>
      <span className="text-xs font-semibold" style={{ color: GREY }}>{label}</span>
      <span className="text-2xl font-bold leading-tight" style={{ color: valueColor }}>{value}</span>
      {sub && <span className="text-xs font-medium mt-1" style={{ color: DIM }}>{sub}</span>}
    </div>
  );
}

/* ── Info chip ──────────────────────────────────────────────────────────── */
function InfoChip({ label, value, color = TEXT }: { label: string; value: string; color?: string }) {
  return (
    <span className="px-3 py-1.5 rounded-full tv-soft-shadow bg-white text-xs font-medium border border-[var(--tv-border)]">
      <span style={{ color: GREY }}>{label}: </span>
      <span style={{ color, fontWeight: 'bold' }}>{value}</span>
    </span>
  );
}
