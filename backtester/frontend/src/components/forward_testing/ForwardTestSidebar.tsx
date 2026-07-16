import React, { useState, useEffect } from 'react';
import { ForecastFormState, Strategy, DataSource, Interval, StrategyMeta, CLASSIC_STRATEGIES } from '../../types';
import { fetchStrategies, isIndianSource } from '../../api';
import StrategyParamsForm, { defaultsFromSchema } from '../shared/StrategyParamsForm';
import RuleBuilder, { defaultCustomParams } from '../shared/RuleBuilder';

const CLASSIC_SET = new Set<string>(CLASSIC_STRATEGIES);

// ── Symbol options (mirrors Sidebar.tsx / StressSidebar.tsx) ─────────────────

const SYMBOL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  binance: [
    { value: 'BTC/USDT',   label: 'BTC/USDT — Bitcoin'    },
    { value: 'ETH/USDT',   label: 'ETH/USDT — Ethereum'   },
    { value: 'BNB/USDT',   label: 'BNB/USDT — BNB'        },
    { value: 'SOL/USDT',   label: 'SOL/USDT — Solana'     },
    { value: 'XRP/USDT',   label: 'XRP/USDT — Ripple'     },
    { value: 'ADA/USDT',   label: 'ADA/USDT — Cardano'    },
    { value: 'DOGE/USDT',  label: 'DOGE/USDT — Dogecoin'  },
    { value: '__custom__', label: '✏️ Custom…'              },
  ],
  yfinance: [
    { value: 'AAPL',       label: 'AAPL — Apple'           },
    { value: 'MSFT',       label: 'MSFT — Microsoft'       },
    { value: 'NVDA',       label: 'NVDA — NVIDIA'          },
    { value: 'GOOGL',      label: 'GOOGL — Alphabet'       },
    { value: 'SPY',        label: 'SPY — S&P 500 ETF'      },
    { value: 'QQQ',        label: 'QQQ — Nasdaq 100 ETF'   },
    { value: '__custom__', label: '✏️ Custom…'              },
  ],
  nse: [
    { value: 'NIFTY50',    label: 'NIFTY50 — Index'        },
    { value: 'BANKNIFTY',  label: 'BANKNIFTY — Bank Index' },
    { value: 'RELIANCE',   label: 'RELIANCE'               },
    { value: 'TCS',        label: 'TCS'                    },
    { value: 'HDFCBANK',   label: 'HDFCBANK'               },
    { value: 'INFY',       label: 'INFY — Infosys'         },
    { value: 'SBIN',       label: 'SBIN — SBI'             },
    { value: '__custom__', label: '✏️ Custom…'              },
  ],
  bse: [
    { value: 'SENSEX',     label: 'SENSEX — BSE Index'     },
    { value: 'RELIANCE',   label: 'RELIANCE'               },
    { value: '__custom__', label: '✏️ Custom…'              },
  ],
};

// ── Horizon / n_paths presets ────────────────────────────────────────────────

const HORIZON_PRESETS = [
  { label: '30d',  value: 30  },
  { label: '60d',  value: 60  },
  { label: '90d',  value: 90  },
  { label: '180d', value: 180 },
  { label: '365d', value: 365 },
];

const NPATHS_PRESETS = [
  { label: '50',  value: 50  },
  { label: '100', value: 100 },
  { label: '200', value: 200 },
  { label: '500', value: 500 },
];

// ── Date helpers ──────────────────────────────────────────────────────────────

const today = new Date();
const fmt   = (d: Date) => d.toISOString().split('T')[0];
const ago   = (days: number) => fmt(new Date(today.getTime() - days * 86_400_000));

const DATE_PRESETS = [
  { label: '1M', days: 30  },
  { label: '3M', days: 90  },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
  { label: '2Y', days: 730 },
  { label: '5Y', days: 1825},
];

// ── Default form ──────────────────────────────────────────────────────────────

