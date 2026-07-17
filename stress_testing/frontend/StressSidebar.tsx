import React, { useState, useEffect } from 'react';
import { StressFormState, StressScenarioKey, Strategy, DataSource, Interval, StrategyMeta, CLASSIC_STRATEGIES } from '@app/types';
import { fetchStrategies } from '@app/api';
import StrategyParamsForm, { defaultsFromSchema } from '@app/components/shared/StrategyParamsForm';
import RuleBuilder, { defaultCustomParams } from '@app/components/shared/RuleBuilder';

const STRESS_CLASSIC_SET = new Set<string>(CLASSIC_STRATEGIES);

// ── Scenario metadata ─────────────────────────────────────────────────────────

const SCENARIO_GROUPS: { label: string; keys: StressScenarioKey[] }[] = [
  { label: 'Historical',            keys: ['gfc_2008', 'covid_crash', 'flash_crash_2010', 'luna_collapse'] },
  { label: 'Flashy / Manipulation', keys: ['pump_dump', 'gap_risk', 'liquidity_drought'] },
  { label: 'Realistic',             keys: ['slow_bleed', 'vol_spike', 'whipsaw_chop', 'range_bound', 'trend_reversal'] },
  { label: 'Indian Market',         keys: ['demonetization_2016', 'covid_nifty_mar2020', 'yes_bank_2020', 'expiry_gamma_squeeze'] },
  { label: 'Modifier',              keys: ['outlier_injection'] },
];

const SCENARIO_DISPLAY: Record<StressScenarioKey, string> = {
  gfc_2008:              '2008 GFC Replay',
  covid_crash:           '2020 COVID Flash Crash',
  flash_crash_2010:      '2010 Flash Crash',
  luna_collapse:         'LUNA-style Collapse',
  liquidity_drought:     'Liquidity Drought',
  pump_dump:             'Pump & Dump',
  whipsaw_chop:          'Whipsaw Chop',
  slow_bleed:            'Slow Bleed Bear',
  vol_spike:             'Vol Spike (VIX-style)',
  gap_risk:              'Gap Risk',
  range_bound:           'Range-bound Consolidation',
  trend_reversal:        'Trend Exhaustion + Reversal',
  outlier_injection:     '20–30% Outlier Injection',
  demonetization_2016:   'India Demonetization 2016',
  covid_nifty_mar2020:   'COVID NIFTY Crash Mar 2020',
  yes_bank_2020:         'Yes Bank Collapse 2020',
  expiry_gamma_squeeze:  'F&O Expiry Gamma Squeeze',
};

/** Scenario default overrides — kept in sync with engine/stress.py SCENARIO_PRESETS */
const SCENARIO_DEFAULTS: Record<StressScenarioKey, { shock_depth_pct: number; shock_duration_days: number; vol_multiplier: number }> = {
  gfc_2008:             { shock_depth_pct: 37,  shock_duration_days: 252, vol_multiplier: 1.5 },
  covid_crash:          { shock_depth_pct: 34,  shock_duration_days: 30,  vol_multiplier: 2.5 },
  flash_crash_2010:     { shock_depth_pct: 9,   shock_duration_days: 1,   vol_multiplier: 3.0 },
  luna_collapse:        { shock_depth_pct: 95,  shock_duration_days: 7,   vol_multiplier: 4.0 },
  liquidity_drought:    { shock_depth_pct: 0,   shock_duration_days: 10,  vol_multiplier: 1.2 },
  pump_dump:            { shock_depth_pct: 60,  shock_duration_days: 3,   vol_multiplier: 2.0 },
  whipsaw_chop:         { shock_depth_pct: 5,   shock_duration_days: 60,  vol_multiplier: 2.5 },
  slow_bleed:           { shock_depth_pct: 40,  shock_duration_days: 180, vol_multiplier: 1.0 },
  vol_spike:            { shock_depth_pct: 0,   shock_duration_days: 30,  vol_multiplier: 3.0 },
  gap_risk:             { shock_depth_pct: 0,   shock_duration_days: 0,   vol_multiplier: 1.0 },
  range_bound:          { shock_depth_pct: 2,   shock_duration_days: 90,  vol_multiplier: 1.0 },
  trend_reversal:       { shock_depth_pct: 25,  shock_duration_days: 20,  vol_multiplier: 1.5 },
  outlier_injection:    { shock_depth_pct: 0,   shock_duration_days: 0,   vol_multiplier: 1.0 },
  demonetization_2016:  { shock_depth_pct: 15,  shock_duration_days: 30,  vol_multiplier: 2.0 },
  covid_nifty_mar2020:  { shock_depth_pct: 38,  shock_duration_days: 40,  vol_multiplier: 3.5 },
  yes_bank_2020:        { shock_depth_pct: 85,  shock_duration_days: 120, vol_multiplier: 3.0 },
  expiry_gamma_squeeze: { shock_depth_pct: 0,   shock_duration_days: 0,   vol_multiplier: 4.0 },
};

// ── Symbol options per source (mirrors Sidebar.tsx) ───────────────────────────

