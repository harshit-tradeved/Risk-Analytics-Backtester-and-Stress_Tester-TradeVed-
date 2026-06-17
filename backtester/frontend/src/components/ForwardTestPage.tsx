import React, { useState, useRef, useCallback } from 'react';
import { ForecastFormState, ForecastResponse, ForecastCompareResult, RegimeDistribution } from '../types';
import ForwardTestSidebar, { DEFAULT_FORECAST_FORM } from './ForwardTestSidebar';
import ForwardTestResults from './ForwardTestResults';
import MCPathsCanvas, { MCRun } from './MCPathsCanvas';
import PaperTradeView from './PaperTradeView';
import { streamForwardTest, streamCrisisTest, compareForecastMethods, isIndianSource, StreamRun } from '../api';

type SubMode = 'forward' | 'crisis' | 'paper';

// ─── Live state ───────────────────────────────────────────────────────────────

interface LiveState {
  runsDone:     number;
  total:        number;
  liveRuns:     MCRun[];
  latestReturn: number | null;
  latestSharpe: number | null;
  bestReturn:   number;
  worstReturn:  number;
  baselineRet:  number | null;
  regimeCounts: { bull: number; bear: number; sideways: number };
}

const EMPTY_LIVE: LiveState = {
  runsDone: 0, total: 0, liveRuns: [],
  latestReturn: null, latestSharpe: null,
  bestReturn: -Infinity, worstReturn: Infinity, baselineRet: null,
  regimeCounts: { bull: 0, bear: 0, sideways: 0 },
};

// ── Progress bar ──────────────────────────────────────────────────────────────

function ReturnBar({ done, total, crisis }: { done: number; total: number; crisis?: boolean }) {
  const pct = total > 0 ? (done / total) * 100 : 0;
  const gradient = crisis
    ? 'linear-gradient(90deg, #f97316, #dc2626)'
    : 'linear-gradient(90deg, #6366f1, #14b8a6)';
  return (
    <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
      <div className="h-full rounded-full transition-all duration-150"
        style={{ width: `${pct}%`, background: gradient }} />
    </div>
  );
}

function sign(n: number, d = 2) { return n >= 0 ? `+${n.toFixed(d)}` : n.toFixed(d); }

// ── Live regime chips ─────────────────────────────────────────────────────────

function LiveRegimeBar({ counts, total }: { counts: { bull: number; bear: number; sideways: number }; total: number }) {
  if (total === 0) return null;
  const pct = (n: number) => Math.round(n / total * 100);
  return (
    <div className="px-6 py-2 bg-gray-50 border-b border-gray-100 flex items-center gap-3 text-xs">
      <span className="text-gray-400 font-semibold uppercase tracking-wider text-[10px]">Live Regime</span>
      <span className="text-teal-600 font-bold">🟢 Bull {pct(counts.bull)}%</span>
      <span className="text-yellow-600 font-bold">🟡 Sideways {pct(counts.sideways)}%</span>
      <span className="text-red-500 font-bold">🔴 Bear {pct(counts.bear)}%</span>
    </div>
  );
}

// ── Live loading view ─────────────────────────────────────────────────────────