export const DEFAULT_FORECAST_FORM: ForecastFormState = {
  symbol: 'BTC/USDT', customSymbol: 'BTC/USDT',
  source: 'binance', startDate: ago(365), endDate: fmt(today),
  datePreset: '1Y', interval: '1d',
  capital: 10_000, feePct: 0.10, slippagePct: 0.05,
  strategy: 'DCA', strategyParams: {},
  lowerBound: 20_000, upperBound: 70_000, numLevels: 5,
  gridSpacing: 'linear', gridInvestPerLevel: 500,
  buyIntervalHours: 24, dcaInvestPerBuy: 200, holdDays: 30,
  dcaExitType: 'time', profitTargetPct: 10,
  fastEma: 12, slowEma: 26,
  plaExitType: 'crossover', takeProfitPct: 5, stopLossPct: 3,
  plaLvl2Pct: -1, plaLvl3Pct: -2.5, plaLvl4Pct: -4, plaInvestPerLevel: 300,
  marketType: 'equity_delivery', brokerageModel: 'flat',
  brokerageFlat: 20, brokeragePct: 0.5,
  horizonDays: 90,
  nPaths: 100,
};

// ── Shared UI helpers ─────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] uppercase tracking-widest font-semibold text-[var(--tv-muted)] mb-1">{children}</p>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="text-[10px] uppercase tracking-widest font-bold text-gray-400 mb-2">{title}</p>
      {children}
    </div>
  );
}

