import { useState, useEffect } from 'react';
import Sidebar          from './components/Sidebar';
import MetricsGrid      from './components/MetricsGrid';
import ChartsPanel      from './components/ChartsPanel';
import TradeLog         from './components/TradeLog';
import RegimeBreakdown  from './components/RegimeBreakdown';
import ValidationPanel  from './components/ValidationPanel';
import StressPage       from './components/StressPage';
import ForwardTestPage  from './components/ForwardTestPage';
import ReelPage         from './components/ReelPage';
import IdentityGate     from './components/IdentityGate';
import FeedbackWidget   from './components/FeedbackWidget';
import AdminDashboard   from './components/AdminDashboard';
import { FormState, BacktestResponse } from './types';
import { runBacktest, isIndianSource, validateAdminToken } from './api';
import { getIdentity, getAdminToken, setAdminToken, track, trackPageView } from './analytics';

type Page = 'backtest' | 'stress' | 'forward' | 'admin' | 'reel';

const today = new Date();
const fmt   = (d: Date) => d.toISOString().split('T')[0];
const yr1   = fmt(new Date(today.getTime() - 365 * 86_400_000));

const DEFAULT_FORM: FormState = {
  symbol:       'BTC/USDT',
  customSymbol: 'BTC/USDT',
  source:       'binance',
  startDate:    yr1,
  endDate:      fmt(today),
  datePreset:   '1Y',
  interval:     '1d',
  capital:      10_000,
  feePct:       0.10,
  slippagePct:  0.05,
  strategy:     'DCA',
  strategyParams:     {},
  lowerBound:         20_000,
  upperBound:         70_000,
  numLevels:          5,
  gridSpacing:        'linear',
  gridInvestPerLevel: 500,
  buyIntervalHours: 24,
  dcaInvestPerBuy:  200,
  holdDays:         30,
  dcaExitType:      'time',
  profitTargetPct:  10,
  fastEma:           12,
  slowEma:           26,
  plaExitType:       'crossover',
  takeProfitPct:     5,
  stopLossPct:       3,
  plaLvl2Pct:        -1,
  plaLvl3Pct:        -2.5,
  plaLvl4Pct:        -4,
  plaInvestPerLevel: 300,
  marketType:     'equity_delivery',
  brokerageModel: 'flat',
  brokerageFlat:  20,
  brokeragePct:   0.5,
  validationMode: 'none',
  trainRatio:     0.7,
  wfWindow:       252,
  wfStep:         63,
};

type Status   = 'idle' | 'loading' | 'success' | 'error';
type MainTab  = 'charts' | 'trades' | 'report' | 'validation';