function LiveLoadingView({
  live, form, currency, locale, crisis, scenarioLabel,
}: {
  live:          LiveState;
  form:          ForecastFormState;
  currency:      string;
  locale:        string;
  crisis:        boolean;
  scenarioLabel?: string;
}) {
  const { runsDone, total, liveRuns, latestReturn, latestSharpe, bestReturn, worstReturn, baselineRet, regimeCounts } = live;
  const hasRuns  = liveRuns.length > 0;
  const tsIndices = Array.from({ length: hasRuns ? liveRuns[0].equity.length : 0 }, (_, i) => i);

  return (
    <div className="bg-white rounded-3xl tv-soft-shadow overflow-hidden">
      {/* Header */}
      <div className="px-6 pt-5 pb-3 border-b border-gray-50">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-xl flex items-center justify-center ${crisis ? 'bg-orange-50' : 'bg-teal-50'}`}>
              <div className={`animate-spin rounded-full h-4 w-4 border-2 border-gray-200 ${crisis ? 'border-t-orange-500' : 'border-t-teal-500'}`} />
            </div>
            <div>
              <p className="font-bold text-sm text-gray-800">
                {crisis ? `Crisis Simulation — ${scenarioLabel ?? ''}` : 'Generating Forward Paths'}
              </p>
              <p className="text-xs text-gray-400">
                {form.horizonDays}d horizon · {form.nPaths} paths · {form.symbol} · {form.strategy}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-gray-800 tabular-nums">
              {runsDone}<span className="text-sm font-normal text-gray-400"> / {total}</span>
            </p>
            <p className="text-xs text-gray-400">paths complete</p>
          </div>
        </div>
        <ReturnBar done={runsDone} total={total} crisis={crisis} />
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-4 divide-x divide-gray-50 border-b border-gray-50">
        {[
          { label: 'Latest Return', value: latestReturn != null ? `${sign(latestReturn)}%` : '—',
            color: latestReturn != null ? (latestReturn >= 0 ? 'text-teal-600' : 'text-red-500') : 'text-gray-400' },
          { label: 'Latest Sharpe', value: latestSharpe != null ? latestSharpe.toFixed(3) : '—', color: 'text-gray-700' },
          { label: 'Best so far',   value: isFinite(bestReturn) ? `${sign(bestReturn)}%` : '—',  color: 'text-teal-600' },
          { label: 'Worst so far',  value: isFinite(worstReturn) ? `${sign(worstReturn)}%` : '—', color: 'text-red-500' },
        ].map(({ label, value, color }) => (
          <div key={label} className="px-4 py-3 text-center">
            <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">{label}</p>
            <p className={`text-base font-bold ${color} tabular-nums`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Live regime bar */}
      <LiveRegimeBar counts={regimeCounts} total={runsDone} />

      {/* Baseline chip */}
      {baselineRet !== null && (
        <div className={`px-6 py-2 border-b text-xs ${crisis ? 'bg-orange-50 border-orange-100 text-orange-700' : 'bg-blue-50 border-blue-100 text-blue-700'}`}>
          Historical baseline: <span className="font-bold">{sign(baselineRet)}%</span>
          <span className="text-blue-400 ml-2">— forward paths project from the last historical close</span>
        </div>
      )}

      {/* Live canvas */}
      <div className={crisis ? 'pt-2 pb-1' : 'px-4 pt-4 pb-2'}>
        {hasRuns ? (
          <>
            {!crisis && (
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Synthetic Equity Paths — building live
              </p>
            )}
            <MCPathsCanvas
              runs={liveRuns}
              baselineEquity={[]}
              timestamps={[]}
              tsIndices={tsIndices}
              capital={form.capital}
              currency={currency}
              locale={locale}
              height={crisis ? 300 : 320}
              isLive
              totalExpected={total}
              darkMode={crisis}
            />
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-48 gap-3 text-gray-400">
            <div className="flex gap-1">
              {[0,1,2].map(i => (
                <div key={i} className={`w-2 h-2 rounded-full animate-bounce ${crisis ? 'bg-orange-300' : 'bg-teal-300'}`}
                  style={{ animationDelay: `${i * 0.15}s` }} />
              ))}
            </div>
            <p className="text-sm font-medium">Fetching historical data &amp; computing baseline…</p>
          </div>
        )}
      </div>

      {!crisis && (
        <p className="text-center text-xs text-gray-300 pb-4">
          Colour: red = projected loss · teal = projected gain
        </p>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

type PageState =
  | { kind: 'idle' }
  | { kind: 'live';     live: LiveState }
  | { kind: 'complete'; result: ForecastResponse; compare?: ForecastCompareResult | null }
  | { kind: 'error';    message: string };

export default function ForwardTestPage() {
  const [form,          setForm]          = useState<ForecastFormState>(DEFAULT_FORECAST_FORM);
  const [pageState,     setPageState]     = useState<PageState>({ kind: 'idle' });
  const [subMode,       setSubMode]       = useState<SubMode>('forward');
  const [crisisScenario,setCrisisScenario]= useState('covid_crash');
  const [severity,      setSeverity]      = useState(1.0);
  const [comparing,     setComparing]     = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Derived helpers
  const crisisMode = subMode === 'crisis';
  const paperMode  = subMode === 'paper';

  const handleChange = (updates: Partial<ForecastFormState>) =>
    setForm(prev => ({ ...prev, ...updates }));

  const handleRunCompare = useCallback(async () => {
    if (pageState.kind !== 'complete') return;
    setComparing(true);
    try {
      const compareResult = await compareForecastMethods(form);
      setPageState(prev => prev.kind === 'complete' ? { ...prev, compare: compareResult } : prev);
    } catch (e) {
      // non-fatal — just don't show comparison
    } finally {
      setComparing(false);
    }
  }, [form, pageState]);

  const handleRun = useCallback(() => {
    cleanupRef.current?.();
    setPageState({ kind: 'live', live: { ...EMPTY_LIVE, total: form.nPaths } });

    const onBaseline = (metrics: Record<string, number>, total?: number) => {
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
    };

    const onRun = (runNum: number, total: number, run: StreamRun & { regime?: string }) => {
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
        const regime = run.regime ?? 'unknown';
        const newCounts = { ...l.regimeCounts };
        if (regime === 'bull' || regime === 'bear' || regime === 'sideways') newCounts[regime]++;
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
            regimeCounts: newCounts,
          },
        };
      });
    };

    const onComplete = (result: ForecastResponse) => {
      setPageState({ kind: 'complete', result, compare: null });
    };

    const onError = (msg: string) => {
      setPageState({ kind: 'error', message: msg });
    };

    const cleanup = crisisMode
      ? streamCrisisTest(form, crisisScenario, severity, { onBaseline, onRun, onComplete, onError })
      : streamForwardTest(form, { onBaseline, onRun, onComplete, onError });

    cleanupRef.current = cleanup;
  }, [form, crisisMode, crisisScenario, severity]);

  const indian   = isIndianSource(form.source);
  const currency = indian ? '₹' : '$';
  const locale   = indian ? 'en-IN' : 'en-US';

  const crisisLabel = crisisScenario.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div className="flex h-full overflow-hidden">
      <ForwardTestSidebar
        form={form}
        onChange={handleChange}
        onRun={handleRun}
        loading={pageState.kind === 'live'}
        crisisMode={crisisMode}
        onCrisisModeChange={(v) => setSubMode(v ? 'crisis' : 'forward')}
        crisisScenario={crisisScenario}
        onCrisisScenarioChange={setCrisisScenario}
        severity={severity}
        onSeverityChange={setSeverity}
      />

      <main className="flex-1 overflow-y-auto bg-[var(--tv-bg)]">
        <div className="p-8 max-w-[1400px] mx-auto">

          {/* Mode tab strip */}
          <div className="mb-5 flex gap-2">
            {([
              { key: 'forward', label: 'Forward Test', icon: '🔭', desc: 'Distribution of futures' },
              { key: 'crisis',  label: 'Crisis Sim',   icon: '🔥', desc: 'Stress + generated paths' },
              { key: 'paper',   label: 'Paper Trade',  icon: '📋', desc: 'Bar-by-bar simulation'  },
            ] as { key: SubMode; label: string; icon: string; desc: string }[]).map(m => (
              <button key={m.key} onClick={() => { setSubMode(m.key); setPageState({ kind: 'idle' }); }}
                className={`flex-1 px-3 py-2.5 rounded-xl text-left transition-all border ${
                  subMode === m.key
                    ? 'bg-indigo-50 border-indigo-200 text-indigo-700'
                    : 'bg-white border-gray-100 text-gray-500 hover:bg-gray-50'
                }`}>
                <p className="text-sm font-semibold">{m.icon} {m.label}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{m.desc}</p>
              </button>
            ))}
          </div>

          {/* Header */}
          <div className="mb-6 flex items-start justify-between">
            <div>
              <h1 className="text-3xl font-bold text-[var(--tv-text)] mb-1">
                {subMode === 'crisis' ? 'AI Crisis Simulator' : subMode === 'paper' ? 'AI Paper Trading' : 'AI Forward Test'}
              </h1>
              <p className="text-sm text-[var(--tv-muted)]">
                {subMode === 'crisis'
                  ? 'Kronos-generated paths with deterministic stress scaffold — how does your strategy survive a crisis?'
                  : subMode === 'paper'
                  ? 'Watch your strategy trade bar-by-bar on a single AI-generated future — see decisions and P&L unfold in real time.'
                  : 'Generate synthetic future price paths and see how your strategy would perform across the distribution of plausible futures.'}
              </p>
            </div>

            {/* Compare button — shown after a forward test completes */}
            {pageState.kind === 'complete' && !crisisMode && (
              <button onClick={handleRunCompare} disabled={comparing}
                className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all border ${
                  comparing
                    ? 'bg-gray-50 text-gray-400 border-gray-200'
                    : 'bg-white text-indigo-600 border-indigo-200 hover:bg-indigo-50 shadow-sm'
                }`}>
                {comparing ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-gray-300 border-t-indigo-500 rounded-full animate-spin" />
                    Comparing…
                  </>
                ) : (
                  <>⚖️ Compare Kronos vs Bootstrap</>
                )}
              </button>
            )}
          </div>

          {/* Paper Trade mode — rendered exclusively */}
          {paperMode && (
            <PaperTradeView form={form} currency={currency} locale={locale} />
          )}

          {/* Error */}
          {!paperMode && pageState.kind === 'error' && (
            <div className="p-4 rounded-2xl mb-6 bg-red-50 border border-red-100 flex items-start gap-3">
              <span className="text-xl">❌</span>
              <div>
                <p className="font-semibold text-red-700">{pageState.message}</p>
                <p className="text-sm text-red-500 mt-1">
                  {pageState.message === 'Failed to fetch'
                    ? 'Could not connect to the backend. Make sure the backend is running on :8000.'
                    : 'Check your symbol, date range, and that the backend is running on :8000.'}
                </p>
              </div>
            </div>
          )}

          {/* Live */}
          {!paperMode && pageState.kind === 'live' && (
            <LiveLoadingView
              live={pageState.live}
              form={form}
              currency={currency}
              locale={locale}
              crisis={crisisMode}
              scenarioLabel={crisisLabel}
            />
          )}

          {/* Idle */}
          {!paperMode && pageState.kind === 'idle' && (
            <div className="flex flex-col items-center justify-center py-24 bg-white rounded-3xl tv-soft-shadow">
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl mb-4"
                style={{ backgroundColor: crisisMode ? '#fff7ed' : '#f0fdf9' }}>
                {crisisMode ? '🔥' : '🔭'}
              </div>
              <p className="text-xl font-bold text-[var(--tv-text)] mb-2">
                {crisisMode ? 'AI Crisis Simulator' : 'AI Forward Test'}
              </p>
              <p className="text-sm text-[var(--tv-muted)] text-center max-w-md">
                {crisisMode
                  ? 'Pick a crisis scenario, set severity, and run — Kronos generates realistic price action while the stress scaffold imposes the macro shock shape.'
                  : 'Pick your strategy and historical context, set how far ahead to project and how many paths to generate, then click Run.'}
              </p>
              <p className="text-xs text-gray-400 text-center max-w-sm mt-3">
                {crisisMode
                  ? 'UC-2 hybrid: Kronos micro-structure + parametric crisis scaffold · 17 scenarios'
                  : 'Paths via circular block-bootstrap (preserving autocorrelation), or Kronos GPU when KRONOS_URL is set.'}
              </p>
              <div className="mt-6 grid grid-cols-3 gap-3 text-xs text-center text-[var(--tv-muted)]">
                {(crisisMode
                  ? ['17 Scenarios', 'Regime Forecast', 'Survival Gate']
                  : ['Block Bootstrap', 'All Strategies', 'Regime Forecast']
                ).map(tag => (
                  <span key={tag} className="px-3 py-1.5 bg-gray-50 rounded-full border border-gray-100">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Results */}
          {!paperMode && pageState.kind === 'complete' && (
            <div className="bg-white rounded-3xl tv-soft-shadow p-6 fade-in">
              <ForwardTestResults
                result={pageState.result}
                currency={currency}
                locale={locale}
                compare={pageState.compare}
              />
            </div>
          )}

        </div>
      </main>
    </div>
  );
}
