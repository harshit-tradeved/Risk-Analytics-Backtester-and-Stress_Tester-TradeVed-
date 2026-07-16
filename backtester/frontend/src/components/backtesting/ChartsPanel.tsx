import { useState, useMemo } from 'react';
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
  ReferenceArea, ResponsiveContainer, Scatter,
} from 'recharts';
import { SeriesData, Trade, ValidationData, WalkForwardWindow } from '../../types';

/* ── TradeVed brand palette ───────────────────────────────────────────── */
const C = {
  bg:       'var(--tv-bg)',
  card:     'var(--tv-s1)',
  card2:    'var(--tv-s2)',
  grid:     'var(--tv-border)',
  accent:   'var(--tv-accent)',
  blue:     'var(--tv-accent)',
  green:    'var(--tv-green)',
  teal:     'var(--tv-accent2)',
  red:      'var(--tv-red)',
  orange:   'var(--tv-amber)',
  amber:    'var(--tv-amber)',
  grey:     'var(--tv-muted)',
  dim:      'var(--tv-dim)',
  text:     'var(--tv-text)',
};

/* Regime colors (background bands) — tinted but chart data stays readable */
const REGIME_FILL = {
  bull:     'rgba(0,200,150,0.18)',    // much darker green
  bear:     'rgba(239,68,68,0.15)',    // much darker red
  sideways: 'rgba(245,158,11,0.15)',   // much darker amber
};

/* ── Shared tooltip style ───────────────────────────────────────────────── */
const tooltipStyle: React.CSSProperties = {
  background: 'var(--tv-s1)', border: '1px solid var(--tv-border)',
  borderRadius: 8, color: 'var(--tv-text)', fontSize: 12,
};
const labelStyle: React.CSSProperties = { color: '#9090A8', fontSize: 11 };

/* ── Downsample helper ──────────────────────────────────────────────────── */
function downsample<T>(arr: T[], max = 600): T[] {
  if (arr.length <= max) return arr;
  const step = Math.ceil(arr.length / max);
  const out: T[] = [];
  for (let i = 0; i < arr.length; i += step) out.push(arr[i]);
  if (out[out.length - 1] !== arr[arr.length - 1]) out.push(arr[arr.length - 1]);
  return out;
}

/* ── Date formatter ─────────────────────────────────────────────────────── */
function fmtDate(ts: string) {
  try {
    const d = new Date(ts);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  } catch { return ts.slice(0, 10); }
}

/* ── Build regime periods from a list of {date, regime} sampled points ────
   Called AFTER chart data is downsampled, with dates and labels already
   aligned 1:1. x1/x2 are guaranteed to exist as data keys in the chart.  */
interface RegimePeriod { regime: 'bull' | 'bear' | 'sideways'; x1: string; x2: string; }

function buildRegimePeriods(dates: string[], labels: string[]): RegimePeriod[] {
  const n = Math.min(dates.length, labels.length);
  if (n === 0) return [];
  const periods: RegimePeriod[] = [];
  let start = 0;
  for (let i = 1; i <= n; i++) {
    if (i === n || labels[i] !== labels[start]) {
      periods.push({
        regime: labels[start] as RegimePeriod['regime'],
        x1: dates[start],
        x2: dates[Math.min(i, n - 1)],
      });
      start = i;
    }
  }
  return periods;
}

/* Sub-sample labels using the same step used to downsample the data array.
   Both use the same total-length N so they stay perfectly aligned.        */
function alignLabels(labels: string[], originalN: number, sampledN: number): string[] {
  if (!labels.length || sampledN >= originalN) return labels.slice(0, sampledN);
  const step = originalN / sampledN;           // same logic as downsample()
  const out: string[] = [];
  for (let k = 0; k < sampledN; k++) {
    out.push(labels[Math.min(Math.round(k * step), labels.length - 1)]);
  }
  return out;
}

/* ── Build OOS split info from validation ───────────────────────────────── */
interface OOSSplit {
  mode:        'holdout' | 'walk_forward';
  splitDate?:  string;          // holdout single split
  wfDates?:    string[];        // walk-forward test-period starts
}

function buildOOSSplit(validation?: ValidationData): OOSSplit | null {
  if (!validation) return null;
  if (validation.mode === 'holdout' && validation.split_date) {
    return { mode: 'holdout', splitDate: validation.split_date.slice(0, 10) };
  }
  if (validation.mode === 'walk_forward' && validation.windows?.length) {
    const dates = validation.windows.map(w =>
      w.test_period?.split('→')[0]?.trim().slice(0, 10) ?? ''
    ).filter(Boolean);
    return { mode: 'walk_forward', wfDates: dates };
  }
  return null;
}