export default function App() {
  const [page,       setPage]       = useState<Page>('backtest');
  const [form,       setForm]       = useState<FormState>(DEFAULT_FORM);
  const [status,     setStatus]     = useState<Status>('idle');
  const [result,     setResult]     = useState<BacktestResponse | null>(null);
  const [errorMsg,   setErrorMsg]   = useState('');
  const [tab,        setTab]        = useState<MainTab>('charts');
  const [identified, setIdentified] = useState(() => !!getIdentity().name);
  const [adminToken, setAdminTokenState] = useState<string | null>(null);

  // Validate admin token on mount — strip it from URL immediately so it's never shareable
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get('admin');
    const candidate = urlToken ?? getAdminToken();

    if (urlToken) {
      // Remove ?admin= from URL right away — token must not persist in address bar
      const clean = new URL(window.location.href);
      clean.searchParams.delete('admin');
      window.history.replaceState({}, '', clean.toString());
    }

    if (!candidate) return;

    validateAdminToken(candidate).then(valid => {
      if (valid) {
        setAdminToken(candidate);
        setAdminTokenState(candidate);
      } else {
        // Bad token — clear it from storage too
        localStorage.removeItem('tv_admin_token');
      }
    });
  }, []);

  // Track page changes
  useEffect(() => {
    if (identified) trackPageView(page);
  }, [page, identified]);

  const updateForm = (updates: Partial<FormState>) =>
    setForm(prev => ({ ...prev, ...updates }));

  const handleRun = async () => {
    if (form.startDate >= form.endDate) {
      setErrorMsg('Start date must be before end date.'); setStatus('error'); return;
    }
    if (form.strategy === 'PLA' && form.fastEma >= form.slowEma) {
      setErrorMsg('PLA: Fast EMA must be less than Slow EMA.'); setStatus('error'); return;
    }
    if (form.strategy === 'GRID' && form.lowerBound >= form.upperBound) {
      setErrorMsg('GRID: Lower bound must be less than Upper bound.'); setStatus('error'); return;
    }
    const symbol = form.symbol === '__custom__' ? form.customSymbol : form.symbol;
    track('run_backtest', { symbol, strategy: form.strategy, capital: form.capital, source: form.source, interval: form.interval }, 'action', 'backtest');
    setStatus('loading'); setErrorMsg('');
    try {
      const data = await runBacktest(form);
      setResult(data);
      setStatus('success');
      setTab('charts');
      track('backtest_success', { symbol, strategy: form.strategy, return_pct: data.results?.total_return_pct }, 'action', 'backtest');
    } catch (err: any) {
      setErrorMsg(err.message || 'Unknown error from API');
      setStatus('error');
      track('backtest_error', { symbol, strategy: form.strategy, error: err.message }, 'error', 'backtest');
    }
  };

  const symbol   = form.symbol === '__custom__' ? form.customSymbol : form.symbol;
  const currency = result?.currency ?? (isIndianSource(form.source) ? '₹' : '$');

  const { name: userName } = getIdentity();
  const initials = userName ? userName.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() : 'HK';

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--tv-bg)] font-sans flex-col">

      {/* ── Identity gate (first visit) ─────────────────────────────────── */}
      {!identified && (
        <IdentityGate onIdentified={() => setIdentified(true)} />
      )}

      {/* ── Top Navigation Bar ──────────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-[var(--tv-bg)]/95 backdrop-blur-md z-20 px-6 py-3 flex items-center justify-between border-b border-[var(--tv-border)]">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg font-black text-sm text-white"
            style={{ background: 'var(--tv-accent)' }}>
            TV
          </div>
          <div className="flex items-baseline gap-0.5">
            <span className="text-xl font-bold tracking-tight text-[var(--tv-text)]">Trade</span>
            <span className="text-xl font-bold tracking-tight text-[var(--tv-accent)]">Ved</span>
          </div>
        </div>

        {/* Page pills */}
        <div className="flex gap-1 bg-gray-100 rounded-full p-1">
          {([
            { key: 'backtest', label: '📈 Backtest'    },
            { key: 'stress',   label: '🧪 Stress Test'  },
            { key: 'forward',  label: '🔭 Forward Test' },
            { key: 'reel',     label: '🎬 Reel Backtest' },
            ...(adminToken ? [{ key: 'admin', label: '🔒 Admin' }] : []),
          ] as { key: Page; label: string }[]).map(p => (
            <button key={p.key} onClick={() => { setPage(p.key); track('switch_page', { to: p.key }, 'action', page); }}
              className={`px-5 py-1.5 rounded-full text-sm font-semibold transition-all ${
                page === p.key
                  ? 'bg-white text-[var(--tv-accent)] shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >{p.label}</button>
          ))}
        </div>

        {/* Right icons */}
        <div className="flex items-center gap-2">
          <button
            title="Send feedback"
            onClick={() => track('feedback_nav_click', {}, 'action', page)}
            className="w-9 h-9 flex items-center justify-center bg-[var(--tv-s1)] rounded-full shadow-sm border border-gray-100 text-gray-500 hover:bg-gray-50">💬</button>
          <button className="w-9 h-9 flex items-center justify-center bg-[var(--tv-accent)] rounded-full shadow-sm text-white font-bold text-sm" title={userName ?? ''}>{initials}</button>
        </div>
      </div>

      {/* ── Page content ────────────────────────────────────────────────── */}
      {page === 'admin' && adminToken ? (
        <div className="flex-1 overflow-y-auto">
          <AdminDashboard token={adminToken} />
        </div>
      ) : page === 'stress' ? (
        <div className="flex-1 overflow-hidden">
          <StressPage />
        </div>
      ) : page === 'forward' ? (
        <div className="flex-1 overflow-hidden">
          <ForwardTestPage />
        </div>
      ) : page === 'reel' ? (
        <div className="flex-1 overflow-hidden">
          <ReelPage />
        </div>
      ) : (
      <div className="flex flex-1 overflow-hidden">

      {/* ── Left sidebar ─────────────────────────────────────────────── */}
      <aside className="w-80 flex-shrink-0 overflow-y-auto bg-[var(--tv-s1)] shadow-sm z-10 border-r border-gray-100">
        <Sidebar form={form} onChange={updateForm} onRun={handleRun} loading={status === 'loading'} />
      </aside>

      {/* ── Main content ─────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        <div className="p-8 max-w-[1400px] mx-auto">

          {/* ── Breadcrumb / Context ────────────────────────────────────── */}
          <div className="mb-6 flex items-start justify-between">
            <div>
              <h1 className="text-3xl font-bold text-[var(--tv-text)] mb-1">Backtester</h1>
              <p className="text-sm text-[var(--tv-muted)] flex items-center gap-2">
                <span className="font-semibold bg-white shadow-sm border border-gray-100 px-2 py-0.5 rounded-md">{symbol}</span>
                <span>•</span>
                <span>{form.strategy}</span>
                <span>•</span>
                <span>{form.startDate} → {form.endDate}</span>
                <span>•</span>
                <span>{currency}{form.capital.toLocaleString()}</span>
                {isIndianSource(form.source) && (
                  <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-orange-100 text-orange-600">
                    🇮🇳 NSE
                  </span>
                )}
              </p>
            </div>
            {status === 'success' && result && (
              <a
                href={`${import.meta.env.VITE_API_BASE_URL ?? ''}${result.report_url}`}
                target="_blank" rel="noreferrer"
                className="flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-semibold transition-all bg-white shadow-sm border border-gray-100 text-[var(--tv-text)] hover:shadow-md hover:-translate-y-0.5">
                📄 View HTML Report ↗
              </a>
            )}
          </div>

          {/* ── Loading ─────────────────────────────────────────────────── */}
          {status === 'loading' && (
            <div className="flex flex-col items-center justify-center py-20 bg-white rounded-3xl tv-soft-shadow">
              <div className="animate-spin rounded-full h-10 w-10 border-4 border-gray-100 border-t-[var(--tv-accent)] mb-4" />
              <p className="text-lg font-medium text-[var(--tv-text)]">
                Fetching {form.interval} candles for {symbol}…
              </p>
              <p className="text-sm text-[var(--tv-muted)] mt-2">Running simulations on historical data.</p>
            </div>
          )}

          {/* ── Error ───────────────────────────────────────────────────── */}
          {status === 'error' && (
            <div className="p-5 rounded-2xl mb-6 bg-red-50 border border-red-100 flex items-start gap-3">
              <span className="text-xl">❌</span>
              <div>
                <p className="font-semibold text-red-700">{errorMsg}</p>
                <p className="text-sm text-red-500 mt-1">
                  Check your date range, symbol, and data source then try again.
                </p>
              </div>
            </div>
          )}

          {/* ── Welcome ─────────────────────────────────────────────────── */}
          {status === 'idle' && <WelcomeScreen />}

          {/* ── Results ─────────────────────────────────────────────────── */}
          {status === 'success' && result && (
            <div className="space-y-8 fade-in">

              {/* Metrics */}
              <section>
                <h2 className="text-lg font-bold mb-4 text-[var(--tv-text)]">Performance Overview</h2>
                <MetricsGrid results={result.results} currency={currency} />
                <div className="mt-4">
                  <RegimeBreakdown results={result.results} currency={currency} />
                </div>
              </section>

              {/* Tab bar */}
              <div className="flex gap-2 p-1 bg-white rounded-full tv-soft-shadow w-max">
                {([
                  { key: 'charts',     label: '📈 Charts'     },
                  { key: 'trades',     label: '📋 Trade Log'  },
                  { key: 'report',     label: '📄 Summary'    },
                  ...(result.validation
                    ? [{ key: 'validation', label: '🔬 Validation' }]
                    : []),
                ] as const).map(t => (
                  <button key={t.key} onClick={() => setTab(t.key as MainTab)}
                    className={`px-6 py-2 rounded-full text-sm font-semibold transition-all ${
                      tab === t.key 
                        ? 'bg-[var(--tv-accent)] text-white shadow-sm' 
                        : 'text-gray-500 hover:bg-gray-50'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="bg-white rounded-3xl p-6 tv-soft-shadow">
                {tab === 'charts' && (
                  <ChartsPanel
                    series={result.series}
                    initialCapital={result.results.initial_capital ?? form.capital}
                    currency={currency}
                    validation={result.validation}
                  />
                )}
                {tab === 'trades' && (
                  <TradeLog trades={result.series.trades} currency={currency} />
                )}
                {tab === 'report' && (
                  <ReportTab result={result} symbol={symbol} form={form} currency={currency} />
                )}
                {tab === 'validation' && result.validation && (
                  <ValidationPanel validation={result.validation} currency={currency} />
                )}
              </div>
            </div>
          )}

        </div>
      </main>
      </div>
      )}

      {/* ── Feedback widget (floating, always visible once identified) ── */}
      {identified && (
        <FeedbackWidget
          page={page}
          context={{ symbol: form.symbol === '__custom__' ? form.customSymbol : form.symbol, strategy: form.strategy }}
        />
      )}
    </div>
  );
}


