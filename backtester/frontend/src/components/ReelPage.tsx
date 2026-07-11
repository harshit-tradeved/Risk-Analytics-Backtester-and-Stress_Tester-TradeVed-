import { useState } from 'react';
import { analyzeReel, backtestFromIR, improveReelStrategy, isIndianSource } from '../api';
import { ReelAnalysisResponse, StrategyIR, BacktestResponse, ImproveResponse } from '../types';
import StrategyIREditor from './StrategyIREditor';
import PlainLanguageVerdict from './PlainLanguageVerdict';
import MetricsGrid  from './MetricsGrid';
import ChartsPanel  from './ChartsPanel';
import StrategyImprovement from './StrategyImprovement';

// ── Small helpers ────────────────────────────────────────────────────────────
const today = new Date();
const fmt   = (d: Date) => d.toISOString().split('T')[0];
const yr1   = fmt(new Date(today.getTime() - 365 * 86_400_000));
const yr3   = fmt(new Date(today.getTime() - 3 * 365 * 86_400_000));

type AnalysisStage = 'idle' | 'extracting' | 'review' | 'running' | 'done' | 'error';

// ── Backtest config form state ───────────────────────────────────────────────
interface BacktestConfig {
  symbol:    string;
  source:    string;
  interval:  string;
  startDate: string;
  endDate:   string;
  capital:   number;
}

const DEFAULT_CONFIG: BacktestConfig = {
  symbol:    'BTC/USDT',
  source:    'binance',
  interval:  '1d',
  startDate: yr3,
  endDate:   fmt(today),
  capital:   10_000,
};

// ── Triage result card ───────────────────────────────────────────────────────
function TriageRejected({ analysis }: { analysis: ReelAnalysisResponse }) {
  const { triage } = analysis;
  const typeLabel: Record<string, string> = {
    market_commentary: 'Market Commentary',
    motivational:      'Motivational Content',
    advertisement:     'Advertisement',
    partial_strategy:  'Partial Strategy (missing entry or exit rules)',
    unknown:           'Unknown',
  };
  return (
    <div className="max-w-2xl mx-auto mt-12 text-center">
      <div className="w-16 h-16 rounded-full bg-orange-50 flex items-center justify-center mx-auto mb-4 text-2xl">🚫</div>
      <h3 className="text-lg font-semibold text-gray-900 mb-2">No testable strategy found</h3>
      <p className="text-gray-500 text-sm mb-4">
        This reel appears to be <strong>{typeLabel[triage.type] ?? triage.type}</strong>.
      </p>
      {triage.reason && (
        <p className="text-xs text-gray-400 italic max-w-md mx-auto">"{triage.reason}"</p>
      )}
      <p className="text-sm text-gray-400 mt-4">
        Try a reel where the creator explains specific entry/exit rules
        (e.g. "Buy when RSI drops below 30, sell when it crosses above 70").
      </p>
    </div>
  );
}

