import React, { useState, useRef, useCallback } from 'react';
import { StressFormState, StressResponse } from '../../types';
import StressSidebar, { DEFAULT_STRESS_FORM } from './StressSidebar';
import StressResults from './StressResults';
import MCPathsCanvas, { MCRun } from './MCPathsCanvas';
import { streamStressTest, isIndianSource, StreamRun } from '../../api';

// ─── Live loading state ───────────────────────────────────────────────────────

interface LiveState {
  runsDone:     number;
  total:        number;
  liveRuns:     MCRun[];
  latestReturn: number | null;
  latestSharpe: number | null;
  bestReturn:   number;
  worstReturn:  number;
  baselineRet:  number | null;
}

const EMPTY_LIVE: LiveState = {
  runsDone: 0, total: 0, liveRuns: [],
  latestReturn: null, latestSharpe: null,
  bestReturn: -Infinity, worstReturn: Infinity, baselineRet: null,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function sign(n: number, d = 2) { return n >= 0 ? `+${n.toFixed(d)}` : n.toFixed(d); }

function ReturnBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? (done / total) * 100 : 0;
  return (
    <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-150"
        style={{
          width: `${pct}%`,
          background: 'linear-gradient(90deg, #6366f1, #f97316)',
        }}
      />
    </div>
  );
}

// ─── Live loading view ────────────────────────────────────────────────────────