/* ── Welcome screen (Pastel Dashboard Style) ────────────────────────── */
function WelcomeScreen() {
  return (
    <div className="fade-in">
      
      <h2 className="text-xl font-bold text-[var(--tv-text)] mb-4">Popular Strategies</h2>
      
      {/* Pastel Feature Cards mimicking TradeVed Dashboard */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
        
        {/* GRID Card (Light Green) */}
        <div className="relative overflow-hidden rounded-[24px] p-6 transition-all hover:-translate-y-1 hover:shadow-lg"
             style={{ backgroundColor: 'var(--tv-pastel-green)' }}>
          <div className="flex justify-center my-6">
            <span className="text-5xl">🕸️</span>
          </div>
          <h3 className="text-lg font-bold text-green-900">Grid Trading</h3>
          <p className="text-sm text-green-800 mt-1 opacity-90">Capture volatility in ranging markets. Auto-detect bounds.</p>
          <div className="mt-4 flex gap-2 text-[10px] font-semibold text-green-700">
            <span className="bg-white/50 px-2 py-1 rounded-full">Automated</span>
            <span className="bg-white/50 px-2 py-1 rounded-full">Sideways</span>
          </div>
        </div>

        {/* DCA Card (Light Pink) */}
        <div className="relative overflow-hidden rounded-[24px] p-6 transition-all hover:-translate-y-1 hover:shadow-lg"
             style={{ backgroundColor: 'var(--tv-pastel-pink)' }}>
          <div className="flex justify-center my-6">
            <span className="text-5xl">📉</span>
          </div>
          <h3 className="text-lg font-bold text-pink-900">Dollar Cost Avg</h3>
          <p className="text-sm text-pink-800 mt-1 opacity-90">Accumulate assets over time to mitigate price drops.</p>
          <div className="mt-4 flex gap-2 text-[10px] font-semibold text-pink-700">
            <span className="bg-white/50 px-2 py-1 rounded-full">Investment</span>
            <span className="bg-white/50 px-2 py-1 rounded-full">Long-term</span>
          </div>
        </div>

        {/* PLA Card (Light Blue) */}
        <div className="relative overflow-hidden rounded-[24px] p-6 transition-all hover:-translate-y-1 hover:shadow-lg"
             style={{ backgroundColor: 'var(--tv-pastel-blue)' }}>
          <div className="flex justify-center my-6">
            <span className="text-5xl">📈</span>
          </div>
          <h3 className="text-lg font-bold text-blue-900">Price Level Avg</h3>
          <p className="text-sm text-blue-800 mt-1 opacity-90">EMA crossover entries with cascading buy levels.</p>
          <div className="mt-4 flex gap-2 text-[10px] font-semibold text-blue-700">
            <span className="bg-white/50 px-2 py-1 rounded-full">Trend</span>
            <span className="bg-white/50 px-2 py-1 rounded-full">Bullish</span>
          </div>
        </div>

      </div>

    </div>
  );
}


/* ── Report tab ─────────────────────────────────────────────────────────── */
function ReportTab({ result, symbol, form, currency = '$' }: {
  result: BacktestResponse; symbol: string; form: FormState; currency?: string;
}) {
  const r = result.results;
  return (
    <div className="fade-in space-y-6">
      
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Execution Summary</h2>
          <p className="text-sm text-gray-500">Overview of backtest parameters and key results.</p>
        </div>
        <div className="px-4 py-2 bg-green-50 text-green-600 rounded-full text-sm font-bold border border-green-200">
          ✅ Success
        </div>
      </div>

      <div className="bg-gray-50 rounded-2xl p-6 border border-gray-100">
        <pre className="text-sm leading-loose text-gray-700 font-mono whitespace-pre-wrap">
{JSON.stringify({
  backtest_id:    result.backtest_id,
  symbol,
  strategy:       form.strategy,
  date_range:     `${form.startDate} → ${form.endDate}`,
  capital:        `${currency}${form.capital.toLocaleString(isIndianSource(form.source) ? 'en-IN' : 'en-US')}`,
  candles:        result.series.timestamps.length,
  total_return:   `${r.total_return_pct >= 0 ? '+' : ''}${r.total_return_pct.toFixed(2)}%`,
  ann_return:     `${(r.annualised_return_pct ?? 0) >= 0 ? '+' : ''}${(r.annualised_return_pct ?? 0).toFixed(2)}%`,
  sharpe_ratio:   r.sharpe_ratio.toFixed(4),
  max_drawdown:   `${r.max_drawdown_pct.toFixed(2)}%`,
  num_trades:     r.num_trades,
  win_rate:       `${r.win_rate.toFixed(1)}%`,
  profit_factor:  r.profit_factor > 999 ? '∞' : r.profit_factor.toFixed(2),
  total_fees:     `${currency}${(r.total_fees_paid ?? 0).toLocaleString(isIndianSource(form.source) ? 'en-IN' : 'en-US', { maximumFractionDigits: 2 })}`,
}, null, 2)}
        </pre>
      </div>
    </div>
  );
}