// ── Config form ──────────────────────────────────────────────────────────────
function ConfigForm({ config, onChange }: {
  config: BacktestConfig;
  onChange: (c: BacktestConfig) => void;
}) {
  const upd = (k: keyof BacktestConfig, v: string | number) =>
    onChange({ ...config, [k]: v });

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      <h3 className="font-semibold text-gray-900 text-sm mb-4">Backtest Settings</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Symbol</label>
          <input className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400"
            value={config.symbol} onChange={e => upd('symbol', e.target.value)} placeholder="BTC/USDT" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Source</label>
          <select className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400"
            value={config.source} onChange={e => upd('source', e.target.value)}>
            <option value="binance">Binance (Crypto)</option>
            <option value="yfinance">Yahoo Finance (US Stocks)</option>
            <option value="nse">NSE (India)</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Interval</label>
          <select className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400"
            value={config.interval} onChange={e => upd('interval', e.target.value)}>
            {['1d','4h','1h','15m','1w'].map(i => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Capital</label>
          <input type="number" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400"
            value={config.capital} onChange={e => upd('capital', Number(e.target.value))} />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Start Date</label>
          <input type="date" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400"
            value={config.startDate} onChange={e => upd('startDate', e.target.value)} />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">End Date</label>
          <input type="date" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400"
            value={config.endDate} onChange={e => upd('endDate', e.target.value)} />
        </div>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function ReelPage() {
  const [inputMode,  setInputMode]  = useState<'url' | 'transcript'>('transcript');
  const [url,        setUrl]        = useState('');
  const [transcript, setTranscript] = useState('');
  const [caption,    setCaption]    = useState('');
  const [config,     setConfig]     = useState<BacktestConfig>(DEFAULT_CONFIG);

  const [stage,      setStage]      = useState<AnalysisStage>('idle');
  const [analysis,   setAnalysis]   = useState<ReelAnalysisResponse | null>(null);
  const [ir,         setIR]         = useState<StrategyIR | null>(null);
  const [irErrors,   setIrErrors]   = useState<string[]>([]);
  const [btResult,   setBtResult]   = useState<BacktestResponse | null>(null);
  const [errorMsg,   setErrorMsg]   = useState('');
  const [btError,    setBtError]    = useState('');

  const [improveStage,  setImproveStage]  = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [improveResult, setImproveResult] = useState<ImproveResponse | null>(null);
  const [improveError,  setImproveError]  = useState('');

  async function handleAnalyze() {
    setStage('extracting');
    setAnalysis(null);
    setIR(null);
    setBtResult(null);
    setErrorMsg('');
    setBtError('');
    try {
      const res = await analyzeReel({
        url:        inputMode === 'url' ? url : undefined,
        transcript: inputMode === 'transcript' ? transcript : undefined,
        caption:    caption || undefined,
      });
      setAnalysis(res);
      // Auto-fill config from reel-extracted suggestions
      if (res.suggested_symbol || res.suggested_source || res.suggested_interval) {
        setConfig(prev => ({
          ...prev,
          ...(res.suggested_symbol   ? { symbol:   res.suggested_symbol }   : {}),
          ...(res.suggested_source   ? { source:   res.suggested_source }   : {}),
          ...(res.suggested_interval ? { interval: res.suggested_interval } : {}),
        }));
      }
      setIrErrors(res.ir_errors ?? []);
      if (res.strategy_ir) {
        setIR(res.strategy_ir);
        setStage('review');
      } else {
        setStage('review');
      }
    } catch (e: any) {
      setErrorMsg(e.message ?? 'Analysis failed');
      setStage('error');
    }
  }

  async function handleRunBacktest() {
    if (!ir) return;
    setStage('running');
    setBtError('');
    try {
      const res = await backtestFromIR(ir, {
        symbol:          config.symbol,
        source:          config.source,
        interval:        config.interval,
        startDate:       config.startDate,
        endDate:         config.endDate,
        capital:         config.capital,
        useIndianCosts:  isIndianSource(config.source),
      });
      setBtResult(res);
      setStage('done');
    } catch (e: any) {
      // Go back to review so user keeps extracted IR; show error above confirm button
      setBtError(e.message ?? 'Backtest failed');
      setStage('review');
    }
  }

  async function handleImprove() {
    if (!ir || !btResult) return;
    setImproveStage('loading');
    setImproveError('');
    try {
      const res = await improveReelStrategy(ir, btResult.results, {
        gaps:       analysis?.gaps ?? [],
        transcript: analysis?.transcript,
        symbol:          config.symbol,
        source:          config.source,
        interval:        config.interval,
        startDate:       config.startDate,
        endDate:         config.endDate,
        capital:         config.capital,
        useIndianCosts:  isIndianSource(config.source),
      });
      setImproveResult(res);
      setImproveStage('done');
    } catch (e: any) {
      setImproveError(e.message ?? 'Improvement pipeline failed');
      setImproveStage('error');
    }
  }

  const currency = btResult?.currency ?? (isIndianSource(config.source) ? '₹' : '$');

  return (
    <div className="h-full overflow-y-auto bg-[var(--tv-bg)]">
      <div className="max-w-5xl mx-auto p-6">

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-gray-900">🎬 Reel Backtest</h1>
          <p className="text-sm text-gray-500 mt-1">
            Paste a trading strategy from any reel — we'll extract the rules and backtest them for you.
          </p>
        </div>

        {/* ── Input section ──────────────────────────────────────────────── */}
        {stage === 'idle' && (
          <div className="space-y-4">
            {/* Mode toggle */}
            <div className="flex gap-1 bg-gray-100 rounded-full p-1 w-fit">
              {(['transcript', 'url'] as const).map(m => (
                <button key={m} onClick={() => setInputMode(m)}
                  className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all ${
                    inputMode === m
                      ? 'bg-white text-indigo-600 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}>
                  {m === 'transcript' ? '📝 Paste Transcript' : '🔗 Paste URL'}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="col-span-2 space-y-4">
                {inputMode === 'url' ? (
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Reel / Video URL</label>
                    <input
                      className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:border-indigo-400"
                      value={url}
                      onChange={e => setUrl(e.target.value)}
                      placeholder="https://www.instagram.com/reel/..."
                    />
                    <p className="text-xs text-gray-400 mt-1">
                      Requires the ingestion service to be configured (INGESTION_API_URL).
                    </p>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Strategy Transcript</label>
                    <textarea
                      className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 h-32 resize-y focus:outline-none focus:border-indigo-400"
                      value={transcript}
                      onChange={e => setTranscript(e.target.value)}
                      placeholder={'Paste the spoken text or caption from the reel here.\n\nExample: "Buy when RSI drops below 30 and price is above the 50 EMA. Sell when RSI crosses above 70."'}
                    />
                  </div>
                )}
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Caption (optional)</label>
                  <textarea
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2.5 h-16 resize-y focus:outline-none focus:border-indigo-400"
                    value={caption}
                    onChange={e => setCaption(e.target.value)}
                    placeholder="Paste the post caption here for better extraction accuracy"
                  />
                </div>
              </div>

              <ConfigForm config={config} onChange={setConfig} />
            </div>

            <button
              onClick={handleAnalyze}
              disabled={!transcript && !url}
              className={`px-6 py-2.5 rounded-lg font-semibold text-sm transition-all ${
                (!transcript && !url)
                  ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
                  : 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm'
              }`}>
              Extract Strategy →
            </button>
          </div>
        )}

        {/* ── Extracting spinner ─────────────────────────────────────────── */}
        {stage === 'extracting' && (
          <div className="max-w-lg mx-auto mt-16 text-center">
            <div className="w-12 h-12 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mx-auto mb-4" />
            <p className="text-gray-700 font-medium">Analyzing strategy…</p>
            <p className="text-gray-400 text-sm mt-1">Triaging content → extracting rules → building IR</p>
          </div>
        )}

        {/* ── Review / HITL stage ────────────────────────────────────────── */}
        {stage === 'review' && analysis && (
          <div>
            {/* Transcript chip */}
            <div className="mb-4 flex items-center gap-2">
              <span className="text-xs text-gray-400">Confidence:</span>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                analysis.confidence >= 0.7 ? 'bg-green-50 text-green-700' :
                analysis.confidence >= 0.4 ? 'bg-yellow-50 text-yellow-700' :
                'bg-red-50 text-red-700'
              }`}>
                {(analysis.confidence * 100).toFixed(0)}%
              </span>
              <button onClick={() => { setStage('idle'); }}
                className="ml-auto text-xs text-gray-400 hover:text-gray-600">
                ← Start over
              </button>
            </div>

            {!analysis.strategy_ir ? (
              <TriageRejected analysis={analysis} />
            ) : (
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2">
                  {btError && (
                    <div className="mb-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
                      <span className="font-semibold">Backtest failed:</span> {btError}
                    </div>
                  )}
                  <StrategyIREditor
                    ir={ir!}
                    gaps={analysis.gaps}
                    onChange={updated => { setIR(updated); setIrErrors([]); }}
                    onConfirm={handleRunBacktest}
                    loading={false}
                    serverErrors={irErrors}
                  />
                </div>
                <ConfigForm config={config} onChange={setConfig} />
              </div>
            )}
          </div>
        )}

        {/* ── Running backtest spinner ───────────────────────────────────── */}
        {stage === 'running' && (
          <div className="max-w-lg mx-auto mt-16 text-center">
            <div className="w-12 h-12 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mx-auto mb-4" />
            <p className="text-gray-700 font-medium">Running backtest…</p>
            <p className="text-gray-400 text-sm mt-1">Fetching data, simulating trades, computing metrics</p>
          </div>
        )}

        {/* ── Results ────────────────────────────────────────────────────── */}
        {stage === 'done' && btResult && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold text-gray-900">Results</h2>
              <button onClick={() => {
                setStage('idle'); setBtResult(null); setAnalysis(null);
                setImproveStage('idle'); setImproveResult(null); setImproveError('');
              }}
                className="text-xs text-gray-400 hover:text-gray-600">← Analyze another reel</button>
            </div>

            <PlainLanguageVerdict
              result={btResult}
              symbol={config.symbol}
              capital={config.capital}
              currency={currency}
              closePrices={btResult.series?.close_prices}
            />

            <MetricsGrid
              results={btResult.results}
              currency={currency}
            />

            <ChartsPanel
              series={btResult.series}
              initialCapital={btResult.results.initial_capital ?? config.capital}
              currency={currency}
              validation={btResult.validation}
            />

            {/* ── Diagnose & Improve ─────────────────────────────────────── */}
            {improveStage === 'idle' && (
              <div className="mt-6 text-center">
                <button
                  onClick={handleImprove}
                  className="px-6 py-2.5 rounded-lg font-semibold text-sm bg-gray-900 text-white hover:bg-gray-800 shadow-sm transition-all">
                  🔍 Diagnose Problems & Try to Improve This Strategy
                </button>
                <p className="text-xs text-gray-400 mt-2">
                  An LLM will identify real problems, propose a fix, and we'll actually re-run it — no fabricated results.
                </p>
              </div>
            )}

            {improveStage === 'loading' && (
              <div className="mt-8 text-center">
                <div className="w-10 h-10 border-4 border-gray-200 border-t-gray-800 rounded-full animate-spin mx-auto mb-3" />
                <p className="text-gray-700 font-medium text-sm">Diagnosing, improving, re-running, and judging…</p>
                <p className="text-gray-400 text-xs mt-1">This runs a real backtest on the improved strategy — may take a bit longer.</p>
              </div>
            )}

            {improveStage === 'error' && (
              <div className="mt-6 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
                <span className="font-semibold">Improvement pipeline failed:</span> {improveError}
                <button onClick={handleImprove} className="ml-3 text-xs underline">Retry</button>
              </div>
            )}

            {improveStage === 'done' && improveResult && (
              <StrategyImprovement result={improveResult} currency={currency} />
            )}
          </div>
        )}

        {/* ── Extraction error ───────────────────────────────────────────── */}
        {stage === 'error' && (
          <div className="max-w-2xl mx-auto mt-12 text-center">
            <div className="w-16 h-16 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4 text-2xl">⚠️</div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Analysis failed</h3>
            {errorMsg && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-4 text-left">{errorMsg}</p>
            )}
            <button
              onClick={() => { setStage('idle'); setErrorMsg(''); }}
              className="px-5 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 transition-colors">
              ← Try again
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