function PillGroup<T extends string | number>({
  options, value, onChange, className = '',
}: {
  options: { label: string; value: T }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={`flex flex-wrap gap-1 ${className}`}>
      {options.map(o => (
        <button key={String(o.value)} onClick={() => onChange(o.value)}
          className={`px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${
            value === o.value
              ? 'bg-[var(--tv-accent)] text-white shadow-sm'
              : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
          }`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Main sidebar ──────────────────────────────────────────────────────────────

// ── Crisis scenario labels (mirrors SCENARIO_PRESETS in stress.py) ─────────────

const CRISIS_SCENARIOS = [
  { value: 'covid_crash',        label: 'COVID Crash'         },
  { value: 'gfc_2008',           label: 'GFC 2008'            },
  { value: 'luna_collapse',      label: 'LUNA Collapse'       },
  { value: 'slow_bleed',         label: 'Slow Bleed'          },
  { value: 'flash_crash',        label: 'Flash Crash'         },
  { value: 'pump_dump',          label: 'Pump & Dump'         },
  { value: 'vol_spike',          label: 'Vol Spike'           },
  { value: 'trend_reversal',     label: 'Trend Reversal'      },
  { value: 'gap_risk',           label: 'Gap Risk'            },
  { value: 'liquidity_crisis',   label: 'Liquidity Crisis'    },
  { value: 'demonetization_2016',label: 'Demonetization 2016' },
  { value: 'covid_nifty_mar2020',label: 'COVID Nifty Mar 2020'},
  { value: 'yes_bank_2020',      label: 'Yes Bank 2020'       },
  { value: 'expiry_gamma_squeeze',label:'Gamma Squeeze'       },
];

export default function ForwardTestSidebar({
  form, onChange, onRun, loading,
  crisisMode, onCrisisModeChange,
  crisisScenario, onCrisisScenarioChange,
  severity, onSeverityChange,
}: {
  form:     ForecastFormState;
  onChange: (updates: Partial<ForecastFormState>) => void;
  onRun:    () => void;
  loading:  boolean;
  crisisMode:            boolean;
  onCrisisModeChange:    (v: boolean) => void;
  crisisScenario:        string;
  onCrisisScenarioChange:(v: string) => void;
  severity:              number;
  onSeverityChange:      (v: number) => void;
}) {
  const [strategies, setStrategies] = useState<StrategyMeta[]>([]);

  useEffect(() => {
    fetchStrategies().then(setStrategies).catch(() => {});
  }, []);

  const symbolOpts = SYMBOL_OPTIONS[form.source] ?? SYMBOL_OPTIONS.binance;
  const indian     = isIndianSource(form.source);

  function handleSourceChange(src: string) {
    const newSymbol = SYMBOL_OPTIONS[src]?.[0]?.value ?? 'BTC/USDT';
    const newCapital = (src === 'nse' || src === 'bse') ? 500_000 : 10_000;
    onChange({
      source: src as DataSource,
      symbol: newSymbol,
      customSymbol: newSymbol,
      capital: newCapital,
      marketType: 'equity_delivery',
    });
  }

  function handleStrategyChange(name: Strategy) {
    const meta = strategies.find(s => s.name === name);
    if (!meta) { onChange({ strategy: name }); return; }
    if (name === 'CUSTOM') {
      onChange({ strategy: name, strategyParams: defaultCustomParams() });
    } else if (!CLASSIC_SET.has(name) && meta.schema) {
      onChange({ strategy: name, strategyParams: defaultsFromSchema(meta.schema) });
    } else {
      onChange({ strategy: name });
    }
  }

  function setDatePreset(days: number, label: string) {
    onChange({ startDate: ago(days), endDate: fmt(today), datePreset: label });
  }

  const selectedStrategy = strategies.find(s => s.name === form.strategy);
  const isClassic = CLASSIC_SET.has(form.strategy);

  // Group strategies for dropdown
  const grouped = strategies.reduce<Record<string, StrategyMeta[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {});

  return (
    <aside className="w-72 flex-shrink-0 overflow-y-auto bg-[var(--tv-s1)] shadow-sm z-10 border-r border-gray-100">
      <div className="p-4">

        {/* Header */}
        <div className="mb-5">
          <h2 className="text-base font-bold text-[var(--tv-text)]">Forward Test</h2>
          <p className="text-xs text-[var(--tv-muted)] mt-0.5">
            Project strategy performance into synthetic futures
          </p>
        </div>

        {/* ── Data source ───────────────────────────────────────────────── */}
        <Section title="Data Source">
          <div className="flex rounded-xl overflow-hidden border border-gray-200 text-xs font-semibold">
            {(['binance', 'yfinance', 'nse', 'bse'] as DataSource[]).map(src => (
              <button key={src} onClick={() => handleSourceChange(src)}
                className={`flex-1 py-1.5 transition-all ${
                  form.source === src
                    ? 'bg-[var(--tv-accent)] text-white'
                    : 'bg-white text-gray-500 hover:bg-gray-50'
                }`}>
                {src === 'binance' ? 'Crypto' : src === 'yfinance' ? 'US' : src.toUpperCase()}
              </button>
            ))}
          </div>
        </Section>

        {/* ── Symbol ────────────────────────────────────────────────────── */}
        <Section title="Symbol">
          <select value={form.symbol}
            onChange={e => onChange({ symbol: e.target.value, customSymbol: e.target.value })}
            className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30">
            {symbolOpts.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {form.symbol === '__custom__' && (
            <input type="text" value={form.customSymbol}
              onChange={e => onChange({ customSymbol: e.target.value.toUpperCase() })}
              placeholder="e.g. LTC/USDT"
              className="mt-1.5 w-full text-sm border border-gray-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30" />
          )}
        </Section>

        {/* ── Interval ─────────────────────────────────────────────────── */}
        <Section title="Interval">
          <PillGroup
            options={[
              { label: '15m', value: '15m' },
              { label: '1h',  value: '1h'  },
              { label: '4h',  value: '4h'  },
              { label: '1d',  value: '1d'  },
              { label: '1w',  value: '1w'  },
            ]}
            value={form.interval}
            onChange={v => onChange({ interval: v as Interval })}
          />
        </Section>

        {/* ── Historical date range ─────────────────────────────────────── */}
        <Section title="Historical Context">
          <div className="flex flex-wrap gap-1 mb-2">
            {DATE_PRESETS.map(p => (
              <button key={p.label} onClick={() => setDatePreset(p.days, p.label)}
                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold transition-all ${
                  form.datePreset === p.label
                    ? 'bg-[var(--tv-accent)] text-white'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label>From</Label>
              <input type="date" value={form.startDate}
                onChange={e => onChange({ startDate: e.target.value, datePreset: 'custom' })}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30" />
            </div>
            <div>
              <Label>To</Label>
              <input type="date" value={form.endDate}
                onChange={e => onChange({ endDate: e.target.value, datePreset: 'custom' })}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30" />
            </div>
          </div>
        </Section>

        {/* ── Capital & fees ────────────────────────────────────────────── */}
        <Section title="Capital">
          <div className="space-y-2">
            <div>
              <Label>Capital ({indian ? '₹' : '$'})</Label>
              <input type="number" value={form.capital}
                onChange={e => onChange({ capital: +e.target.value })}
                className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30" />
            </div>
            {!indian && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Fee %</Label>
                  <input type="number" step="0.01" value={form.feePct}
                    onChange={e => onChange({ feePct: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30" />
                </div>
                <div>
                  <Label>Slippage %</Label>
                  <input type="number" step="0.01" value={form.slippagePct}
                    onChange={e => onChange({ slippagePct: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30" />
                </div>
              </div>
            )}
          </div>
        </Section>

        {/* ── Strategy ─────────────────────────────────────────────────── */}
        <Section title="Strategy">
          {strategies.length > 0 ? (
            <select value={form.strategy} onChange={e => handleStrategyChange(e.target.value)}
              className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30">
              {Object.entries(grouped).map(([cat, strats]) => (
                <optgroup key={cat} label={cat.charAt(0).toUpperCase() + cat.slice(1)}>
                  {strats.map(s => (
                    <option key={s.name} value={s.name}>{s.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          ) : (
            <select value={form.strategy}
              onChange={e => onChange({ strategy: e.target.value })}
              className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]/30">
              {['GRID','DCA','PLA'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          )}

          {/* Classic GRID params (brief) */}
          {form.strategy === 'GRID' && (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Lower</Label>
                  <input type="number" value={form.lowerBound}
                    onChange={e => onChange({ lowerBound: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
                <div>
                  <Label>Upper</Label>
                  <input type="number" value={form.upperBound}
                    onChange={e => onChange({ upperBound: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Levels</Label>
                  <input type="number" value={form.numLevels}
                    onChange={e => onChange({ numLevels: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
                <div>
                  <Label>Per level</Label>
                  <input type="number" value={form.gridInvestPerLevel}
                    onChange={e => onChange({ gridInvestPerLevel: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
              </div>
            </div>
          )}

          {/* Classic DCA params */}
          {form.strategy === 'DCA' && (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Interval (h)</Label>
                  <input type="number" value={form.buyIntervalHours}
                    onChange={e => onChange({ buyIntervalHours: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
                <div>
                  <Label>Per buy</Label>
                  <input type="number" value={form.dcaInvestPerBuy}
                    onChange={e => onChange({ dcaInvestPerBuy: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
              </div>
            </div>
          )}

          {/* Classic PLA params */}
          {form.strategy === 'PLA' && (
            <div className="mt-2 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Fast EMA</Label>
                  <input type="number" value={form.fastEma}
                    onChange={e => onChange({ fastEma: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
                <div>
                  <Label>Slow EMA</Label>
                  <input type="number" value={form.slowEma}
                    onChange={e => onChange({ slowEma: +e.target.value })}
                    className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none" />
                </div>
              </div>
            </div>
          )}

          {/* Schema-driven form for indicator presets */}
          {!isClassic && form.strategy !== 'CUSTOM' && selectedStrategy?.schema && (
            <div className="mt-2">
              <StrategyParamsForm
                schema={selectedStrategy.schema}
                value={form.strategyParams}
                onChange={sp => onChange({ strategyParams: sp })}
              />
            </div>
          )}

          {/* Rule builder for CUSTOM */}
          {form.strategy === 'CUSTOM' && (
            <div className="mt-2">
              <RuleBuilder
                value={form.strategyParams}
                onChange={sp => onChange({ strategyParams: sp })}
              />
            </div>
          )}
        </Section>

        {/* ── Forecast settings ────────────────────────────────────────── */}
        <Section title="Forecast Horizon">
          <PillGroup
            options={HORIZON_PRESETS}
            value={form.horizonDays}
            onChange={v => onChange({ horizonDays: v as number })}
          />
        </Section>

        <Section title="Synthetic Paths">
          <PillGroup
            options={NPATHS_PRESETS}
            value={form.nPaths}
            onChange={v => onChange({ nPaths: v as number })}
          />
          <p className="text-[10px] text-gray-400 mt-1.5">
            More paths = more stable distribution. 100 is fast; 500 takes ~30s.
          </p>
        </Section>

        {/* ── UC-2 Crisis Mode ─────────────────────────────────────────── */}
        <Section title="Simulation Mode">
          <div className="flex rounded-xl overflow-hidden border border-gray-200 text-xs font-semibold mb-2">
            <button onClick={() => onCrisisModeChange(false)}
              className={`flex-1 py-1.5 transition-all ${!crisisMode ? 'bg-[var(--tv-accent)] text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              Forward Test
            </button>
            <button onClick={() => onCrisisModeChange(true)}
              className={`flex-1 py-1.5 transition-all ${crisisMode ? 'bg-orange-500 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              Crisis Sim
            </button>
          </div>
          {crisisMode && (
            <div className="space-y-2">
              <div>
                <Label>Stress Scenario</Label>
                <select value={crisisScenario} onChange={e => onCrisisScenarioChange(e.target.value)}
                  className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-orange-300">
                  {CRISIS_SCENARIOS.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label>Severity (0.5× – 3×)</Label>
                <div className="flex items-center gap-2">
                  <input type="range" min="0.5" max="3" step="0.25" value={severity}
                    onChange={e => onSeverityChange(+e.target.value)}
                    className="flex-1 accent-orange-500" />
                  <span className="text-xs font-bold text-orange-600 w-8 text-right">{severity}×</span>
                </div>
              </div>
              <p className="text-[10px] text-orange-500 bg-orange-50 rounded-lg px-2 py-1.5">
                Crisis mode overlays a macro stress scaffold on each Kronos/bootstrap path
                (UC-2 hybrid — realistic micro-structure + deterministic shock shape).
              </p>
            </div>
          )}
        </Section>

        {/* ── Run button ───────────────────────────────────────────────── */}
        <button onClick={onRun} disabled={loading}
          className={`w-full py-3 rounded-2xl font-bold text-sm mt-2 transition-all ${
            loading
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : 'text-white shadow-md hover:shadow-lg hover:-translate-y-0.5 active:translate-y-0'
          }`}
          style={loading ? {} : { background: crisisMode ? '#f97316' : 'var(--tv-accent)' }}>
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <div className="w-4 h-4 border-2 border-gray-300 border-t-gray-500 rounded-full animate-spin" />
              {crisisMode ? 'Simulating crisis…' : 'Generating paths…'}
            </span>
          ) : crisisMode
            ? `Run Crisis Sim  (${form.nPaths} paths × ${form.horizonDays}d)`
            : `Run Forward Test  (${form.nPaths} paths × ${form.horizonDays}d)`
          }
        </button>

        {/* Info note */}
        <p className="text-[10px] text-center text-gray-300 mt-3">
          {crisisMode
            ? 'Kronos paths + stress scaffold overlay · UC-2 hybrid mode'
            : 'Paths: circular block bootstrap · Kronos GPU when KRONOS_URL is set'}
        </p>

      </div>
    </aside>
  );
}