function LiveLoadingView({
  live, form, currency, locale,
}: {
  live:     LiveState;
  form:     StressFormState;
  currency: string;
  locale:   string;
}) {
  const { runsDone, total, liveRuns, latestReturn, latestSharpe, bestReturn, worstReturn, baselineRet } = live;
  const hasRuns = liveRuns.length > 0;

  // Dummy tsIndices (0…N-1) for the live canvas — we don't have full timestamps yet
  const tsIndices = Array.from({ length: hasRuns ? liveRuns[0].equity.length : 0 }, (_, i) => i);

  return (
    <div className="bg-white rounded-3xl tv-soft-shadow overflow-hidden">

      {/* Header bar */}
      <div className="px-6 pt-5 pb-3 border-b border-gray-50">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-indigo-50 flex items-center justify-center">
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-200 border-t-indigo-500" />
            </div>
            <div>
              <p className="font-bold text-sm text-gray-800">
                Running Monte Carlo Simulation
              </p>
              <p className="text-xs text-gray-400">
                {form.scenarioKey.replace('_', ' ')} · {form.mcRuns} runs · {form.symbol}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-gray-800 tabular-nums">
              {runsDone}
              <span className="text-sm font-normal text-gray-400"> / {total}</span>
            </p>
            <p className="text-xs text-gray-400">runs complete</p>
          </div>
        </div>
        <ReturnBar done={runsDone} total={total} />
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-4 divide-x divide-gray-50 border-b border-gray-50">
        {[
          { label: 'Latest Return',  value: latestReturn  != null ? `${sign(latestReturn)}%`  : '—', color: latestReturn != null ? (latestReturn >= 0 ? 'text-green-600' : 'text-red-500') : 'text-gray-400' },
          { label: 'Latest Sharpe', value: latestSharpe != null ? latestSharpe.toFixed(3)    : '—', color: 'text-gray-700' },
          { label: 'Best so far',   value: isFinite(bestReturn)  ? `${sign(bestReturn)}%`   : '—', color: 'text-green-600' },
          { label: 'Worst so far',  value: isFinite(worstReturn) ? `${sign(worstReturn)}%`  : '—', color: 'text-red-500' },
        ].map(({ label, value, color }) => (
          <div key={label} className="px-4 py-3 text-center">
            <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">{label}</p>
            <p className={`text-base font-bold ${color} tabular-nums`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Baseline chip */}
      {baselineRet !== null && (
        <div className="px-6 py-2 bg-blue-50 border-b border-blue-100 text-xs text-blue-700">
          Baseline (no stress): <span className="font-bold">{sign(baselineRet)}%</span>
          <span className="text-blue-400 ml-2">— stress impact will be measured against this</span>
        </div>
      )}

      {/* Live canvas — shows paths building up */}
      <div className="px-4 pt-4 pb-2">
        {hasRuns ? (
          <>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Equity Paths — building live
            </p>
            <MCPathsCanvas
              runs={liveRuns}
              baselineEquity={[]}
              timestamps={[]}
              tsIndices={tsIndices}
              capital={form.capital}
              currency={currency}
              locale={locale}
              height={320}
              isLive
              totalExpected={total}
            />
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-48 gap-3 text-gray-400">
            <div className="flex gap-1">
              {[0,1,2].map(i => (
                <div key={i} className="w-2 h-2 bg-indigo-300 rounded-full animate-bounce"
                  style={{ animationDelay: `${i * 0.15}s` }} />
              ))}
            </div>
            <p className="text-sm font-medium">Fetching market data &amp; computing baseline…</p>
            <p className="text-xs text-gray-300">
              {form.runValidation
                ? 'Running walk-forward validation before MC runs — may take 15–60 s'
                : 'Indian/NSE data can take 10–30 s via yfinance'}
            </p>
          </div>
        )}
      </div>

      {/* Footer note */}
      <p className="text-center text-xs text-gray-300 pb-4">
        Each line is one simulated equity path — colour shows expected outcome (red=loss, teal=gain)
      </p>
    </div>
  );
}

// ─── Main StressPage ──────────────────────────────────────────────────────────

type PageState =
  | { kind: 'idle' }
  | { kind: 'live';     live: LiveState }
  | { kind: 'complete'; result: StressResponse }
  | { kind: 'error';    message: string };

export default function StressPage() {
  const [form,      setForm]      = useState<StressFormState>(DEFAULT_STRESS_FORM);
  const [pageState, setPageState] = useState<PageState>({ kind: 'idle' });
  const cleanupRef = useRef<(() => void) | null>(null);

  const handleChange = (updates: Partial<StressFormState>) =>
    setForm(prev => ({ ...prev, ...updates }));

  const handleRun = useCallback(() => {
    // Cancel any in-flight stream
    cleanupRef.current?.();

    setPageState({ kind: 'live', live: { ...EMPTY_LIVE, total: form.mcRuns } });

    const cleanup = streamStressTest(form, {
      onBaseline(metrics, total) {
        setPageState(prev => {
          if (prev.kind !== 'live') return prev;
          return {
            kind: 'live',
            live: {
              ...prev.live,
              baselineRet: metrics.total_return_pct ?? null,
              ...(total != null ? { total } : {}),
            },
          };
        });
      },

      onRun(runNum, total, run: StreamRun) {
        const mcRun: MCRun = {
          run_idx:    run.run_idx,
          return_pct: run.return_pct,
          max_dd_pct: run.max_dd_pct,
          sharpe:     run.sharpe,
          win_rate:   run.win_rate,
          equity:     run.equity,
        };
        setPageState(prev => {
          if (prev.kind !== 'live') return prev;
          const l = prev.live;
          return {
            kind: 'live',
            live: {
              runsDone:     runNum,
              total,
              liveRuns:     [...l.liveRuns, mcRun],
              latestReturn: run.return_pct,
              latestSharpe: run.sharpe,
              bestReturn:   Math.max(l.bestReturn,  run.return_pct),
              worstReturn:  Math.min(l.worstReturn, run.return_pct),
              baselineRet:  l.baselineRet,
            },
          };
        });
      },

      onComplete(result) {
        setPageState({ kind: 'complete', result });
      },

      onError(msg) {
        setPageState({ kind: 'error', message: msg });
      },
    });

    cleanupRef.current = cleanup;
  }, [form]);

  const indian   = isIndianSource(form.source);
  const currency = indian ? '₹' : '$';
  const locale   = indian ? 'en-IN' : 'en-US';

  return (
    <div className="flex h-full overflow-hidden">
      <StressSidebar
        form={form}
        onChange={handleChange}
        onRun={handleRun}
        loading={pageState.kind === 'live'}
      />

      <main className="flex-1 overflow-y-auto bg-[var(--tv-bg)]">
        <div className="p-8 max-w-[1400px] mx-auto">

          {/* Header */}
          <div className="mb-6">
            <h1 className="text-3xl font-bold text-[var(--tv-text)] mb-1">Stress Tester</h1>
            <p className="text-sm text-[var(--tv-muted)]">
              Simulate extreme market scenarios on real OHLCV data and see how your strategy holds up.
            </p>
          </div>

          {/* Error */}
          {pageState.kind === 'error' && (
            <div className="p-4 rounded-2xl mb-6 bg-red-50 border border-red-100 flex items-start gap-3">
              <span className="text-xl">❌</span>
              <div>
                <p className="font-semibold text-red-700">{pageState.message}</p>
                <p className="text-sm text-red-500 mt-1">
                  {pageState.message === 'Failed to fetch'
                    ? 'Could not connect to the backend. Restart the Vite dev server (npm run dev) and make sure the backend is running on :8000.'
                    : 'Check your symbol, date range, and that the backend is running on :8000.'}
                </p>
              </div>
            </div>
          )}

          {/* Live loading */}
          {pageState.kind === 'live' && (
            <LiveLoadingView
              live={pageState.live}
              form={form}
              currency={currency}
              locale={locale}
            />
          )}

          {/* Empty state */}
          {pageState.kind === 'idle' && (
            <div className="flex flex-col items-center justify-center py-24 bg-white rounded-3xl tv-soft-shadow">
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl mb-4"
                style={{ backgroundColor: 'var(--tv-pastel-pink)' }}>
                🧪
              </div>
              <p className="text-xl font-bold text-[var(--tv-text)] mb-2">Stress Tester</p>
              <p className="text-sm text-[var(--tv-muted)] text-center max-w-sm">
                Pick a scenario, set severity, then click{' '}
                <span className="font-semibold text-[var(--tv-accent)]">Run Stress Test</span> to see
                baseline vs stressed performance and Monte Carlo outcome distributions.
              </p>
              <div className="mt-6 grid grid-cols-3 gap-3 text-xs text-center text-[var(--tv-muted)]">
                {['13 Scenarios', 'Mild → Severe', 'Monte Carlo'].map(tag => (
                  <span key={tag} className="px-3 py-1.5 bg-gray-50 rounded-full border border-gray-100">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Results */}
          {pageState.kind === 'complete' && (
            <div className="bg-white rounded-3xl tv-soft-shadow p-6 fade-in">
              <StressResults result={pageState.result} currency={currency} locale={locale} />
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