/* ── Regime legend chip ─────────────────────────────────────────────────── */
function RegimeLegend() {
  return (
    <div className="flex items-center gap-3 text-[10px]" style={{ color: C.grey }}>
      <span className="font-semibold" style={{ color: C.dim }}>Regime:</span>
      {[
        { label: '📈 Bull',     color: 'rgba(34,197,94,0.4)'   },
        { label: '📉 Bear',     color: 'rgba(239,68,68,0.4)'   },
        { label: '↔️ Sideways', color: 'rgba(245,158,11,0.4)'  },
      ].map(r => (
        <span key={r.label} className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-sm inline-block" style={{ background: r.color }} />
          {r.label}
        </span>
      ))}
    </div>
  );
}

/* ── OOS legend chip ────────────────────────────────────────────────────── */
function OOSLegend({ split, revealed, onToggle }: { split: OOSSplit; revealed: boolean; onToggle: () => void }) {
  return (
    <div className="flex items-center gap-3 text-[10px]" style={{ color: C.grey }}>
      <span className="font-semibold" style={{ color: C.dim }}>OOS:</span>
      {split.mode === 'holdout' && (
        <>
          <span className="flex items-center gap-1">
            <span className="w-6 h-0.5 inline-block" style={{ background: C.blue }} />
            In-Sample
          </span>
          {revealed && (
            <span className="flex items-center gap-1">
              <span className="w-6 h-0.5 inline-block border-dashed border-t-2"
                style={{ borderColor: C.amber }} />
              Out-of-Sample
            </span>
          )}
          <span style={{ color: C.amber }}>
            split: {split.splitDate}
          </span>
        </>
      )}
      {split.mode === 'walk_forward' && (
        <>
          <span className="flex items-center gap-1">
            <span className="w-6 h-0.5 inline-block" style={{ background: C.blue }} />
            In-Sample
          </span>
          {revealed && (
            <span className="flex items-center gap-1">
              <span className="w-6 h-0.5 inline-block border-dashed border-t-2"
                style={{ borderColor: C.amber }} />
              Walk-Forward OOS
            </span>
          )}
          <span style={{ color: C.amber }}>
            {split.wfDates?.length} test windows — dashed lines = test-period starts
          </span>
        </>
      )}
      {/* Reveal / Hide toggle */}
      {(split.mode === 'holdout' || split.mode === 'walk_forward') && (
        <button
          onClick={onToggle}
          className="ml-2 px-3 py-1 rounded-lg text-[10px] font-bold transition-all"
          style={revealed
            ? { background: 'rgba(245,158,11,0.15)', color: C.amber, border: '1px solid rgba(245,158,11,0.3)' }
            : { background: C.amber, color: '#0A0A0F', boxShadow: '0 0 12px rgba(245,158,11,0.4)' }
          }
        >
          {revealed ? '🙈 Hide OOS' : '🔬 Reveal OOS'}
        </button>
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   Tab bar + parent
   ═══════════════════════════════════════════════════════════════════════════ */
const TABS = ['Equity', 'Drawdown', 'Distribution', 'Price+Trades', 'Monthly P&L', 'Rolling'];

interface Props {
  series:         SeriesData;
  initialCapital: number;
  currency?:      string;
  validation?:    ValidationData;
}

export default function ChartsPanel({ series, initialCapital, currency = '$', validation }: Props) {
  const [activeTab, setActiveTab] = useState(0);
  const [oosRevealed, setOosRevealed] = useState(false);
  const locale = currency === '₹' ? 'en-IN' : 'en-US';

  // Build regime periods from the same downsampled dates that EquityChart uses.
  const regimePeriods = useMemo(() => {
    const labels = series.regime_labels ?? [];
    if (!labels.length || !series.timestamps.length) return [];
    const rawDates = series.timestamps.map(ts => fmtDate(ts));
    const sampledDates = downsample(rawDates);
    const sampledLabels = alignLabels(labels, rawDates.length, sampledDates.length);
    return buildRegimePeriods(sampledDates, sampledLabels);
  }, [series.timestamps, series.regime_labels]);
  const oosSplit = useMemo(() => buildOOSSplit(validation), [validation]);

  return (
    <div className="fade-in">
      {/* Tab bar */}
      <div className="flex gap-1 mb-4 p-1 rounded-xl overflow-x-auto"
        style={{ background: 'var(--tv-bg)', border: '1px solid #23233A' }}>
        {TABS.map((t, i) => (
          <button key={t} onClick={() => setActiveTab(i)}
            className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all
              ${activeTab === i ? '' : 'hover:opacity-80'}`}
            style={activeTab === i
              ? { background: 'var(--tv-accent)', color: '#0A0A0F', boxShadow: '0 0 12px rgba(168,236,58,0.35)' }
              : { color: '#9090A8' }}
          >{t}</button>
        ))}
      </div>

      {/* Legend row */}
      <div className="flex flex-wrap gap-4 mb-3 px-1">
        {regimePeriods.length > 0 && <RegimeLegend />}
        {oosSplit && <OOSLegend split={oosSplit} revealed={oosRevealed}
          onToggle={() => setOosRevealed(r => !r)} />}
      </div>

      {/* Chart panels */}
      <div className="rounded-xl p-4" style={{ background: 'var(--tv-bg)', border: '1px solid #23233A' }}>
        {activeTab === 0 && (
          <EquityChart series={series} initialCapital={initialCapital}
            currency={currency} locale={locale}
            regimePeriods={regimePeriods} oosSplit={oosSplit}
            oosRevealed={oosRevealed} validation={validation} />
        )}
        {activeTab === 1 && (
          <DrawdownChart series={series}
            regimePeriods={regimePeriods} oosSplit={oosSplit}
            oosRevealed={oosRevealed} validation={validation} />
        )}
        {activeTab === 2 && <DistributionChart trades={series.trades} />}
        {activeTab === 3 && (
          <PriceTradesChart series={series} currency={currency} locale={locale}
            regimePeriods={regimePeriods} oosSplit={oosSplit}
            oosRevealed={oosRevealed} validation={validation} />
        )}
        {activeTab === 4 && <MonthlyHeatmap  series={series} currency={currency} />}
        {activeTab === 5 && <RollingChart    series={series} regimePeriods={regimePeriods} />}
      </div>
    </div>
  );
}


/* NOTE: RegimeBands wrapper removed — Recharts only recognises its own
   component types as direct children. Wrap them in a custom component and
   Recharts silently drops them. ReferenceArea elements must be inlined
   directly inside each chart as siblings, not inside a wrapper.           */

/** Render OOS split line(s) inside any chart */
function OOSSplitLines({ split, label = true }: { split: OOSSplit | null; label?: boolean }) {
  if (!split) return null;
  if (split.mode === 'holdout' && split.splitDate) {
    return (
      <ReferenceLine x={split.splitDate} stroke={C.amber}
        strokeDasharray="5 3" strokeWidth={1.5}
        label={label ? {
          value: '🔬 OOS →',
          position: 'insideTopLeft',
          fill: C.amber, fontSize: 10, fontWeight: 700,
          dy: -4,
        } : undefined}
      />
    );
  }
  if (split.mode === 'walk_forward' && split.wfDates?.length) {
    return (
      <>
        {split.wfDates.map((d, i) => (
          <ReferenceLine key={i} x={d} stroke={C.amber}
            strokeDasharray="3 4" strokeWidth={1} opacity={0.6}
            label={i === 0 && label ? {
              value: `WF-${i + 1}`,
              position: 'insideTopLeft',
              fill: C.amber, fontSize: 9,
            } : undefined}
          />
        ))}
      </>
    );
  }
  return null;
}


/* ═══════════════════════════════════════════════════════════════════════════
   1. Equity Curve
   ═══════════════════════════════════════════════════════════════════════════ */
function EquityChart({
  series, initialCapital, currency = '$', locale = 'en-US',
  regimePeriods, oosSplit, oosRevealed = false, validation,
}: {
  series: SeriesData; initialCapital: number; currency?: string; locale?: string;
  regimePeriods: RegimePeriod[]; oosSplit: OOSSplit | null; oosRevealed?: boolean;
  validation?: ValidationData;
}) {
  const hasValidation = !!validation && !!validation.validation_equity_curve?.length;
  const splitDate = validation?.mode === 'holdout'
    ? validation.split_date?.slice(0, 10)
    : validation?.windows?.[0]?.test_period?.split('→')[0]?.trim().slice(0, 10);

  const { data, splitIdx } = useMemo(() => {
    const eqCurve = hasValidation ? validation.validation_equity_curve! : series.equity_curve;
    const timestamps = hasValidation ? validation.validation_timestamps! : series.timestamps;

    const raw = eqCurve.map((v, i) => ({
      date:   fmtDate(timestamps[i] ?? ''),
      equity: Math.round(v * 100) / 100,
    }));
    const pts = downsample(raw);

    // Find split index for holdout two-color rendering
    let si = -1;
    if (splitDate) {
      si = pts.findIndex(d => d.date >= splitDate);
    }

    // When OOS is NOT revealed, clip data at split point
    const visible = splitDate && !oosRevealed && si > 0
      ? pts.slice(0, si + 1)
      : pts;

    // Annotate each point with IS and OOS equity keys (null outside window)
    const annotated = visible.map((d, i) => ({
      ...d,
      equityIS:  si === -1 || i <= si ? d.equity : null,
      equityOOS: si !== -1 && i >= si && oosRevealed ? d.equity : null,
    }));

    return { data: annotated, splitIdx: si };
  }, [series, hasValidation, validation, splitDate, oosRevealed]);

  // For the header: show IS-only return when OOS is hidden
  const isLast = splitDate && !oosRevealed && splitIdx > 0
    ? data[data.length - 1]?.equity ?? initialCapital
    : data[data.length - 1]?.equity ?? initialCapital;
  const retPct = ((isLast - initialCapital) / initialCapital) * 100;
  const color  = retPct >= 0 ? C.green : C.red;

  return (
    <div style={{ position: 'relative' }}>
      <div className="flex items-baseline gap-3 mb-3">
        <h3 className="text-sm font-semibold" style={{ color: C.text }}>Equity Curve</h3>
        <span className="text-sm font-bold" style={{ color }}>
          {retPct >= 0 ? '+' : ''}{retPct.toFixed(2)}%
        </span>
        <span className="text-xs" style={{ color: C.grey }}>
          {currency}{isLast.toLocaleString(locale, { maximumFractionDigits: 0 })} final
          {splitDate && !oosRevealed && ' (in-sample only)'}
        </span>
        {validation?.mode === 'holdout' && (
          <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
            style={{ background: 'rgba(245,158,11,0.15)', color: C.amber, border: '1px solid rgba(245,158,11,0.3)' }}>
            {oosRevealed ? '🔬 Holdout — IS + OOS' : '🔒 OOS Hidden'}
          </span>
        )}
        {validation?.mode === 'walk_forward' && (
          <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
            style={{ background: 'rgba(245,158,11,0.15)', color: C.amber, border: '1px solid rgba(245,158,11,0.3)' }}>
            {oosRevealed ? `🔬 Walk-Fwd (${validation.num_windows} windows) — IS + OOS` : '🔒 OOS Hidden'}
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={380}>
        <AreaChart data={data} margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
          <defs>
            <linearGradient id="eqGradIS" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.blue}  stopOpacity={0.25} />
              <stop offset="95%" stopColor={C.blue}  stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id="eqGradOOS" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.amber} stopOpacity={0.30} />
              <stop offset="95%" stopColor={C.amber} stopOpacity={0.03} />
            </linearGradient>
          </defs>

          {/* Regime background bands */}
          {regimePeriods.map((p, i) => (
            <ReferenceArea key={`rb-${i}`} x1={p.x1} x2={p.x2}
              fill={REGIME_FILL[p.regime]} stroke="none" />
          ))}

          {/* OOS region shading (amber wash behind OOS data — only when revealed) */}
          {splitDate && oosRevealed && (
            <ReferenceArea
              x1={splitDate}
              x2={data[data.length - 1]?.date}
              fill="rgba(245,158,11,0.08)"
              stroke="none"
            />
          )}

          <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fill: C.grey, fontSize: 11 }} tickCount={8} />
          <YAxis tick={{ fill: C.grey, fontSize: 11 }}
            tickFormatter={v => `${currency}${(v / 1000).toFixed(0)}k`} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={labelStyle}
            formatter={(v: number, name: string) => [
              `${currency}${v.toLocaleString(locale, { maximumFractionDigits: 2 })}`,
              name === 'equityOOS' ? '📊 OOS Portfolio' : name === 'equityIS' ? '📊 Portfolio' : 'Portfolio',
            ]}
          />
          <Legend wrapperStyle={{ color: C.grey, fontSize: 11 }} />

          {/* Reference lines */}
          <ReferenceLine y={initialCapital} stroke={C.grey} strokeDasharray="4 4"
            label={{ value: 'Start', fill: C.grey, fontSize: 10, position: 'insideTopLeft' }} />
          {oosRevealed && <OOSSplitLines split={oosSplit} />}

          {/* Equity area(s) */}
          {splitDate && oosRevealed ? (
            <>
              <Area type="monotone" dataKey="equityIS" name="In-Sample"
                stroke={C.accent} strokeWidth={2}
                fill="url(#eqGradIS)" dot={false} activeDot={{ r: 4, fill: C.accent }}
                connectNulls={false} legendType="line" />
              <Area type="monotone" dataKey="equityOOS" name="Out-of-Sample"
                stroke={C.amber} strokeWidth={2}
                fill="url(#eqGradOOS)" dot={false} activeDot={{ r: 4, fill: C.amber }}
                connectNulls={false} legendType="line" />
            </>
          ) : (
            <Area type="monotone" dataKey={splitDate ? 'equityIS' : 'equity'} name="Portfolio"
              stroke={C.accent} strokeWidth={2}
              fill="url(#eqGradIS)" dot={false} activeDot={{ r: 4, fill: C.accent }} />
          )}
        </AreaChart>
      </ResponsiveContainer>

      {/* OOS masked overlay — shown when validation is active but not revealed */}
      {splitDate && !oosRevealed && (
        <div style={{
          position: 'absolute',
          top: 40, right: 0,
          width: '30%', height: 'calc(100% - 40px)',
          background: 'linear-gradient(90deg, transparent 0%, rgba(10,10,15,0.85) 30%, rgba(10,10,15,0.95) 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderRadius: '0 12px 12px 0',
          pointerEvents: 'none',
        }}>
          <div style={{ textAlign: 'center', pointerEvents: 'none' }}>
            <div style={{ fontSize: 28, marginBottom: 4 }}>🔒</div>
            <div style={{ color: C.amber, fontSize: 11, fontWeight: 700, letterSpacing: '0.05em' }}>
              OOS DATA HIDDEN
            </div>
            <div style={{ color: C.dim, fontSize: 10, marginTop: 2 }}>
              Click "Reveal OOS" above
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
/* ═══════════════════════════════════════════════════════════════════════════
   2. Drawdown
   ═══════════════════════════════════════════════════════════════════════════ */
function DrawdownChart({
  series, regimePeriods, oosSplit, oosRevealed = false, validation,
}: {
  series: SeriesData; regimePeriods: RegimePeriod[]; oosSplit: OOSSplit | null; oosRevealed?: boolean;
  validation?: ValidationData;
}) {
  const hasValidation = !!validation && !!validation.validation_drawdowns?.length;
  const splitDate = validation?.mode === 'holdout'
    ? validation.split_date?.slice(0, 10)
    : validation?.windows?.[0]?.test_period?.split('→')[0]?.trim().slice(0, 10);

  const data = useMemo(() => {
    const ddCurve = hasValidation ? validation.validation_drawdowns! : series.drawdowns;
    const timestamps = hasValidation ? validation.validation_timestamps! : series.timestamps;

    const all = downsample(ddCurve.map((v, i) => ({
      date: fmtDate(timestamps[i] ?? ''),
      dd:   Math.round(v * 100) / 100,
    })));
    if (splitDate && !oosRevealed) {
      const si = all.findIndex(d => d.date >= splitDate);
      if (si > 0) return all.slice(0, si + 1);
    }
    return all;
  }, [series, hasValidation, validation, splitDate, oosRevealed]);

  const maxDd = Math.min(...data.map(d => d.dd));

  return (
    <div style={{ position: 'relative' }}>
      <div className="flex items-baseline gap-3 mb-3">
        <h3 className="text-sm font-semibold" style={{ color: C.text }}>Drawdown</h3>
        <span className="text-sm font-bold" style={{ color: C.red }}>Max: {maxDd.toFixed(2)}%</span>
        {splitDate && !oosRevealed && (
          <span className="text-[10px]" style={{ color: C.dim }}>(in-sample only)</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={data} margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
          <defs>
            <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.red} stopOpacity={0.3} />
              <stop offset="95%" stopColor={C.red} stopOpacity={0.03} />
            </linearGradient>
          </defs>
          {regimePeriods.map((p, i) => (
            <ReferenceArea key={`rb-${i}`} x1={p.x1} x2={p.x2}
              fill={REGIME_FILL[p.regime]} stroke="none" />
          ))}
          {splitDate && oosRevealed && (
            <ReferenceArea
              x1={splitDate}
              x2={data[data.length - 1]?.date}
              fill="rgba(245,158,11,0.08)"
              stroke="none"
            />
          )}
          <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fill: C.grey, fontSize: 11 }} tickCount={8} />
          <YAxis tick={{ fill: C.grey, fontSize: 11 }} tickFormatter={v => `${v}%`} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={labelStyle}
            formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']} />
          <ReferenceLine y={0} stroke={C.grey} strokeDasharray="4 4" />
          {oosRevealed && <OOSSplitLines split={oosSplit} />}
          <Area type="monotone" dataKey="dd" name="Drawdown"
            stroke={C.red} strokeWidth={1.5} fill="url(#ddGrad)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>

      {/* OOS mask overlay */}
      {splitDate && !oosRevealed && (
        <div style={{
          position: 'absolute', top: 40, right: 0,
          width: '30%', height: 'calc(100% - 40px)',
          background: 'linear-gradient(90deg, transparent 0%, rgba(10,10,15,0.85) 30%, rgba(10,10,15,0.95) 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderRadius: '0 12px 12px 0', pointerEvents: 'none',
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 22, marginBottom: 2 }}>🔒</div>
            <div style={{ color: C.amber, fontSize: 10, fontWeight: 700 }}>OOS HIDDEN</div>
          </div>
        </div>
      )}
    </div>
  );
}
/* ═══════════════════════════════════════════════════════════════════════════
   3. Trade Return Distribution (unchanged — no regime bands needed here)
   ═══════════════════════════════════════════════════════════════════════════ */
function DistributionChart({ trades }: { trades: Trade[] }) {
  const data = useMemo(() => {
    if (!trades.length) return [];
    const pcts = trades.map(t => t.pnl_pct * 100);
    const mn = Math.min(...pcts), mx = Math.max(...pcts);
    if (mn === mx) return [{ bucket: `${mn.toFixed(1)}%`, winners: 0, losers: 0, count: trades.length }];
    const BINS = 15;
    const step = (mx - mn) / BINS;
    const bins: { label: string; min: number; max: number }[] = [];
    for (let i = 0; i < BINS; i++) {
      bins.push({ label: `${(mn + i * step).toFixed(1)}%`, min: mn + i * step, max: mn + (i + 1) * step });
    }
    return bins.map(b => ({
      bucket:  b.label,
      winners: pcts.filter(p => p >= b.min && p < b.max && p >= 0).length,
      losers:  pcts.filter(p => p >= b.min && p < b.max && p < 0).length,
    })).filter(b => b.winners + b.losers > 0);
  }, [trades]);

  if (!data.length) return <EmptyChart msg="No completed trades for distribution" />;

  return (
    <div>
      <h3 className="text-sm font-semibold mb-4" style={{ color: C.text }}>Trade Return Distribution</h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} barCategoryGap="10%" margin={{ top: 10, right: 20, left: 20, bottom: 40 }}>
          <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="bucket" tick={{ fill: C.grey, fontSize: 10 }} angle={-45} textAnchor="end" />
          <YAxis tick={{ fill: C.grey, fontSize: 11 }} allowDecimals={false} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={labelStyle}
            formatter={(v: number, name: string) => [v, name === 'winners' ? 'Winners' : 'Losers']} />
          <Legend wrapperStyle={{ color: C.grey, fontSize: 11 }} />
          <Bar dataKey="winners" name="Winners" fill={C.green} opacity={0.85} radius={[3,3,0,0]} />
          <Bar dataKey="losers"  name="Losers"  fill={C.red}   opacity={0.85} radius={[3,3,0,0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   4. Price + Trades
   ═══════════════════════════════════════════════════════════════════════════ */
function PriceTradesChart({
  series, currency = '$', locale = 'en-US', regimePeriods, oosSplit, oosRevealed = false, validation,
}: {
  series: SeriesData; currency?: string; locale?: string;
  regimePeriods: RegimePeriod[]; oosSplit: OOSSplit | null; oosRevealed?: boolean;
  validation?: ValidationData;
}) {
  const splitDate = validation?.mode === 'holdout'
    ? validation.split_date?.slice(0, 10)
    : validation?.windows?.[0]?.test_period?.split('→')[0]?.trim().slice(0, 10);

  const { priceData, entries, exits } = useMemo(() => {
    const prices = series.close_prices.length > 0 ? series.close_prices : series.equity_curve;
    const raw = prices.map((v, i) => ({
      date:  fmtDate(series.timestamps[i] ?? ''),
      price: Math.round(v * 100) / 100,
      ts:    series.timestamps[i] ?? '',
    }));
    let sampled = downsample(raw);

    // Clip at split point when OOS hidden
    if (splitDate && !oosRevealed) {
      const si = sampled.findIndex(d => d.date >= splitDate);
      if (si > 0) sampled = sampled.slice(0, si + 1);
    }

    const tsSet = new Set(sampled.map(d => d.ts));
    const entries: { date: string; price: number }[] = [];
    const exits:   { date: string; price: number }[] = [];
    series.trades.forEach(t => {
      const ets = t.entry_time?.slice(0, 10);
      const idx = series.timestamps.findIndex(ts => ts.startsWith(ets ?? ''));
      if (idx >= 0 && tsSet.has(series.timestamps[idx])) {
        const d = fmtDate(t.entry_time);
        if (!splitDate || oosRevealed || d < splitDate)
          entries.push({ date: d, price: prices[idx] });
      }
      if (t.exit_time) {
        const exts = t.exit_time.slice(0, 10);
        const exi  = series.timestamps.findIndex(ts => ts.startsWith(exts));
        if (exi >= 0 && tsSet.has(series.timestamps[exi])) {
          const d = fmtDate(t.exit_time);
          if (!splitDate || oosRevealed || d < splitDate)
            exits.push({ date: d, price: prices[exi] });
        }
      }
    });
    return { priceData: sampled, entries, exits };
  }, [series, splitDate, oosRevealed]);

  const yKey = series.close_prices.length > 0 ? `Price (${currency})` : `Equity (${currency})`;

  return (
    <div style={{ position: 'relative' }}>
      <div className="flex items-center gap-4 mb-4">
        <h3 className="text-sm font-semibold" style={{ color: C.text }}>
          {series.close_prices.length > 0 ? 'Price Chart with Trades' : 'Equity with Trades'}
        </h3>
        <span className="text-xs px-2 py-0.5 rounded-full border border-[#2D3748]" style={{ color: C.green }}>▲ {entries.length} entries</span>
        <span className="text-xs px-2 py-0.5 rounded-full border border-[#2D3748]" style={{ color: C.red }}>▼ {exits.length} exits</span>
        {splitDate && !oosRevealed && (
          <span className="text-[10px]" style={{ color: C.dim }}>(in-sample only)</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={400}>
        <ComposedChart margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
          {regimePeriods.map((p, i) => (
            <ReferenceArea key={`rb-${i}`} x1={p.x1} x2={p.x2}
              fill={REGIME_FILL[p.regime]} stroke="none" />
          ))}
          {splitDate && oosRevealed && (
            <ReferenceArea
              x1={splitDate}
              x2={priceData[priceData.length - 1]?.date}
              fill="rgba(245,158,11,0.08)"
              stroke="none"
            />
          )}
          <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
          <XAxis dataKey="date" type="category" allowDuplicatedCategory={false}
            tick={{ fill: C.grey, fontSize: 11 }} tickCount={8} />
          <YAxis tick={{ fill: C.grey, fontSize: 11 }}
            tickFormatter={v => v > 10000 ? `${currency}${(v/1000).toFixed(0)}k` : `${currency}${v.toFixed(0)}`} />
          <Tooltip contentStyle={tooltipStyle} labelStyle={labelStyle}
            formatter={(v: number) => [`${currency}${v.toLocaleString(locale, { maximumFractionDigits: 2 })}`, yKey]} />
          <Legend wrapperStyle={{ color: C.grey, fontSize: 11 }} />
          {oosRevealed && <OOSSplitLines split={oosSplit} />}
          <Line data={priceData} type="monotone" dataKey="price" name={yKey}
            stroke={C.grey} strokeWidth={1.5} dot={false} legendType="line" />
          <Scatter data={entries} name="BUY Entry" dataKey="price" fill={C.green} />
          <Scatter data={exits}   name="SELL Exit" dataKey="price" fill={C.red}   />
        </ComposedChart>
      </ResponsiveContainer>

      {/* OOS mask overlay */}
      {splitDate && !oosRevealed && (
        <div style={{
          position: 'absolute', top: 40, right: 0,
          width: '30%', height: 'calc(100% - 40px)',
          background: 'linear-gradient(90deg, transparent 0%, rgba(10,10,15,0.85) 30%, rgba(10,10,15,0.95) 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderRadius: '0 12px 12px 0', pointerEvents: 'none',
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 22, marginBottom: 2 }}>🔒</div>
            <div style={{ color: C.amber, fontSize: 10, fontWeight: 700 }}>OOS HIDDEN</div>
          </div>
        </div>
      )}
    </div>
  );
}
/* ═══════════════════════════════════════════════════════════════════════════
   5. Monthly P&L Heatmap (unchanged)
   ═══════════════════════════════════════════════════════════════════════════ */
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function MonthlyHeatmap({ series, currency = '$' }: { series: SeriesData; currency?: string }) {
  const { years, pivot } = useMemo(() => {
    const pnlMap: Record<string, number> = {};
    if (series.trades.length) {
      series.trades.forEach(t => {
        try {
          const d = new Date(t.exit_time ?? t.entry_time);
          const key = `${d.getFullYear()}-${d.getMonth() + 1}`;
          pnlMap[key] = (pnlMap[key] ?? 0) + t.pnl;
        } catch { /* */ }
      });
    } else {
      const eq = series.equity_curve;
      const ts = series.timestamps;
      const monthly: Record<string, number[]> = {};
      eq.forEach((v, i) => {
        try {
          const d = new Date(ts[i]);
          const k = `${d.getFullYear()}-${d.getMonth() + 1}`;
          if (!monthly[k]) monthly[k] = [];
          monthly[k].push(v);
        } catch { /* */ }
      });
      const sorted = Object.keys(monthly).sort();
      let prev = eq[0];
      sorted.forEach(k => {
        const last = monthly[k][monthly[k].length - 1];
        pnlMap[k] = last - prev;
        prev = last;
      });
    }
    const allYears = [...new Set(Object.keys(pnlMap).map(k => +k.split('-')[0]))].sort();
    const pivot: Record<number, Record<number, number>> = {};
    allYears.forEach(y => {
      pivot[y] = {};
      for (let m = 1; m <= 12; m++) pivot[y][m] = pnlMap[`${y}-${m}`] ?? 0;
    });
    return { years: allYears, pivot };
  }, [series]);

  if (!years.length) return <EmptyChart msg="Insufficient data for monthly heatmap" />;
  const allVals = years.flatMap(y => Object.values(pivot[y]));
  const maxAbs  = Math.max(...allVals.map(Math.abs), 1);
  const cellColor = (v: number) => {
    if (v === 0) return 'var(--tv-bg)';
    const t = Math.min(Math.abs(v) / maxAbs, 1);
    const alpha = 0.15 + t * 0.65;
    return v > 0 ? `rgba(168,236,58,${alpha})` : `rgba(239,68,68,${alpha})`;
  };

  return (
    <div>
      <h3 className="text-sm font-semibold mb-4" style={{ color: C.text }}>Monthly P&L Heatmap</h3>
      <div className="overflow-x-auto">
        <table className="text-xs w-full border-collapse">
          <thead>
            <tr>
              <th className="px-2 py-1.5 text-left" style={{ color: C.grey, width: 50 }}>Year</th>
              {MONTH_NAMES.map(m => (
                <th key={m} className="px-1 py-1.5 text-center font-semibold" style={{ color: C.grey }}>{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {years.map(y => (
              <tr key={y}>
                <td className="px-2 py-1 font-semibold" style={{ color: C.text }}>{y}</td>
                {MONTH_NAMES.map((_, mi) => {
                  const v = pivot[y][mi + 1] ?? 0;
                  return (
                    <td key={mi} className="px-0.5 py-0.5">
                      <div
                        title={`${y} ${MONTH_NAMES[mi]}: ${currency}${v.toFixed(2)}`}
                        className="text-center py-1.5 rounded text-[10px] font-medium cursor-default transition-opacity hover:opacity-80"
                        style={{
                          background: cellColor(v),
                          color: Math.abs(v) > maxAbs * 0.3 ? C.text : C.grey,
                          minWidth: 38,
                        }}>
                        {v !== 0 ? (v > 0 ? '+' : '') + (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)) : '—'}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-3 mt-3 text-[10px]" style={{ color: C.grey }}>
        {[['rgba(239,68,68,0.6)','Loss'],['#0F0F17 border border-[#23233A]','Flat'],['rgba(168,236,58,0.6)','Profit']].map(([bg,label]) => (
          <div key={label} className="flex items-center gap-1.5">
            <div className="w-8 h-3 rounded" style={{ background: bg.includes('border') ? 'var(--tv-bg)' : bg, border: bg.includes('border') ? '1px solid #23233A' : undefined }}></div>
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   6. Rolling Metrics (Sharpe + Drawdown) — now with regime bands
   ═══════════════════════════════════════════════════════════════════════════ */
function RollingChart({ series, regimePeriods }: { series: SeriesData; regimePeriods: RegimePeriod[] }) {
  const data = useMemo(() => {
    const eq = series.equity_curve;
    if (eq.length < 30) return [];
    const WINDOW = Math.min(30, Math.floor(eq.length / 3));
    const pts: { date: string; sharpe: number; dd: number }[] = [];
    let runMax = eq[0];
    for (let i = 1; i < eq.length; i++) {
      if (eq[i] > runMax) runMax = eq[i];
      if (i < WINDOW) continue;
      const slice = eq.slice(i - WINDOW, i);
      const rets  = slice.slice(1).map((v, j) => (v - slice[j]) / slice[j]).filter(r => isFinite(r));
      const mean  = rets.reduce((a, b) => a + b, 0) / rets.length;
      const std   = Math.sqrt(rets.map(r => (r - mean) ** 2).reduce((a, b) => a + b, 0) / rets.length);
      const sharpe = std > 1e-10 ? (mean / std) * Math.sqrt(252) : 0;
      const dd     = runMax > 0 ? (eq[i] - runMax) / runMax * 100 : 0;
      pts.push({ date: fmtDate(series.timestamps[i] ?? ''), sharpe: +sharpe.toFixed(3), dd: +dd.toFixed(3) });
    }
    return downsample(pts, 400);
  }, [series]);

  if (!data.length) return <EmptyChart msg="Need 30+ candles for rolling metrics" />;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold" style={{ color: C.text }}>Rolling Risk Metrics (30-candle window)</h3>

      <div>
        <p className="text-xs mb-2" style={{ color: C.grey }}>Rolling Sharpe Ratio</p>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={data} margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
            <defs>
              <linearGradient id="sharpeGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={C.blue} stopOpacity={0.2} />
                <stop offset="95%" stopColor={C.blue} stopOpacity={0.0} />
              </linearGradient>
            </defs>
            {regimePeriods.map((p, i) => (
              <ReferenceArea key={`rb-${i}`} x1={p.x1} x2={p.x2}
                fill={REGIME_FILL[p.regime]} stroke="none" />
            ))}
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fill: C.grey, fontSize: 10 }} tickCount={6} />
            <YAxis tick={{ fill: C.grey, fontSize: 10 }} />
            <Tooltip contentStyle={tooltipStyle} labelStyle={labelStyle}
              formatter={(v: number) => [v.toFixed(2), 'Sharpe']} />
            <ReferenceLine y={1} stroke={C.green} strokeDasharray="3 3" />
            <ReferenceLine y={0} stroke={C.grey}  strokeDasharray="2 2" />
            <Area type="monotone" dataKey="sharpe" stroke={C.blue} fill="url(#sharpeGrad)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div>
        <p className="text-xs mb-2" style={{ color: C.grey }}>Running Drawdown (%)</p>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={data} margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
            <defs>
              <linearGradient id="rddGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={C.red} stopOpacity={0.25} />
                <stop offset="95%" stopColor={C.red} stopOpacity={0.0} />
              </linearGradient>
            </defs>
            {regimePeriods.map((p, i) => (
              <ReferenceArea key={`rb-${i}`} x1={p.x1} x2={p.x2}
                fill={REGIME_FILL[p.regime]} stroke="none" />
            ))}
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fill: C.grey, fontSize: 10 }} tickCount={6} />
            <YAxis tick={{ fill: C.grey, fontSize: 10 }} tickFormatter={v => `${v}%`} />
            <Tooltip contentStyle={tooltipStyle} labelStyle={labelStyle}
              formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']} />
            <ReferenceLine y={0} stroke={C.grey} strokeDasharray="2 2" />
            <Area type="monotone" dataKey="dd" stroke={C.red} fill="url(#rddGrad)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}


/* ── Empty chart placeholder ─────────────────────────────────────────────── */
function EmptyChart({ msg }: { msg: string }) {
  return (
    <div className="flex items-center justify-center h-40 rounded-xl"
      style={{ border: '1px dashed #23233A' }}>
      <p className="text-sm" style={{ color: C.grey }}>{msg}</p>
    </div>
  );
}