const SYMBOL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  binance: [
    { value: 'BTC/USDT',   label: 'BTC/USDT — Bitcoin'    },
    { value: 'ETH/USDT',   label: 'ETH/USDT — Ethereum'   },
    { value: 'BNB/USDT',   label: 'BNB/USDT — BNB'        },
    { value: 'SOL/USDT',   label: 'SOL/USDT — Solana'     },
    { value: 'XRP/USDT',   label: 'XRP/USDT — Ripple'     },
    { value: 'ADA/USDT',   label: 'ADA/USDT — Cardano'    },
    { value: 'DOGE/USDT',  label: 'DOGE/USDT — Dogecoin'  },
    { value: 'AVAX/USDT',  label: 'AVAX/USDT — Avalanche' },
    { value: 'MATIC/USDT', label: 'MATIC/USDT — Polygon'  },
    { value: 'LINK/USDT',  label: 'LINK/USDT — Chainlink' },
    { value: '__custom__', label: '✏️ Custom…'              },
  ],
  yfinance: [
    { value: 'AAPL',  label: 'AAPL — Apple'        },
    { value: 'MSFT',  label: 'MSFT — Microsoft'    },
    { value: 'NVDA',  label: 'NVDA — NVIDIA'       },
    { value: 'GOOGL', label: 'GOOGL — Alphabet'    },
    { value: 'AMZN',  label: 'AMZN — Amazon'       },
    { value: 'META',  label: 'META — Meta'         },
    { value: 'TSLA',  label: 'TSLA — Tesla'        },
    { value: 'SPY',   label: 'SPY — S&P 500 ETF'  },
    { value: 'QQQ',   label: 'QQQ — Nasdaq 100 ETF'},
    { value: 'GLD',   label: 'GLD — Gold ETF'      },
    { value: '__custom__', label: '✏️ Custom…'      },
  ],
  nse: [
    { value: 'NIFTY50',    label: 'NIFTY50 — Index'         },
    { value: 'BANKNIFTY',  label: 'BANKNIFTY — Bank Index'  },
    { value: 'FINNIFTY',   label: 'FINNIFTY — Fin Index'    },
    { value: 'RELIANCE',   label: 'RELIANCE'                },
    { value: 'TCS',        label: 'TCS'                     },
    { value: 'HDFCBANK',   label: 'HDFCBANK'                },
    { value: 'INFY',       label: 'INFY — Infosys'          },
    { value: 'SBIN',       label: 'SBIN — SBI'              },
    { value: 'ICICIBANK',  label: 'ICICIBANK'               },
    { value: 'BAJFINANCE', label: 'BAJFINANCE'              },
    { value: 'TATAMOTORS', label: 'TATAMOTORS'              },
    { value: 'WIPRO',      label: 'WIPRO'                   },
    { value: 'HCLTECH',    label: 'HCLTECH'                 },
    { value: 'AXISBANK',   label: 'AXISBANK'                },
    { value: 'KOTAKBANK',  label: 'KOTAKBANK'               },
    { value: '__custom__', label: '✏️ Custom…'               },
  ],
  bse: [
    { value: 'SENSEX',     label: 'SENSEX — Index'   },
    { value: 'RELIANCE',   label: 'RELIANCE'          },
    { value: 'TCS',        label: 'TCS'               },
    { value: 'HDFCBANK',   label: 'HDFCBANK'          },
    { value: 'INFY',       label: 'INFY — Infosys'    },
    { value: 'SBIN',       label: 'SBIN — SBI'        },
    { value: '__custom__', label: '✏️ Custom…'         },
  ],
};

// ── Approximate prices for smart fill ────────────────────────────────────────

// Must stay in sync with data/indian_assets.py:FO_LOT_SIZES (backend source of truth)
const FO_LOT_SIZES: Record<string, number> = {
  NIFTY50: 50, BANKNIFTY: 15, FINNIFTY: 40, SENSEX: 10,
  RELIANCE: 250, HDFCBANK: 550, TCS: 150, INFY: 300,
  SBIN: 1500, BAJFINANCE: 125, TATAMOTORS: 2400, ICICIBANK: 700,
  KOTAKBANK: 400, AXISBANK: 1200, LT: 300, SUNPHARMA: 700,
  WIPRO: 2800, TITAN: 375, MARUTI: 75, BHARTIARTL: 1000,
};

const APPROX_PRICES: Record<string, number> = {
  NIFTY50: 24000, BANKNIFTY: 52000, FINNIFTY: 24000, SENSEX: 80000,
  RELIANCE: 1300, HDFCBANK: 1700, TCS: 3500, INFY: 1600,
  SBIN: 800, BAJFINANCE: 7000, TATAMOTORS: 700, ICICIBANK: 1300,
  KOTAKBANK: 1800, AXISBANK: 1100, LT: 3500, SUNPHARMA: 1700,
  WIPRO: 270, TITAN: 3300, MARUTI: 12000, BHARTIARTL: 1600,
  'BTC/USDT': 65000, 'ETH/USDT': 3500, 'BNB/USDT': 600, 'SOL/USDT': 170,
  'XRP/USDT': 0.60, 'ADA/USDT': 0.50, 'DOGE/USDT': 0.15, 'AVAX/USDT': 40,
  'MATIC/USDT': 0.90, 'LINK/USDT': 18,
  AAPL: 185, MSFT: 380, NVDA: 870, GOOGL: 175,
  AMZN: 195, META: 495, TSLA: 200, SPY: 520, QQQ: 445, GLD: 195,
};

