import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceDot, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { ForecastFormState, PaperBarEvent, PaperTrade, PaperSetupEvent, PaperCompleteEvent } from '@app/types';
import { streamPaperTrade } from '@app/api';

// ── Speed control presets ─────────────────────────────────────────────────────
const SPEED_OPTS = [
  { label: 'Slow',   ms: 1500 },
  { label: 'Normal', ms: 400  },
  { label: 'Fast',   ms: 100  },
  { label: 'Turbo',  ms: 50   },
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n: number, d = 2) { return n.toFixed(d); }
function sign(n: number, d = 2) { return n >= 0 ? `+${n.toFixed(d)}` : n.toFixed(d); }
function pct(n: number) { return sign(n) + '%'; }

function SignalBadge({ signal }: { signal: string }) {
  if (signal === 'BUY')  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-teal-100 text-teal-700">BUY</span>;
  if (signal === 'SELL') return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-600">SELL</span>;
  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-gray-100 text-gray-400">HOLD</span>;
}

// ── Price chart with BUY/SELL markers ─────────────────────────────────────────
interface ChartPoint { idx: number; price: number; equity: number; signal?: string }

function PriceChart({
  points, capital, currency,
}: { points: ChartPoint[]; capital: number; currency: string }) {
  if (points.length < 2) return (
    <div className="flex items-center justify-center h-48 text-gray-300 text-sm">
      Waiting for bars…
    </div>
  );

  const buys  = points.filter(p => p.signal === 'BUY');
  const sells = points.filter(p => p.signal === 'SELL');

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="idx" tick={{ fontSize: 10 }} tickLine={false} />
        <YAxis
          domain={['auto', 'auto']}
          tick={{ fontSize: 10 }}
          tickLine={false}
          tickFormatter={v => `${currency}${(v as number).toLocaleString()}`}
          width={70}
        />
        <Tooltip
          formatter={(v: number) => [`${currency}${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`, 'Price']}
          labelFormatter={l => `Bar ${l}`}
          contentStyle={{ fontSize: 12, borderRadius: 8 }}
        />
        <Line type="monotone" dataKey="price" stroke="#6366f1" strokeWidth={2} dot={false} />
        {buys.map(p => (
          <ReferenceDot key={`b${p.idx}`} x={p.idx} y={p.price}
            r={5} fill="#14b8a6" stroke="#fff" strokeWidth={1.5} />
        ))}
        {sells.map(p => (
          <ReferenceDot key={`s${p.idx}`} x={p.idx} y={p.price}
            r={5} fill="#ef4444" stroke="#fff" strokeWidth={1.5} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Equity chart ──────────────────────────────────────────────────────────────
function EquityChart({
  points, capital, currency,
}: { points: ChartPoint[]; capital: number; currency: string }) {
  if (points.length < 2) return null;
  return (
    <ResponsiveContainer width="100%" height={120}>
      <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="idx" tick={false} tickLine={false} height={0} />
        <YAxis
          domain={['auto', 'auto']}
          tick={{ fontSize: 10 }} tickLine={false}
          tickFormatter={v => `${currency}${(v as number / 1000).toFixed(1)}k`}
          width={50}
        />
        <ReferenceLine y={capital} stroke="#cbd5e1" strokeDasharray="4 2" />
        <Tooltip
          formatter={(v: number) => [`${currency}${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`, 'Equity']}
          labelFormatter={l => `Bar ${l}`}
          contentStyle={{ fontSize: 12, borderRadius: 8 }}
        />
        <Line type="monotone" dataKey="equity" stroke="#f97316" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface PaperState {
  status:      'idle' | 'running' | 'complete' | 'error';
  setup?:      PaperSetupEvent;
  bars:        PaperBarEvent[];
  trades:      PaperTrade[];
  finalMetrics?: Record<string, number>;
  errorMsg?:   string;
}

const EMPTY: PaperState = { status: 'idle', bars: [], trades: [] };

export default function PaperTradeView({
  form,
  currency,
  locale,
}: {
  form:     ForecastFormState;
  currency: string;
  locale:   string;
}) {
  const [state,   setState]   = useState<PaperState>(EMPTY);
  const [speedMs, setSpeedMs] = useState(400);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Keep latest speed accessible from inside the running callback without restart
  const speedRef = useRef(speedMs);
  useEffect(() => { speedRef.current = speedMs; }, [speedMs]);

  const handleStart = useCallback(() => {
    cleanupRef.current?.();
    setState({ status: 'running', bars: [], trades: [] });

    const cleanup = streamPaperTrade(form, speedMs, {
      onSetup: (evt) => setState(prev => ({ ...prev, setup: evt })),

      onBar: (evt) => setState(prev => ({
        ...prev,
        bars: [...prev.bars, evt],
        trades: evt.trade
          ? prev.trades.some(t => t.entry_time === evt.trade!.entry_time && t.exit_time === evt.trade!.exit_time)
            ? prev.trades
            : [...prev.trades, evt.trade]
          : prev.trades,
      })),

      onComplete: (evt: PaperCompleteEvent) => setState(prev => ({
        ...prev,
        status: 'complete',
        finalMetrics: evt.metrics,
        trades: evt.trades,
      })),

      onError: (msg) => setState(prev => ({ ...prev, status: 'error', errorMsg: msg })),
    });

    cleanupRef.current = cleanup;
  }, [form, speedMs]);

  const handleStop = () => {
    cleanupRef.current?.();
    setState(prev => ({ ...prev, status: 'idle' }));
  };

  const { status, bars, trades, finalMetrics, errorMsg, setup } = state;

  const latest  = bars[bars.length - 1];
  const equity  = latest?.equity  ?? form.capital;
  const pnl     = equity - form.capital;
  const pnlPct  = (pnl / form.capital) * 100;

  const chartPoints: ChartPoint[] = bars.map(b => ({
    idx:    b.bar_idx,
    price:  b.candle.close,
    equity: b.equity,
    signal: b.signal,
  }));

  return (
    <div className="space-y-4">
      {/* ── Controls ── */}
      <div className="bg-white rounded-2xl tv-soft-shadow p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <p className="text-sm font-bold text-gray-700">AI Paper Trading</p>
            <p className="text-xs text-gray-400 mt-0.5">
              Watch your strategy trade bar-by-bar on a single AI-generated future path.
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Speed picker */}
            <div className="flex rounded-xl overflow-hidden border border-gray-200 text-xs font-semibold">
              {SPEED_OPTS.map(o => (
                <button key={o.ms} onClick={() => setSpeedMs(o.ms)}
                  className={`px-2.5 py-1.5 transition-all ${
                    speedMs === o.ms ? 'bg-indigo-500 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'
                  }`}>
                  {o.label}
                </button>
              ))}
            </div>

            {status === 'running' ? (
              <button onClick={handleStop}
                className="px-4 py-2 rounded-full bg-red-50 text-red-600 border border-red-200 text-sm font-semibold hover:bg-red-100 transition-all">
                Stop
              </button>
            ) : (
              <button onClick={handleStart}
                className="px-5 py-2 rounded-full bg-indigo-500 text-white text-sm font-semibold hover:bg-indigo-600 shadow-sm transition-all">
                {status === 'complete' ? 'Replay' : 'Start Paper Trade'}
              </button>
            )}
          </div>
        </div>

        {/* Setup info pill */}
        {setup && (
          <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
            {[
              ['Symbol',   setup.symbol],
              ['Strategy', setup.strategy],
              ['Horizon',  `${setup.horizon} bars`],
              ['Capital',  `${currency}${setup.capital.toLocaleString()}`],
              ['Method',   setup.method === 'kronos' ? 'Kronos AI' : 'Block Bootstrap'],
            ].map(([k, v]) => (
              <span key={k} className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
                <span className="text-gray-400">{k}: </span>{v}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ── Error ── */}
      {status === 'error' && (
        <div className="p-4 rounded-2xl bg-red-50 border border-red-100 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      {/* ── Live stats strip ── */}
      {bars.length > 0 && (
        <div className="bg-white rounded-2xl tv-soft-shadow overflow-hidden">
          {/* Stats row */}
          <div className="grid grid-cols-4 divide-x divide-gray-50 border-b border-gray-50">
            {[
              { label: 'Equity',   value: `${currency}${equity.toLocaleString(locale, { maximumFractionDigits: 0 })}`,
                color: pnl >= 0 ? 'text-teal-600' : 'text-red-500' },
              { label: 'P&L',      value: `${sign(pnl, 0)} (${pct(pnlPct)})`,
                color: pnl >= 0 ? 'text-teal-600' : 'text-red-500' },
              { label: 'Position', value: latest ? `${fmt(latest.position_qty, 4)} × ${currency}${fmt(latest.candle.close)}` : '—',
                color: 'text-gray-700' },
              { label: 'Bar',      value: latest ? `${latest.bar_idx + 1} / ${latest.total}` : '—',
                color: 'text-gray-700' },
            ].map(({ label, value, color }) => (
              <div key={label} className="px-4 py-3 text-center">
                <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">{label}</p>
                <p className={`text-sm font-bold ${color} tabular-nums`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Current signal */}
          {latest && latest.signal !== 'HOLD' && (
            <div className={`px-6 py-2 border-b text-xs flex items-center gap-2 ${
              latest.signal === 'BUY' ? 'bg-teal-50 border-teal-100 text-teal-700'
                                     : 'bg-red-50 border-red-100 text-red-600'
            }`}>
              <SignalBadge signal={latest.signal} />
              <span>at {currency}{fmt(latest.candle.close)} — qty {fmt(latest.quantity, 4)}</span>
              {latest.trade && (
                <span className="ml-2 font-semibold">
                  Trade P&L: {pct(latest.trade.pnl_pct)}
                </span>
              )}
            </div>
          )}

          {/* Price chart */}
          <div className="px-4 pt-4 pb-2">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-gray-400 mb-2">
              Price — teal dot = BUY · red dot = SELL
            </p>
            <PriceChart points={chartPoints} capital={form.capital} currency={currency} />
          </div>

          {/* Equity chart */}
          <div className="px-4 pb-4">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-gray-400 mb-1 mt-2">
              Equity curve
            </p>
            <EquityChart points={chartPoints} capital={form.capital} currency={currency} />
          </div>
        </div>
      )}

      {/* ── Trade log ── */}
      {trades.length > 0 && (
        <div className="bg-white rounded-2xl tv-soft-shadow overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-50">
            <p className="text-xs font-bold text-gray-600 uppercase tracking-wider">
              Trade Log — {trades.length} trade{trades.length !== 1 ? 's' : ''}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-50">
                  {['#', 'Entry', 'Exit', 'Qty', 'Entry P', 'Exit P', 'P&L', 'P&L %', 'Fees'].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const won = t.pnl >= 0;
                  return (
                    <tr key={i} className="border-b border-gray-50 hover:bg-gray-50/50">
                      <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                      <td className="px-3 py-2 text-gray-500">{t.entry_time.slice(0, 10)}</td>
                      <td className="px-3 py-2 text-gray-500">{t.exit_time.slice(0, 10)}</td>
                      <td className="px-3 py-2 text-gray-700">{fmt(t.quantity, 4)}</td>
                      <td className="px-3 py-2 text-gray-700">{currency}{fmt(t.entry_price)}</td>
                      <td className="px-3 py-2 text-gray-700">{currency}{fmt(t.exit_price)}</td>
                      <td className={`px-3 py-2 font-semibold ${won ? 'text-teal-600' : 'text-red-500'}`}>
                        {currency}{fmt(t.pnl)}
                      </td>
                      <td className={`px-3 py-2 font-semibold ${won ? 'text-teal-600' : 'text-red-500'}`}>
                        {pct(t.pnl_pct)}
                      </td>
                      <td className="px-3 py-2 text-gray-400">{fmt(t.fees)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Final metrics ── */}
      {status === 'complete' && finalMetrics && (
        <div className="bg-white rounded-2xl tv-soft-shadow p-5">
          <p className="text-xs font-bold text-gray-600 uppercase tracking-wider mb-3">
            Final Results
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              ['Total Return', pct(finalMetrics.total_return_pct ?? 0)],
              ['Sharpe Ratio', fmt(finalMetrics.sharpe_ratio ?? 0, 3)],
              ['Max Drawdown', pct(finalMetrics.max_drawdown_pct ?? 0)],
              ['Win Rate',     fmt(finalMetrics.win_rate ?? 0, 1) + '%'],
              ['Total Trades', String(finalMetrics.num_trades ?? 0)],
              ['Final Equity', `${currency}${(finalMetrics.final_equity ?? form.capital).toLocaleString(locale, { maximumFractionDigits: 0 })}`],
            ].map(([label, value]) => (
              <div key={label} className="bg-gray-50 rounded-xl p-3">
                <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">{label}</p>
                <p className="text-sm font-bold text-gray-700 tabular-nums">{value}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
