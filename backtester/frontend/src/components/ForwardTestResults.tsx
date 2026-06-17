import React, { useState } from 'react';
import { ForecastResponse, ForecastCompareResult, RegimeDistribution } from '../types';
import MCPathsCanvas, { MCRun } from './MCPathsCanvas';

// ── Helpers ────────────────────────────────────────────────────────────────────

function sign(n: number, d = 2): string {
  return (n >= 0 ? '+' : '') + n.toFixed(d);
}

function MetricPill({
  label, value, color = 'text-gray-800', sub,
}: { label: string; value: React.ReactNode; color?: string; sub?: string }) {
  return (
    <div className="flex flex-col items-center bg-gray-50 rounded-2xl px-4 py-3 text-center">
      <p className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-gray-300 mt-0.5">{sub}</p>}
    </div>
  );
}

function Pcts({ label, pcts }: { label: string; pcts: { p5: number; p50: number; p95: number; worst?: number; best?: number } }) {
  const good = pcts.p50 >= 0;
  return (
    <div className="bg-gray-50 rounded-2xl p-4">
      <p className="text-xs font-semibold text-gray-500 mb-2">{label}</p>
      <div className="flex gap-3 justify-between text-center">
        {[
          { l: 'Worst', v: pcts.worst },
          { l: 'P5',    v: pcts.p5   },
          { l: 'P50',   v: pcts.p50  },
          { l: 'P95',   v: pcts.p95  },
          { l: 'Best',  v: pcts.best },
        ].filter(x => x.v != null).map(({ l, v }) => (
          <div key={l}>
            <p className="text-[10px] text-gray-400 mb-0.5">{l}</p>
            <p className={`text-sm font-bold tabular-nums ${(v ?? 0) >= 0 ? (good ? 'text-teal-600' : 'text-gray-600') : 'text-red-500'}`}>
              {typeof v === 'number' ? sign(v) : '—'}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Regime Distribution Bar ────────────────────────────────────────────────────

function RegimeBar({ dist }: { dist: RegimeDistribution }) {
  const total = dist.bull + dist.bear + dist.sideways;
  if (total === 0) return null;
  const dominant = dist.bull >= dist.bear && dist.bull >= dist.sideways ? 'bull'
    : dist.bear >= dist.sideways ? 'bear' : 'sideways';
  const label = dominant === 'bull' ? 'Mostly Bullish' : dominant === 'bear' ? 'Mostly Bearish' : 'Mostly Sideways';

  return (
    <div className="bg-gray-50 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-gray-500">Regime Forecast across Paths</p>
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
          dominant === 'bull' ? 'bg-teal-50 text-teal-700' :
          dominant === 'bear' ? 'bg-red-50 text-red-600' :
          'bg-yellow-50 text-yellow-700'
        }`}>{label}</span>
      </div>
      {/* Stacked bar */}
      <div className="flex rounded-full overflow-hidden h-3 mb-2">
        {dist.bull > 0 && (
          <div className="bg-teal-400 transition-all" style={{ width: `${dist.bull}%` }} title={`Bull ${dist.bull}%`} />
        )}
        {dist.sideways > 0 && (
          <div className="bg-yellow-400 transition-all" style={{ width: `${dist.sideways}%` }} title={`Sideways ${dist.sideways}%`} />
        )}
        {dist.bear > 0 && (
          <div className="bg-red-400 transition-all" style={{ width: `${dist.bear}%` }} title={`Bear ${dist.bear}%`} />
        )}
      </div>
      <div className="flex gap-4 text-[10px] font-semibold">
        <span className="text-teal-600">● Bull {dist.bull}%</span>
        <span className="text-yellow-600">● Sideways {dist.sideways}%</span>
        <span className="text-red-500">● Bear {dist.bear}%</span>
      </div>
    </div>
  );
}

// ── Price Path Spaghetti (UC-3 synthetic market view) ─────────────────────────

function PriceSpaghetti({ runs, horizon }: {
  runs: { run_idx: number; return_pct: number; price_pct: number[] }[];
  horizon: number;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const [hovered, setHovered] = React.useState<{ x: number; y: number; ret: number } | null>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || runs.length === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext('2d')!;
    ctx.scale(dpr, dpr);

    // Value range
    const allVals = runs.flatMap(r => r.price_pct);
    const minV = Math.min(...allVals, -5);
    const maxV = Math.max(...allVals,  5);
    const range = maxV - minV || 1;
    const pad = { t: 16, b: 24, l: 40, r: 12 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    ctx.clearRect(0, 0, W, H);

    // Zero line
    const y0 = pad.t + (1 - (0 - minV) / range) * plotH;
    ctx.beginPath(); ctx.strokeStyle = '#d1d5db'; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
    ctx.moveTo(pad.l, y0); ctx.lineTo(W - pad.r, y0); ctx.stroke();
    ctx.setLineDash([]);

    // Paths
    for (const r of runs) {
      const pts = r.price_pct;
      if (pts.length < 2) continue;
      const ret = r.return_pct;
      const norm = Math.max(-1, Math.min(1, ret / 50));
      const hue  = norm >= 0 ? 168 : 0;
      const sat  = 60 + Math.abs(norm) * 30;
      ctx.beginPath();
      ctx.strokeStyle = `hsla(${hue},${sat}%,48%,0.25)`;
      ctx.lineWidth = 1;
      pts.forEach((v, i) => {
        const x = pad.l + (i / (pts.length - 1)) * plotW;
        const y = pad.t + (1 - (v - minV) / range) * plotH;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    // Y-axis labels
    ctx.fillStyle = '#9ca3af'; ctx.font = '9px system-ui'; ctx.textAlign = 'right';
    [minV, 0, maxV].forEach(v => {
      const y = pad.t + (1 - (v - minV) / range) * plotH;
      ctx.fillText(`${v >= 0 ? '+' : ''}${v.toFixed(0)}%`, pad.l - 4, y + 3);
    });

    // X-axis label
    ctx.textAlign = 'center'; ctx.fillStyle = '#9ca3af'; ctx.font = '9px system-ui';
    ctx.fillText(`${horizon}d horizon`, pad.l + plotW / 2, H - 4);
  }, [runs, horizon]);

  return (
    <div className="relative">
      <canvas ref={canvasRef} style={{ width: '100%', height: 200 }} className="rounded-xl" />
      {hovered && (
        <div className="absolute pointer-events-none bg-white border border-gray-100 shadow-md rounded-lg px-2 py-1 text-xs"
          style={{ left: hovered.x + 8, top: hovered.y - 20 }}>
          {sign(hovered.ret)}%
        </div>
      )}
    </div>
  );
}

// ── Method comparison panel (UC-7) ────────────────────────────────────────────

function ComparePanel({ compare }: { compare: ForecastCompareResult }) {
  const { bootstrap: bs, kronos: kr } = compare;
  if (!kr) return null;

  const rows: { label: string; bs: string; kr: string; better?: 'bs' | 'kr' | 'same' }[] = [
    {
      label: 'Median Return',
      bs: `${sign(bs.return_pct.p50)}%`,
      kr: `${sign(kr.return_pct.p50)}%`,
      better: kr.return_pct.p50 > bs.return_pct.p50 ? 'kr' : kr.return_pct.p50 < bs.return_pct.p50 ? 'bs' : 'same',
    },
    {
      label: 'P5 Return (tail)',
      bs: `${sign(bs.return_pct.p5)}%`,
      kr: `${sign(kr.return_pct.p5)}%`,
      better: kr.return_pct.p5 > bs.return_pct.p5 ? 'kr' : 'bs',
    },
    {
      label: 'P95 Return (upside)',
      bs: `${sign(bs.return_pct.p95)}%`,
      kr: `${sign(kr.return_pct.p95)}%`,
      better: kr.return_pct.p95 > bs.return_pct.p95 ? 'kr' : 'bs',
    },
    {
      label: 'Median Sharpe',
      bs: bs.sharpe.p50.toFixed(3),
      kr: kr.sharpe.p50.toFixed(3),
      better: kr.sharpe.p50 > bs.sharpe.p50 ? 'kr' : 'bs',
    },
    {
      label: 'Median Max DD',
      bs: `${bs.max_dd_pct.p50.toFixed(1)}%`,
      kr: `${kr.max_dd_pct.p50.toFixed(1)}%`,
      better: kr.max_dd_pct.p50 < bs.max_dd_pct.p50 ? 'kr' : 'bs',
    },
    {
      label: 'Forward Survival',
      bs: `${bs.forward_survival_pct.toFixed(0)}%`,
      kr: `${kr.forward_survival_pct.toFixed(0)}%`,
      better: kr.forward_survival_pct > bs.forward_survival_pct ? 'kr' : 'bs',
    },
  ];

  return (
    <div className="bg-gray-50 rounded-2xl p-4">
      <p className="text-xs font-semibold text-gray-500 mb-3">Kronos AI vs Statistical Bootstrap</p>
      <div className="overflow-auto rounded-xl border border-gray-100">
        <table className="w-full text-xs border-collapse">
          <thead className="bg-white sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left text-[10px] uppercase text-gray-400 font-semibold">Metric</th>
              <th className="px-3 py-2 text-center text-[10px] uppercase text-indigo-500 font-semibold">Bootstrap</th>
              <th className="px-3 py-2 text-center text-[10px] uppercase text-teal-600 font-semibold">Kronos AI</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rows.map(r => (
              <tr key={r.label} className="hover:bg-white transition-colors">
                <td className="px-3 py-2 text-gray-600 font-medium">{r.label}</td>
                <td className={`px-3 py-2 text-center font-semibold tabular-nums ${r.better === 'bs' ? 'text-indigo-600' : 'text-gray-500'}`}>
                  {r.bs}{r.better === 'bs' && ' ✓'}
                </td>
                <td className={`px-3 py-2 text-center font-semibold tabular-nums ${r.better === 'kr' ? 'text-teal-600' : 'text-gray-500'}`}>
                  {r.kr}{r.better === 'kr' && ' ✓'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-gray-300 mt-2">
        ✓ marks the more conservative / favourable value for each metric.
        Divergence between methods reveals model uncertainty.
      </p>
    </div>
  );
}

// ── Run log table ──────────────────────────────────────────────────────────────

type SortKey = 'return_pct' | 'max_dd_pct' | 'sharpe' | 'win_rate' | 'num_trades';

function RunLogTable({ runs }: { runs: {
  return_pct: number; max_dd_pct: number; sharpe: number; win_rate: number;
  num_trades: number; final_equity: number; run_idx: number; regime?: string;
}[] }) {
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: 'return_pct', asc: false });
  const [filter, setFilter] = useState<'all' | 'profit' | 'loss'>('all');

  const displayed = [...runs]
    .filter(r => filter === 'all' || (filter === 'profit' ? r.return_pct >= 0 : r.return_pct < 0))
    .sort((a, b) => { const diff = a[sort.key] - b[sort.key]; return sort.asc ? diff : -diff; });

  function th(label: string, key: SortKey) {
    const active = sort.key === key;
    return (
      <th key={key} onClick={() => setSort(prev => ({ key, asc: prev.key === key ? !prev.asc : false }))}
        className="px-3 py-2 text-left text-[10px] uppercase tracking-wider font-semibold text-gray-400 cursor-pointer hover:text-gray-600 select-none">
        {label}{active ? (sort.asc ? ' ▲' : ' ▼') : ''}
      </th>
    );
  }

  const regimeDot = (r?: string) =>
    r === 'bull' ? '🟢' : r === 'bear' ? '🔴' : r === 'sideways' ? '🟡' : '';

  return (
    <div>
      <div className="flex gap-2 mb-3">
        {(['all', 'profit', 'loss'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1 rounded-full text-xs font-semibold transition-all ${
              filter === f ? 'bg-[var(--tv-accent)] text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
            }`}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-400 self-center">{displayed.length} paths</span>
      </div>
      <div className="overflow-auto max-h-64 rounded-xl border border-gray-100">
        <table className="w-full text-xs border-collapse">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left text-[10px] uppercase tracking-wider font-semibold text-gray-400">#</th>
              {th('Return', 'return_pct')}
              {th('Max DD', 'max_dd_pct')}
              {th('Sharpe', 'sharpe')}
              {th('Win%', 'win_rate')}
              {th('Trades', 'num_trades')}
              <th className="px-3 py-2 text-[10px] uppercase text-gray-400 font-semibold">Regime</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {displayed.slice(0, 200).map(r => (
              <tr key={r.run_idx} className="hover:bg-gray-50 transition-colors">
                <td className="px-3 py-1.5 text-gray-400">{r.run_idx + 1}</td>
                <td className={`px-3 py-1.5 font-semibold ${r.return_pct >= 0 ? 'text-teal-600' : 'text-red-500'}`}>
                  {sign(r.return_pct)}%
                </td>
                <td className="px-3 py-1.5 text-red-500">{r.max_dd_pct.toFixed(1)}%</td>
                <td className="px-3 py-1.5 text-gray-700">{r.sharpe.toFixed(3)}</td>
                <td className="px-3 py-1.5 text-gray-700">{r.win_rate.toFixed(1)}%</td>
                <td className="px-3 py-1.5 text-gray-500">{r.num_trades}</td>
                <td className="px-3 py-1.5 text-gray-400">{regimeDot((r as any).regime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ForwardTestResults({
  result,
  currency = '$',
  locale   = 'en-US',
  compare,
}: {
  result:   ForecastResponse;
  currency: string;
  locale:   string;
  compare?: ForecastCompareResult | null;
}) {
  const { baseline, monte_carlo: mc, series, forecast, price_spaghetti } = result;
  if (!series) return null;

  const spaghetti = series.spaghetti;
  const mcRuns: MCRun[] = (spaghetti?.runs ?? []).map(r => ({
    run_idx:    r.run_idx,
    return_pct: r.return_pct,
    max_dd_pct: r.max_dd_pct,
    sharpe:     r.sharpe,
    win_rate:   r.win_rate,
    equity:     r.equity,
  }));

  const tsIndices       = spaghetti?.ts_indices ?? [];
  const baselineRet     = baseline?.total_return_pct  ?? 0;
  const baselineSharpe  = baseline?.sharpe_ratio       ?? 0;
  const totalTrades     = mc ? mc.per_run.reduce((s, r) => s + (r.num_trades ?? 0), 0) : null;
  const noTrades        = totalTrades === 0;
  const probPositive    = mc && !noTrades
    ? (mc.per_run.filter(r => r.return_pct > 0).length / mc.runs * 100)
    : null;

  const isCrisis   = forecast?.mode === 'crisis';
  const survivalPct = forecast?.forward_survival_pct ?? probPositive;
  const method     = forecast?.method ?? 'block_bootstrap';
  const methodLabel = method === 'kronos' ? 'Kronos AI' : 'Block Bootstrap';
  const regimeDist = forecast?.regime_distribution;

  return (
    <div className="space-y-6">

      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-[var(--tv-text)]">
            {isCrisis ? 'Crisis Simulation Results' : 'Forward Test Results'}
          </h2>
          <p className="text-sm text-[var(--tv-muted)] flex items-center gap-2 flex-wrap">
            <span>{result.symbol} · {result.strategy}</span>
            {forecast && (
              <>
                <span>·</span>
                <span className="font-semibold">{forecast.horizon_days}d horizon</span>
                <span>·</span>
                <span className="font-semibold">{forecast.n_paths} paths</span>
                <span>·</span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                  method === 'kronos'
                    ? 'bg-teal-50 text-teal-700 border border-teal-200'
                    : 'bg-indigo-50 text-indigo-600 border border-indigo-200'
                }`}>{methodLabel}</span>
                {isCrisis && forecast.scenario_display && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-orange-50 text-orange-600 border border-orange-200">
                    {forecast.scenario_display}
                  </span>
                )}
              </>
            )}
          </p>
        </div>
        {survivalPct != null && (
          <div className={`px-4 py-2 rounded-full text-sm font-bold border ${
            survivalPct >= 60 ? 'bg-teal-50 text-teal-700 border-teal-200'
            : survivalPct >= 40 ? 'bg-yellow-50 text-yellow-700 border-yellow-200'
            : 'bg-red-50 text-red-600 border-red-200'
          }`}>
            {survivalPct.toFixed(0)}% forward survival
          </div>
        )}
      </div>

      {/* ── No-trades warning ────────────────────────────────────────── */}
      {noTrades && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 flex gap-3">
          <span className="text-xl flex-shrink-0">⚠️</span>
          <div>
            <p className="font-semibold text-amber-800 text-sm">Strategy produced 0 trades on every forward path</p>
            <p className="text-xs text-amber-600 mt-1">
              Entry conditions never triggered on synthetic data. Try relaxing conditions,
              using percentage-based comparisons, or shortening the indicator look-back period.
            </p>
          </div>
        </div>
      )}

      {/* ── Baseline ─────────────────────────────────────────────────── */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Historical Baseline (context window, no projection)
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricPill label="Return" value={`${sign(baselineRet)}%`}
            color={baselineRet >= 0 ? 'text-teal-600' : 'text-red-500'} />
          <MetricPill label="Sharpe" value={baselineSharpe.toFixed(3)} />
          <MetricPill label="Max DD" value={`${(baseline?.max_drawdown_pct ?? 0).toFixed(2)}%`} color="text-red-500" />
          <MetricPill label="Trades" value={baseline?.num_trades ?? 0} />
        </div>
      </div>

      {/* ── UC-7 Regime Forecast ─────────────────────────────────────── */}
      {regimeDist && (
        <RegimeBar dist={regimeDist} />
      )}

      {/* ── UC-3 Synthetic Price Paths ───────────────────────────────── */}
      {price_spaghetti && price_spaghetti.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Synthetic Market Paths — Price Change from Today
          </p>
          <PriceSpaghetti runs={price_spaghetti} horizon={forecast?.horizon_days ?? 90} />
          <p className="text-[10px] text-gray-300 mt-1 text-center">
            Each line is one generated future — teal = paths where strategy profits · red = loss
          </p>
        </div>
      )}

      {/* ── MC outcome distribution ──────────────────────────────────── */}
      {mc && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Outcome Distribution ({mc.runs} synthetic futures)
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <Pcts label="Return %" pcts={mc.return_pct} />
            <Pcts label="Max Drawdown %" pcts={mc.max_drawdown_pct} />
            <Pcts label="Sharpe" pcts={mc.sharpe} />
            <Pcts label="Win Rate %" pcts={mc.win_rate} />
          </div>
          {mc.cvar_5 != null && (
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div className="bg-red-50 border border-red-100 rounded-2xl p-3 text-center">
                <p className="text-[10px] uppercase tracking-wider text-red-400 mb-0.5">CVaR 5% (Tail Loss)</p>
                <p className="text-lg font-bold text-red-600">{sign(mc.cvar_5)}%</p>
                <p className="text-[10px] text-red-300 mt-0.5">avg of worst 5% of paths</p>
              </div>
              {mc.prob_ruin != null && (
                <div className="bg-orange-50 border border-orange-100 rounded-2xl p-3 text-center">
                  <p className="text-[10px] uppercase tracking-wider text-orange-400 mb-0.5">Ruin Probability</p>
                  <p className="text-lg font-bold text-orange-600">{(mc.prob_ruin * 100).toFixed(1)}%</p>
                  <p className="text-[10px] text-orange-300 mt-0.5">paths ending below 50% capital</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── UC-6 Robustness gate ─────────────────────────────────────── */}
      {survivalPct != null && mc && mc.runs >= 10 && (
        <div className={`rounded-2xl p-4 border ${
          survivalPct >= 60 ? 'bg-teal-50 border-teal-100'
          : survivalPct >= 40 ? 'bg-yellow-50 border-yellow-100'
          : 'bg-red-50 border-red-100'
        }`}>
          <div className="flex items-center gap-3">
            <span className="text-2xl">{survivalPct >= 60 ? '✅' : survivalPct >= 40 ? '⚠️' : '❌'}</span>
            <div>
              <p className={`font-bold text-sm ${
                survivalPct >= 60 ? 'text-teal-800' : survivalPct >= 40 ? 'text-yellow-800' : 'text-red-700'
              }`}>
                Forward Robustness Gate: {survivalPct >= 60 ? 'PASS' : survivalPct >= 40 ? 'BORDERLINE' : 'FAIL'}
              </p>
              <p className={`text-xs mt-0.5 ${
                survivalPct >= 60 ? 'text-teal-600' : survivalPct >= 40 ? 'text-yellow-600' : 'text-red-500'
              }`}>
                Strategy profitable in <strong>{survivalPct.toFixed(0)}%</strong> of {mc.runs} synthetic futures.
                {survivalPct >= 60 ? ' Strategy shows forward robustness.' :
                 survivalPct >= 40 ? ' Marginal — results are path-dependent.' :
                 ' Strategy fails more futures than it survives.'}
              </p>
            </div>
          </div>
          {/* Visual survival bar */}
          <div className="mt-3 w-full bg-white/60 rounded-full h-2 overflow-hidden">
            <div className={`h-full rounded-full transition-all ${
              survivalPct >= 60 ? 'bg-teal-500' : survivalPct >= 40 ? 'bg-yellow-500' : 'bg-red-500'
            }`} style={{ width: `${survivalPct}%` }} />
          </div>
          <p className="text-[10px] text-gray-400 mt-1">Threshold: 60% = Pass · 40–60% = Borderline · &lt;40% = Fail</p>
        </div>
      )}

      {/* ── Equity spaghetti canvas ───────────────────────────────────── */}
      {mcRuns.length > 0 && !noTrades && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Strategy Equity Paths across Synthetic Futures
          </p>
          <MCPathsCanvas
            runs={mcRuns}
            baselineEquity={series.baseline_equity ?? []}
            timestamps={series.timestamps ?? []}
            tsIndices={tsIndices}
            capital={baseline?.initial_capital ?? 10_000}
            currency={currency}
            locale={locale}
            height={340}
          />
          <p className="text-[10px] text-gray-300 mt-2 text-center">
            Colour: red = loss path · teal = gain path · click to pin · delta toggle for relative impact
          </p>
        </div>
      )}

      {/* ── Kronos vs Bootstrap comparison ───────────────────────────── */}
      {compare && compare.kronos_available && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Kronos AI vs Statistical Bootstrap Comparison
          </p>
          <ComparePanel compare={compare} />
        </div>
      )}

      {/* ── Run log ──────────────────────────────────────────────────── */}
      {mc && mc.per_run.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Path Log
          </p>
          <RunLogTable runs={mc.per_run.map((r, i) => ({ ...r, final_equity: r.final_equity ?? 0, run_idx: i }))} />
        </div>
      )}

    </div>
  );
}