function computeSmartDefaults(form: StressFormState): { updates: Partial<StressFormState>; hint: string } {
  const { symbol, source, marketType, scenarioKey } = form;
  const isIndian  = source === 'nse' || source === 'bse';
  const isCrypto  = source === 'binance';
  const isFutures = marketType === 'futures' || marketType === 'options';

  const lotSize  = FO_LOT_SIZES[symbol] ?? 1;
  const price    = APPROX_PRICES[symbol] ?? (isCrypto ? 100 : 1000);
  const hasFOLot = lotSize > 1;

  const roundLakh = (n: number) => Math.ceil(n / 100_000) * 100_000;
  const round10k  = (n: number) => Math.ceil(n / 10_000) * 10_000;

  // Scenario advanced defaults
  const scDef = SCENARIO_DEFAULTS[scenarioKey];

  let stratUpdates: Partial<StressFormState> = {};
  let hint = '';

  if (isIndian) {
    if (hasFOLot && isFutures) {
      const minLotCost = lotSize * price;
      const investBuy  = round10k(minLotCost * 1.10);
      const capital    = roundLakh(investBuy * 5);
      const plaBase    = round10k(investBuy * 0.35);
      const glo = Math.floor(price * 0.90 / 500) * 500;
      const ghi = Math.ceil(price * 1.10 / 500) * 500;
      hint = `${symbol} futures: lot ${lotSize} × ≈₹${Math.round(price).toLocaleString('en-IN')} → ₹${investBuy.toLocaleString('en-IN')}/order · ₹${capital.toLocaleString('en-IN')} capital · 15m synthetic`;
      stratUpdates = {
        capital, dcaInvestPerBuy: investBuy, buyIntervalHours: 24, holdDays: 7,
        dcaExitType: 'profit', profitTargetPct: 5,
        gridInvestPerLevel: investBuy, numLevels: 5, gridSpacing: 'linear',
        lowerBound: glo, upperBound: ghi,
        plaInvestPerLevel: plaBase, fastEma: 9, slowEma: 21,
        plaExitType: 'take_profit', takeProfitPct: 5,
        plaLvl2Pct: -1, plaLvl3Pct: -2.5, plaLvl4Pct: -4,
        interval: '15m', syntheticIntraday: true, feePct: 0.1, slippagePct: 0.05,
      };
    } else {
      const rawInvest = Math.max(10_000, price * 15);
      const investBuy = Math.min(round10k(rawInvest), 100_000);
      const capital   = Math.min(roundLakh(investBuy * 20), 2_000_000);
      const plaBase   = round10k(investBuy * 0.6);
      const glo = Math.floor(price * 0.90 / 500) * 500;
      const ghi = Math.ceil(price * 1.10 / 500) * 500;
      hint = `${symbol} equity: ≈₹${Math.round(price).toLocaleString('en-IN')}/share → ₹${investBuy.toLocaleString('en-IN')}/order · ₹${capital.toLocaleString('en-IN')} capital · 15m synthetic`;
      stratUpdates = {
        marketType: 'equity_delivery', capital, lowerBound: glo, upperBound: ghi,
        dcaInvestPerBuy: investBuy, buyIntervalHours: 24, holdDays: 30,
        dcaExitType: 'time', profitTargetPct: 8,
        gridInvestPerLevel: round10k(investBuy * 2), numLevels: 5, gridSpacing: 'linear',
        plaInvestPerLevel: plaBase, fastEma: 12, slowEma: 26,
        plaExitType: 'take_profit', takeProfitPct: 8,
        plaLvl2Pct: -1, plaLvl3Pct: -2.5, plaLvl4Pct: -4,
        interval: '15m', syntheticIntraday: true, feePct: 0.1, slippagePct: 0.05,
      };
    }
  } else if (isCrypto) {
    const investBuy = price < 10 ? 50 : price < 1000 ? 100 : 200;
    const glo = Math.floor(price * 0.85 / 100) * 100 || Math.floor(price * 0.85);
    const ghi = Math.ceil(price * 1.15 / 100) * 100 || Math.ceil(price * 1.15);
    hint = `${symbol}: $${investBuy}/buy · $10,000 capital · grid $${glo.toLocaleString()}–$${ghi.toLocaleString()} · PLA 9/21 EMA, TP 10%`;
    stratUpdates = {
      capital: 10_000, lowerBound: glo, upperBound: ghi,
      dcaInvestPerBuy: investBuy, buyIntervalHours: 24, holdDays: 30,
      dcaExitType: 'profit', profitTargetPct: 10,
      gridInvestPerLevel: investBuy * 2.5, numLevels: 5, gridSpacing: 'linear',
      plaInvestPerLevel: investBuy * 1.5, fastEma: 9, slowEma: 21,
      plaExitType: 'take_profit', takeProfitPct: 10,
      plaLvl2Pct: -2, plaLvl3Pct: -5, plaLvl4Pct: -8,
      interval: '1d', feePct: 0.10, slippagePct: 0.05,
    };
  } else {
    const investBuy = Math.ceil(price * 3 / 50) * 50;
    const glo = Math.floor(price * 0.90 / 5) * 5;
    const ghi = Math.ceil(price * 1.10 / 5) * 5;
    hint = `${symbol} ~$${price}/share → $${investBuy}/order · $10,000 capital · grid $${glo}–$${ghi}`;
    stratUpdates = {
      capital: 10_000, lowerBound: glo, upperBound: ghi,
      dcaInvestPerBuy: investBuy, buyIntervalHours: 24 * 7, holdDays: 60,
      dcaExitType: 'time', profitTargetPct: 8,
      gridInvestPerLevel: investBuy * 2, numLevels: 5, gridSpacing: 'linear',
      plaInvestPerLevel: Math.ceil(investBuy * 0.6 / 50) * 50, fastEma: 12, slowEma: 26,
      plaExitType: 'crossover', takeProfitPct: 8,
      plaLvl2Pct: -1, plaLvl3Pct: -3, plaLvl4Pct: -5,
      interval: '1d', feePct: 0.05, slippagePct: 0.02,
    };
  }

  return {
    hint: `${hint} · Scenario: ${SCENARIO_DISPLAY[scenarioKey]} (depth ${scDef.shock_depth_pct}%, ${scDef.shock_duration_days}d, vol×${scDef.vol_multiplier})`,
    updates: {
      ...stratUpdates,
      shockDepthPct:     scDef.shock_depth_pct     || undefined,
      shockDurationDays: scDef.shock_duration_days  || undefined,
      volMultiplier:     scDef.vol_multiplier       !== 1.0 ? scDef.vol_multiplier : undefined,
    },
  };
}

// ── Default form state ────────────────────────────────────────────────────────

export const DEFAULT_STRESS_FORM: StressFormState = {
  symbol:       'BTC/USDT',
  customSymbol: '',
  source:       'binance',
  startDate:    '2023-01-01',
  endDate:      '2024-01-01',
  datePreset:   '1Y',
  interval:     '1d',
  capital:      10000,
  feePct:       0.1,
  slippagePct:  0.05,
  strategy:     'DCA',
  strategyParams:     {},
  lowerBound:         0,
  upperBound:         0,
  numLevels:          5,
  gridSpacing:        'linear',
  gridInvestPerLevel: 500,
  buyIntervalHours:   24,
  dcaInvestPerBuy:    200,
  holdDays:           30,
  dcaExitType:        'time',
  profitTargetPct:    10,
  fastEma:            9,
  slowEma:            21,
  plaExitType:        'take_profit',
  takeProfitPct:      10,
  stopLossPct:        5,
  plaLvl2Pct:         -2,
  plaLvl3Pct:         -5,
  plaLvl4Pct:         -8,
  plaInvestPerLevel:  300,
  marketType:         'equity_delivery',
  brokerageModel:     'flat',
  brokerageFlat:      20,
  brokeragePct:       0.05,
  scenarioKey:     'covid_crash',
  severity:        'moderate',
  outlierCount:    0,
  mcRuns:          100,
  tradeMcRuns:     0,
  tradeSkipPct:    0.10,
  runValidation:   false,
  wfWindow:        252,
  wfStep:          63,
  regimeAwareMC:      false,
  syntheticIntraday:  false,
};

// ── Shared input class (matches backtest sidebar style) ───────────────────────
const inp = 'w-full bg-white text-[var(--tv-text)] text-sm rounded-lg px-3 py-2 border border-gray-200 shadow-sm focus:outline-none focus:border-[var(--tv-accent)]';
const lbl = 'block text-xs font-medium text-[var(--tv-muted)] mb-1';

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  form:     StressFormState;
  onChange: (updates: Partial<StressFormState>) => void;
  onRun:    () => void;
  loading:  boolean;
}

export default function StressSidebar({ form, onChange, onRun, loading }: Props) {
  const [advancedOpen, setAdvancedOpen]     = useState(false);
  const [outlierEnabled, setOutlierEnabled] = useState(false);
  const [smartHint, setSmartHint]           = useState('');

  const indian   = form.source === 'nse' || form.source === 'bse';
  const currency = indian ? '₹' : '$';
  const isFutures = form.marketType === 'futures' || form.marketType === 'options';

  const set = (updates: Partial<StressFormState>) => onChange(updates);

  const [strategies, setStrategies] = useState<StrategyMeta[]>([]);
  useEffect(() => { fetchStrategies().then(setStrategies).catch(() => {}); }, []);
  const selectedMeta = strategies.find(s => s.name === form.strategy);

  const handleStrategyChange = (name: string) => {
    if (STRESS_CLASSIC_SET.has(name)) { set({ strategy: name }); return; }
    const meta = strategies.find(s => s.name === name);
    const seed = name === 'CUSTOM' ? defaultCustomParams() : (meta ? defaultsFromSchema(meta.schema) : {});
    set({ strategy: name, strategyParams: seed });
  };

  const handleOutlierToggle = (enabled: boolean) => {
    setOutlierEnabled(enabled);
    set({ outlierCount: enabled ? 5 : 0 });
  };

  const handleSourceChange = (src: DataSource) => {
    const first = SYMBOL_OPTIONS[src]?.[0]?.value ?? 'BTC/USDT';
    // Build a temp form with the new source/symbol so computeSmartDefaults picks correct amounts
    const tempForm: StressFormState = {
      ...form, source: src, symbol: first, customSymbol: '', marketType: 'equity_delivery',
    };
    const { updates, hint } = computeSmartDefaults(tempForm);
    setSmartHint(hint);
    onChange({ ...updates, source: src, symbol: first, customSymbol: '', marketType: 'equity_delivery', mcRuns: Math.max(form.mcRuns, 100) });
  };

  const handleSmartFill = () => {
    const { updates, hint } = computeSmartDefaults(form);
    onChange({ ...updates, mcRuns: Math.max(form.mcRuns, 100) });
    setSmartHint(hint);
    if (updates.shockDepthPct != null || updates.shockDurationDays != null || updates.volMultiplier != null) {
      setAdvancedOpen(true);
    }
  };

  const datePresets = [
    { label: '1M', months: 1 },  { label: '3M', months: 3 },
    { label: '6M', months: 6 },  { label: '1Y', months: 12 },
  ] as const;

  const currentSymbols = SYMBOL_OPTIONS[form.source] ?? SYMBOL_OPTIONS['binance'];

  return (
    <div className="w-72 min-w-[17rem] bg-[var(--tv-s1)] border-r border-gray-100 flex flex-col overflow-y-auto shadow-sm">
      <div className="p-4 space-y-5">

        {/* ── Dataset ──────────────────────────────────────────────────── */}
        <section>
          <p className="text-xs font-bold uppercase tracking-widest text-[var(--tv-muted)] mb-3">Dataset</p>

          <label className={lbl}>Source</label>
          <select
            data-testid="source-select"
            value={form.source}
            onChange={e => handleSourceChange(e.target.value as DataSource)}
            className={`${inp} mb-2`}
          >
            <option value="binance">Binance (Crypto)</option>
            <option value="yfinance">Yahoo Finance (US)</option>
            <option value="nse">NSE (India)</option>
            <option value="bse">BSE (India)</option>
          </select>

          <label className={lbl}>Symbol</label>
          <select
            value={form.symbol}
            onChange={e => { setSmartHint(''); set({ symbol: e.target.value, customSymbol: '' }); }}
            className={`${inp} mb-2`}
          >
            {currentSymbols.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {form.symbol === '__custom__' && (
            <input
              type="text"
              placeholder="e.g. HDFCBANK or ETH/BTC"
              className={`${inp} mb-2`}
              value={form.customSymbol}
              onChange={e => set({ customSymbol: e.target.value.toUpperCase() })}
            />
          )}

          <label className={lbl}>Interval</label>
          <select value={form.interval} onChange={e => set({ interval: e.target.value as Interval })} className={`${inp} mb-1`}>
            {(['15m','1h','4h','1d','1w'] as Interval[]).map(i => <option key={i} value={i}>{i}</option>)}
          </select>
          {(form.source === 'nse' || form.source === 'bse') && ['15m','1h','4h'].includes(form.interval) && (
            <div className="mb-2 rounded-lg border border-blue-100 bg-blue-50 px-2 py-1.5">
              <div className="flex items-center justify-between mb-0.5">
                <p className="text-[10px] text-blue-700 font-medium">
                  {form.syntheticIntraday
                    ? 'Synthetic 15m — unlimited history, from daily OHLCV'
                    : 'Real 15m via TradingView — free, ~10 months'}
                </p>
                <button
                  type="button"
                  onClick={() => set({ syntheticIntraday: !form.syntheticIntraday })}
                  className={`relative w-8 h-4 rounded-full transition-colors flex-shrink-0 ml-2 ${form.syntheticIntraday ? 'bg-blue-500' : 'bg-gray-300'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${form.syntheticIntraday ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </div>
              <p className="text-[10px] text-blue-500">
                {form.syntheticIntraday
                  ? 'Brownian Bridge disaggregation of daily data. Statistically consistent; ideal for multi-year backtests.'
                  : 'Toggle on for 2–10 year backtests. Generates realistic intraday paths from daily OHLCV.'}
              </p>
            </div>
          )}

          {/* Date presets */}
          <label className={lbl}>Date Range</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {datePresets.map(({ label, months }) => {
              const isActive = form.datePreset === label;
              return (
                <button
                  key={label}
                  type="button"
                  onClick={() => {
                    const end   = new Date();
                    const start = new Date(end);
                    start.setMonth(start.getMonth() - months);
                    const fmt = (d: Date) => d.toISOString().split('T')[0];
                    set({ startDate: fmt(start), endDate: fmt(end), datePreset: label });
                  }}
                  className="px-2 py-0.5 rounded-full text-[11px] font-semibold transition-all"
                  style={{
                    background: isActive ? 'var(--tv-accent)' : '#f3f4f6',
                    color:      isActive ? '#fff' : '#6b7280',
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <div className="flex gap-2">
            <div className="flex-1">
              <label className={lbl}>Start</label>
              <input type="date" value={form.startDate}
                onChange={e => set({ startDate: e.target.value, datePreset: '' })}
                className={inp} />
            </div>
            <div className="flex-1">
              <label className={lbl}>End</label>
              <input type="date" value={form.endDate}
                onChange={e => set({ endDate: e.target.value, datePreset: '' })}
                className={inp} />
            </div>
          </div>
        </section>

        {/* ── Capital ──────────────────────────────────────────────────── */}
        <section>
          <label className={lbl}>Capital ({currency})</label>
          <input type="number" value={form.capital} min={100}
            onChange={e => set({ capital: +e.target.value })} className={inp} />
        </section>

        {/* ── Indian Market Config ──────────────────────────────────────── */}
        {indian && (
          <section className="p-3 rounded-xl" style={{ background: 'var(--tv-pastel-blue)' }}>
            <p className="text-xs font-bold uppercase tracking-widest text-[var(--tv-muted)] mb-2">Indian Markets</p>
            <label className={lbl}>Market Type</label>
            <select value={form.marketType}
              onChange={e => set({ marketType: e.target.value as any })} className={`${inp} mb-2`}>
              <option value="equity_delivery">Equity Delivery</option>
              <option value="equity_intraday">Equity Intraday</option>
              <option value="futures">F&O Futures</option>
              <option value="options">F&O Options</option>
            </select>
            <label className={lbl}>Brokerage</label>
            <select value={form.brokerageModel}
              onChange={e => set({ brokerageModel: e.target.value as any })} className={inp}>
              <option value="flat">Flat (₹20)</option>
              <option value="percentage">Percentage</option>
              <option value="zero">Zero</option>
            </select>
          </section>
        )}

        {/* ── Strategy ─────────────────────────────────────────────────── */}
        <section>
          <p className="text-xs font-bold uppercase tracking-widest text-[var(--tv-muted)] mb-3">Strategy</p>
          <select value={form.strategy} onChange={e => handleStrategyChange(e.target.value)} className={`${inp} mb-3`}>
            {strategies.length === 0 ? (
              <>
                <option value="GRID">GRID</option>
                <option value="DCA">DCA</option>
                <option value="PLA">PLA</option>
              </>
            ) : (
              ['classic', 'indicator', 'custom'].map(cat => {
                const inCat = strategies.filter(s => s.category === cat);
                if (!inCat.length) return null;
                const label = cat === 'classic' ? 'Classic' : cat === 'indicator' ? 'Indicator' : 'Custom';
                return (
                  <optgroup key={cat} label={label}>
                    {inCat.map(s => <option key={s.name} value={s.name}>{s.description || s.name}</option>)}
                  </optgroup>
                );
              })
            )}
          </select>

          {/* Schema-driven params for non-classic strategies */}
          {form.strategy === 'CUSTOM' && (
            <RuleBuilder value={form.strategyParams} onChange={next => set({ strategyParams: next })} />
          )}
          {!STRESS_CLASSIC_SET.has(form.strategy) && form.strategy !== 'CUSTOM' && selectedMeta && (
            <StrategyParamsForm schema={selectedMeta.schema} value={form.strategyParams}
                                onChange={next => set({ strategyParams: next })} />
          )}

          {form.strategy === 'DCA' && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className={lbl}>Invest/{currency}</label>
                  <input type="number" value={form.dcaInvestPerBuy} onChange={e => set({ dcaInvestPerBuy: +e.target.value })} className={inp} />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Interval (h)</label>
                  <input type="number" value={form.buyIntervalHours} onChange={e => set({ buyIntervalHours: +e.target.value })} className={inp} />
                </div>
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className={lbl}>Hold days</label>
                  <input type="number" value={form.holdDays} onChange={e => set({ holdDays: +e.target.value })} className={inp} />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Exit</label>
                  <select value={form.dcaExitType} onChange={e => set({ dcaExitType: e.target.value as 'time'|'profit' })} className={inp}>
                    <option value="time">Time</option>
                    <option value="profit">Profit %</option>
                  </select>
                </div>
              </div>
              {form.dcaExitType === 'profit' && (
                <div>
                  <label className={lbl}>Profit target %</label>
                  <input type="number" value={form.profitTargetPct} onChange={e => set({ profitTargetPct: +e.target.value })} className={inp} />
                </div>
              )}
            </div>
          )}

          {form.strategy === 'GRID' && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className={lbl}>Levels</label>
                  <input type="number" value={form.numLevels} onChange={e => set({ numLevels: +e.target.value })} className={inp} />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Invest/{currency}/lvl</label>
                  <input type="number" value={form.gridInvestPerLevel} onChange={e => set({ gridInvestPerLevel: +e.target.value })} className={inp} />
                </div>
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className={lbl}>Lower bound</label>
                  <input type="number" value={form.lowerBound} onChange={e => set({ lowerBound: +e.target.value })} className={inp} />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Upper bound</label>
                  <input type="number" value={form.upperBound} onChange={e => set({ upperBound: +e.target.value })} className={inp} />
                </div>
              </div>
            </div>
          )}

          {form.strategy === 'PLA' && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className={lbl}>Fast EMA</label>
                  <input type="number" value={form.fastEma} onChange={e => set({ fastEma: +e.target.value })} className={inp} />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Slow EMA</label>
                  <input type="number" value={form.slowEma} onChange={e => set({ slowEma: +e.target.value })} className={inp} />
                </div>
              </div>
              <div>
                <label className={lbl}>Invest/{currency} per level</label>
                <input type="number" value={form.plaInvestPerLevel} onChange={e => set({ plaInvestPerLevel: +e.target.value })} className={inp} />
              </div>
              <div>
                <label className={lbl}>Exit type</label>
                <select value={form.plaExitType} onChange={e => set({ plaExitType: e.target.value as any })} className={inp}>
                  <option value="crossover">EMA Crossover</option>
                  <option value="take_profit">Take Profit</option>
                  <option value="stop_loss">Stop Loss</option>
                </select>
              </div>
              {form.plaExitType === 'take_profit' && (
                <div>
                  <label className={lbl}>Take profit %</label>
                  <input type="number" value={form.takeProfitPct} onChange={e => set({ takeProfitPct: +e.target.value })} className={inp} />
                </div>
              )}
            </div>
          )}
        </section>

        {/* ── Stress Configuration ─────────────────────────────────────── */}
        <section>
          <p className="text-xs font-bold uppercase tracking-widest text-[var(--tv-muted)] mb-3">Stress Configuration</p>

          <label className={lbl}>Scenario</label>
          <select value={form.scenarioKey}
            onChange={e => {
              const key = e.target.value as StressScenarioKey;
              const def = SCENARIO_DEFAULTS[key];
              set({
                scenarioKey:       key,
                shockDepthPct:     def.shock_depth_pct     || undefined,
                shockDurationDays: def.shock_duration_days  || undefined,
                volMultiplier:     def.vol_multiplier !== 1.0 ? def.vol_multiplier : undefined,
              });
            }}
            className={`${inp} mb-3`}>
            {SCENARIO_GROUPS.map(group => (
              <optgroup key={group.label} label={group.label}>
                {group.keys.map(key => (
                  <option key={key} value={key}>{SCENARIO_DISPLAY[key]}</option>
                ))}
              </optgroup>
            ))}
          </select>

          <label className={lbl}>Severity</label>
          <div className="flex gap-1 mb-3 bg-gray-100 rounded-full p-1">
            {(['mild','moderate','severe'] as const).map(s => (
              <button key={s} onClick={() => set({ severity: s })}
                className={`flex-1 py-1.5 text-xs font-semibold rounded-full capitalize transition
                  ${form.severity === s
                    ? s === 'mild'   ? 'bg-yellow-400 text-yellow-900 shadow-sm'
                    : s === 'severe' ? 'bg-red-500 text-white shadow-sm'
                    :                  'bg-orange-500 text-white shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'}`}
              >{s}</button>
            ))}
          </div>

          {/* Advanced accordion */}
          <button onClick={() => setAdvancedOpen(o => !o)}
            className="w-full flex items-center justify-between text-xs font-medium text-[var(--tv-muted)] hover:text-[var(--tv-text)] mb-2 transition">
            <span>Advanced overrides</span>
            <span className="text-base leading-none">{advancedOpen ? '−' : '+'}</span>
          </button>
          {advancedOpen && (
            <div className="space-y-2 mb-3 pl-2 border-l-2 border-gray-200">
              <div>
                <label className={lbl}>Shock depth %</label>
                <input type="number" placeholder="default"
                  value={form.shockDepthPct ?? ''}
                  onChange={e => set({ shockDepthPct: e.target.value ? +e.target.value : undefined })}
                  className={inp} />
              </div>
              <div>
                <label className={lbl}>Shock duration (days)</label>
                <input type="number" placeholder="default"
                  value={form.shockDurationDays ?? ''}
                  onChange={e => set({ shockDurationDays: e.target.value ? +e.target.value : undefined })}
                  className={inp} />
              </div>
              <div>
                <label className={lbl}>Vol multiplier</label>
                <input type="number" step="0.1" placeholder="default"
                  value={form.volMultiplier ?? ''}
                  onChange={e => set({ volMultiplier: e.target.value ? +e.target.value : undefined })}
                  className={inp} />
              </div>
              {form.scenarioKey === 'liquidity_drought' && (
                <p className="text-xs text-[var(--tv-muted)] italic">5× slippage + 3× spread applied by default.</p>
              )}
            </div>
          )}

          {/* Outlier injection toggle */}
          <label className="flex items-center gap-2 cursor-pointer mb-2 text-sm text-[var(--tv-text)]">
            <input type="checkbox" checked={outlierEnabled} onChange={e => handleOutlierToggle(e.target.checked)} className="rounded" />
            Add 20–30% outlier shocks
          </label>
          {outlierEnabled && (
            <div className="mb-3 pl-2 border-l-2 border-gray-200">
              <label className={lbl}>Outlier count</label>
              <input type="number" min={1} max={20} value={form.outlierCount}
                onChange={e => set({ outlierCount: +e.target.value })} className={inp} />
            </div>
          )}
        </section>

        {/* ── Monte Carlo ──────────────────────────────────────────────── */}
        <section>
          <p className="text-xs font-bold uppercase tracking-widest text-[var(--tv-muted)] mb-3">Monte Carlo</p>
          <label className={lbl}>Monte Carlo Runs</label>
          <div className="flex gap-1 mb-2 bg-gray-100 rounded-full p-1">
            {[50, 100, 250, 500].map(n => (
              <button key={n} data-testid={n === 50 ? 'mc-runs-50' : n === 100 ? 'mc-runs-100' : undefined}
                onClick={() => set({ mcRuns: n })}
                className={`flex-1 py-1 text-xs font-semibold rounded-full transition
                  ${form.mcRuns === n
                    ? 'bg-white text-[var(--tv-accent)] shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'}`}
              >{n}</button>
            ))}
          </div>
          <input type="number" min={1} max={1000} value={form.mcRuns}
            onChange={e => set({ mcRuns: Math.min(1000, Math.max(1, +e.target.value)) })}
            className={`${inp} mb-1`} />
          {form.mcRuns > 250 && (
            <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-2 py-1.5 border border-amber-200">
              {form.mcRuns} runs may take {Math.round(form.mcRuns * 0.15)}–{Math.round(form.mcRuns * 0.4)} s.
            </p>
          )}
        </section>

        {/* ── Trade-level MC ───────────────────────────────────────────── */}
        <section>
          <label className={lbl}>Trade-level MC <span className="text-[10px] font-normal opacity-60">(reshuffle + skip)</span></label>
          <p className="text-[10px] text-[var(--tv-muted)] mb-2">
            Reshuffles your actual trades and skips a random fraction per run. 0 = disabled.
          </p>
          <div className="flex gap-1 mb-2 bg-gray-100 rounded-full p-1">
            {[0, 100, 200, 500].map(n => (
              <button key={n} data-testid={n === 100 ? 'trade-mc-100' : undefined}
                onClick={() => set({ tradeMcRuns: n })}
                className={`flex-1 py-1 text-xs font-semibold rounded-full transition
                  ${form.tradeMcRuns === n
                    ? 'bg-white text-purple-600 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'}`}
              >{n === 0 ? 'Off' : n}</button>
            ))}
          </div>
          {form.tradeMcRuns > 0 && (
            <div className="flex items-center gap-2 mt-1">
              <label className="text-[10px] text-[var(--tv-muted)] whitespace-nowrap">Skip %</label>
              <input type="range" min={0} max={50} step={5}
                value={Math.round(form.tradeSkipPct * 100)}
                onChange={e => set({ tradeSkipPct: +e.target.value / 100 })}
                className="flex-1" />
              <span className="text-[11px] font-bold text-purple-600 w-8 text-right">
                {Math.round(form.tradeSkipPct * 100)}%
              </span>
            </div>
          )}
        </section>

        {/* ── Walk-Forward Validation ─────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-1">
            <label className={lbl}>
              Walk-Forward Validation
              <span className="ml-1 text-[10px] font-normal opacity-60">unlocks Overfit Resistance score</span>
            </label>
            <button
              type="button"
              data-testid="wf-toggle"
              onClick={() => set({ runValidation: !form.runValidation })}
              className={`relative w-10 h-5 rounded-full transition-colors ${form.runValidation ? 'bg-[var(--tv-accent)]' : 'bg-gray-200'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${form.runValidation ? 'translate-x-5' : 'translate-x-0'}`} />
            </button>
          </div>
          {form.runValidation && (
            <div className="space-y-1.5 mt-2">
              <p className="text-[10px] text-[var(--tv-muted)] bg-indigo-50 rounded-lg px-2 py-1.5 border border-indigo-100">
                Runs walk-forward optimization to compute Walk-Forward Efficiency (OOS Sharpe / IS Sharpe) — upgrades the Robustness Score from provisional to full 4-axis. Values are in <strong>trading days</strong>; the backend auto-scales to candles for intraday intervals.
              </p>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-[10px] text-[var(--tv-muted)] block mb-0.5">Train window (trading days)</label>
                  <input type="number" min={60} max={504} value={form.wfWindow}
                    onChange={e => set({ wfWindow: Math.max(60, Math.min(504, +e.target.value)) })}
                    className={inp} />
                </div>
                <div className="flex-1">
                  <label className="text-[10px] text-[var(--tv-muted)] block mb-0.5">OOS step (trading days)</label>
                  <input type="number" min={20} max={126} value={form.wfStep}
                    onChange={e => set({ wfStep: Math.max(20, Math.min(126, +e.target.value)) })}
                    className={inp} />
                </div>
              </div>
            </div>
          )}
        </section>

        {/* ── Regime-aware MC ─────────────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-1">
            <label className={lbl}>
              Regime-aware MC
              <span className="ml-1 text-[10px] font-normal opacity-60">physically realistic path fanning</span>
            </label>
            <button
              type="button"
              data-testid="regime-aware-toggle"
              onClick={() => set({ regimeAwareMC: !form.regimeAwareMC })}
              className={`relative w-10 h-5 rounded-full transition-colors ${form.regimeAwareMC ? 'bg-[var(--tv-accent)]' : 'bg-gray-200'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${form.regimeAwareMC ? 'translate-x-5' : 'translate-x-0'}`} />
            </button>
          </div>
          {form.regimeAwareMC && (
            <p className="text-[10px] text-[var(--tv-muted)] bg-emerald-50 rounded-lg px-2 py-1.5 border border-emerald-100 mt-1">
              Classifies the dataset into bull / bear / sideways regimes and scales each MC run's shock intensity by the regime's realized volatility. Bear-regime runs fan wider; bull-regime runs cluster tighter — matching how real markets behave.
            </p>
          )}
        </section>

        {/* ── Smart Fill ──────────────────────────────────────────────── */}
        <button
          type="button"
          onMouseDown={e => { e.preventDefault(); handleSmartFill(); }}
          className="w-full py-2.5 rounded-full text-sm font-bold text-white shadow-sm
            bg-[var(--tv-accent)] opacity-90 hover:opacity-100 active:scale-95 transition-all
            flex items-center justify-center gap-2"
        >
          ⚡ Smart Fill Settings
        </button>
        {smartHint && (
          <div className="px-3 py-2 rounded-lg bg-green-50 border border-green-200 text-[10px] text-green-700 leading-relaxed">
            {smartHint}
          </div>
        )}

        {/* ── Run button ───────────────────────────────────────────────── */}
        <button data-testid="run-stress-button" onClick={onRun} disabled={loading}
          className="w-full py-3 rounded-full font-bold text-sm transition-all
            bg-[var(--tv-accent)] hover:opacity-90 text-white shadow-sm
            disabled:opacity-50 disabled:cursor-not-allowed">
          {loading ? 'Running…' : 'Run Stress Test'}
        </button>

      </div>
    </div>
  );
}
