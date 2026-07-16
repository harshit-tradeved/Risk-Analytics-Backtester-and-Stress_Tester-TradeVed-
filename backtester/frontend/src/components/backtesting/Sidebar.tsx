import { useState, useEffect } from 'react';
import { FormState, Strategy, DataSource, Interval, MarketType, BrokerageModel, StrategyMeta, CLASSIC_STRATEGIES } from '../../types';
import { fetchGridBounds, fetchIndianCostPreview, fetchStrategies } from '../../api';
import StrategyParamsForm, { defaultsFromSchema } from '../shared/StrategyParamsForm';
import RuleBuilder, { defaultCustomParams } from '../shared/RuleBuilder';

const CLASSIC_SET = new Set<string>(CLASSIC_STRATEGIES);

// Must stay in sync with data/indian_assets.py:FO_LOT_SIZES (backend source of truth)
const FO_LOT_SIZES: Record<string, number> = {
  NIFTY50:    50,   BANKNIFTY:  15,   FINNIFTY:   40,   SENSEX:     10,
  RELIANCE:   250,  HDFCBANK:   550,  TCS:        150,  INFY:       300,
  SBIN:       1500, BAJFINANCE: 125,  TATAMOTORS: 2400, ICICIBANK:  700,
  KOTAKBANK:  400,  AXISBANK:   1200, LT:         300,  SUNPHARMA:  700,
  WIPRO:      2800, TITAN:      375,  MARUTI:     75,   BHARTIARTL: 1000,
  ZOMATO:     4500, IRCTC:      875,  HAL:        175,  HCLTECH:    700,
};

const APPROX_PRICES: Record<string, number> = {
  NIFTY50:    24000, BANKNIFTY: 52000, FINNIFTY: 24000, SENSEX:     80000,
  RELIANCE:   1300,  HDFCBANK:  1700,  TCS:      3500,  INFY:       1600,
  SBIN:       800,   BAJFINANCE:7000,  TATAMOTORS:700,  ICICIBANK:  1300,
  KOTAKBANK:  1800,  AXISBANK:  1100,  LT:       3500,  SUNPHARMA:  1700,
  WIPRO:      270,   TITAN:     3300,  MARUTI:   12000, BHARTIARTL: 1600,
  ZOMATO:     240,   IRCTC:     850,   HAL:      4000,  HCLTECH:    1600,
};

// Approximate prices for crypto/US stocks used in smart fill
const APPROX_PRICES_EXTRA: Record<string, number> = {
  'BTC/USDT': 65000, 'ETH/USDT': 3500, 'BNB/USDT': 600,   'SOL/USDT': 170,
  'XRP/USDT': 0.60,  'ADA/USDT': 0.50, 'DOGE/USDT': 0.15, 'AVAX/USDT': 40,
  'MATIC/USDT': 0.90,'LINK/USDT': 18,
  'AAPL': 185,  'MSFT': 380,  'NVDA': 870,  'GOOGL': 175,
  'AMZN': 195,  'META': 495,  'TSLA': 200,  'SPY': 520,
  'QQQ': 445,   'GLD': 195,
};

function computeSmartDefaults(form: FormState): { updates: Partial<FormState>; hint: string } {
  const { symbol, source, marketType } = form;
  const isIndian   = source === 'nse' || source === 'bse';
  const isCrypto   = source === 'binance';
  const isFutures  = marketType === 'futures' || marketType === 'options';

  const lotSize    = FO_LOT_SIZES[symbol] ?? 1;
  const price      = APPROX_PRICES[symbol]
                  ?? APPROX_PRICES_EXTRA[symbol]
                  ?? (isCrypto ? 100 : 1000);
  const hasFOLot   = lotSize > 1;

  // ── Helpers ───────────────────────────────────────────────────────────────
  const roundLakh  = (n: number) => Math.ceil(n / 100_000) * 100_000;
  const round10k   = (n: number) => Math.ceil(n / 10_000)  * 10_000;

  // Grid bounds: ±10% around approximate price, rounded to nearest 500 (Indian) or 100 (crypto/US)
  const gridLowerIN = Math.floor(price * 0.90 / 500) * 500 || Math.floor(price * 0.90);
  const gridUpperIN = Math.ceil (price * 1.10 / 500) * 500 || Math.ceil (price * 1.10);

  if (isIndian) {
    if (hasFOLot && isFutures) {
      const minLotCost   = lotSize * price;
      const investPerBuy = round10k(minLotCost * 1.10);
      const capital      = roundLakh(investPerBuy * 5);
      const plaBase      = round10k(investPerBuy * 0.35);
      return {
        hint: `${symbol} futures: lot ${lotSize} × ≈₹${Math.round(price).toLocaleString('en-IN')} → ₹${investPerBuy.toLocaleString('en-IN')}/order · ₹${capital.toLocaleString('en-IN')} capital · grid ${gridLowerIN.toLocaleString('en-IN')}–${gridUpperIN.toLocaleString('en-IN')} · PLA 9/21 EMA, TP 5%`,
        updates: {
          capital,
          lowerBound:         gridLowerIN,
          upperBound:         gridUpperIN,
          // DCA params
          dcaInvestPerBuy:    investPerBuy,
          buyIntervalHours:   24,
          holdDays:           7,
          dcaExitType:        'profit',
          profitTargetPct:    5,
          // GRID params
          gridInvestPerLevel: investPerBuy,
          numLevels:          5,
          gridSpacing:        'linear',
          // PLA params
          plaInvestPerLevel:  plaBase,
          fastEma:            9,
          slowEma:            21,
          plaExitType:        'take_profit',
          takeProfitPct:      5,
          plaLvl2Pct:         -1,
          plaLvl3Pct:         -2.5,
          plaLvl4Pct:         -4,
          // General
          interval:           '1d',
          feePct:             0.1,
          slippagePct:        0.05,
        },
      };
    } else {
      const rawInvest  = Math.max(10_000, price * 15);
      const investBuy  = Math.min(round10k(rawInvest), 100_000);
      const capital    = Math.min(roundLakh(investBuy * 20), 2_000_000);
      const plaBase    = round10k(investBuy * 0.6);
      return {
        hint: `${symbol} equity: ≈₹${Math.round(price).toLocaleString('en-IN')}/share → ₹${investBuy.toLocaleString('en-IN')}/order · ₹${capital.toLocaleString('en-IN')} capital · grid ${gridLowerIN.toLocaleString('en-IN')}–${gridUpperIN.toLocaleString('en-IN')} · PLA 12/26 EMA, TP 8%`,
        updates: {
          marketType:         'equity_delivery',
          capital,
          lowerBound:         gridLowerIN,
          upperBound:         gridUpperIN,
          // DCA params
          dcaInvestPerBuy:    investBuy,
          buyIntervalHours:   24,
          holdDays:           30,
          dcaExitType:        'time',
          profitTargetPct:    8,
          // GRID params
          gridInvestPerLevel: round10k(investBuy * 2),
          numLevels:          5,
          gridSpacing:        'linear',
          // PLA params
          plaInvestPerLevel:  plaBase,
          fastEma:            12,
          slowEma:            26,
          plaExitType:        'take_profit',
          takeProfitPct:      8,
          plaLvl2Pct:         -1,
          plaLvl3Pct:         -2.5,
          plaLvl4Pct:         -4,
          // General
          interval:           '1d',
          feePct:             0.1,
          slippagePct:        0.05,
        },
      };
    }
  } else if (isCrypto) {
    const investBuy  = price < 10 ? 50 : price < 1000 ? 100 : 200;
    const gridLower  = Math.floor(price * 0.85 / 100) * 100 || Math.floor(price * 0.85);
    const gridUpper  = Math.ceil (price * 1.15 / 100) * 100 || Math.ceil (price * 1.15);
    return {
      hint: `${symbol}: $${investBuy}/buy · $10,000 capital · grid $${gridLower.toLocaleString()}–$${gridUpper.toLocaleString()} · PLA 9/21 EMA, TP 10%`,
      updates: {
        capital:            10_000,
        lowerBound:         gridLower,
        upperBound:         gridUpper,
        // DCA params
        dcaInvestPerBuy:    investBuy,
        buyIntervalHours:   24,
        holdDays:           30,
        dcaExitType:        'profit',
        profitTargetPct:    10,
        // GRID params
        gridInvestPerLevel: investBuy * 2.5,
        numLevels:          5,
        gridSpacing:        'linear',
        // PLA params
        plaInvestPerLevel:  investBuy * 1.5,
        fastEma:            9,
        slowEma:            21,
        plaExitType:        'take_profit',
        takeProfitPct:      10,
        plaLvl2Pct:         -2,
        plaLvl3Pct:         -5,
        plaLvl4Pct:         -8,
        // General
        interval:           '1d',
        feePct:             0.10,
        slippagePct:        0.05,
      },
    };
  } else {
    // US stocks
    const investBuy = Math.ceil(price * 3 / 50) * 50;
    const gridLower = Math.floor(price * 0.90 / 5) * 5;
    const gridUpper = Math.ceil (price * 1.10 / 5) * 5;
    return {
      hint: `${symbol} ~$${price}/share → $${investBuy}/order · $10,000 capital · grid $${gridLower}–$${gridUpper} · PLA 12/26 EMA crossover`,
      updates: {
        capital:            10_000,
        lowerBound:         gridLower,
        upperBound:         gridUpper,
        // DCA params
        dcaInvestPerBuy:    investBuy,
        buyIntervalHours:   24 * 7,
        holdDays:           60,
        dcaExitType:        'time',
        profitTargetPct:    8,
        // GRID params
        gridInvestPerLevel: investBuy * 2,
        numLevels:          5,
        gridSpacing:        'linear',
        // PLA params
        plaInvestPerLevel:  Math.ceil(investBuy * 0.6 / 50) * 50,
        fastEma:            12,
        slowEma:            26,
        plaExitType:        'crossover',
        takeProfitPct:      8,
        plaLvl2Pct:         -1,
        plaLvl3Pct:         -3,
        plaLvl4Pct:         -5,
        // General
        interval:           '1d',
        feePct:             0.05,
        slippagePct:        0.02,
      },
    };
  }
}

const SYMBOL_OPTIONS: Record<string, { value: string; label: string }[]> = {
  binance: [
    { value: 'BTC/USDT',  label: 'BTC/USDT — Bitcoin'     },
    { value: 'ETH/USDT',  label: 'ETH/USDT — Ethereum'    },
    { value: 'BNB/USDT',  label: 'BNB/USDT — BNB'         },
    { value: 'SOL/USDT',  label: 'SOL/USDT — Solana'      },
    { value: 'XRP/USDT',  label: 'XRP/USDT — Ripple'      },
    { value: 'ADA/USDT',  label: 'ADA/USDT — Cardano'     },
    { value: 'DOGE/USDT', label: 'DOGE/USDT — Dogecoin'   },
    { value: 'AVAX/USDT', label: 'AVAX/USDT — Avalanche'  },
    { value: 'MATIC/USDT',label: 'MATIC/USDT — Polygon'   },
    { value: 'LINK/USDT', label: 'LINK/USDT — Chainlink'  },
    { value: '__custom__', label: '✏️ Custom…'             },
  ],
  yfinance: [
    { value: 'AAPL',  label: 'AAPL — Apple'           },
    { value: 'MSFT',  label: 'MSFT — Microsoft'        },
    { value: 'NVDA',  label: 'NVDA — NVIDIA'           },
    { value: 'GOOGL', label: 'GOOGL — Alphabet'        },
    { value: 'AMZN',  label: 'AMZN — Amazon'           },
    { value: 'META',  label: 'META — Meta'              },
    { value: 'TSLA',  label: 'TSLA — Tesla'            },
    { value: 'SPY',   label: 'SPY — S&P 500 ETF'       },
    { value: 'QQQ',   label: 'QQQ — Nasdaq 100 ETF'    },
    { value: 'GLD',   label: 'GLD — Gold ETF'          },
    { value: '__custom__', label: '✏️ Custom…'         },
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
    { value: '__custom__', label: '✏️ Custom…'              },
  ],
  bse: [
    { value: 'SENSEX',   label: 'SENSEX — Index'   },
    { value: 'RELIANCE', label: 'RELIANCE'          },
    { value: 'TCS',      label: 'TCS'               },
    { value: 'HDFCBANK', label: 'HDFCBANK'          },
    { value: 'INFY',     label: 'INFY — Infosys'    },
    { value: 'SBIN',     label: 'SBIN — SBI'        },
    { value: '__custom__', label: '✏️ Custom…'      },
  ],
};

/** Rough estimate of trading candles in a date range for a given interval. */
function estimateCandles(startDate: string, endDate: string, interval: string): number {
  const calDays = Math.max(0, (new Date(endDate).getTime() - new Date(startDate).getTime()) / 86_400_000);
  const tradingDays = calDays * (5 / 7) * 0.97; // ~252/365 ≈ 0.69
  const perDay: Record<string, number> = { '15m': 25, '1h': 6, '4h': 1.6, '1d': 1, '1w': 0.2 };
  return Math.floor(tradingDays * (perDay[interval] ?? 1));
}

function inrCompact(n: number): string {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}k`;
  return `₹${n.toFixed(0)}`;
}

interface SidebarProps {
  form: FormState;
  onChange: (updates: Partial<FormState>) => void;
  onRun: () => void;
  loading: boolean;
}

export default function Sidebar({ form, onChange, onRun, loading }: SidebarProps) {
  const [detecting, setDetecting] = useState(false);
  const [autoInfo, setAutoInfo] = useState<any>(null);
  const [detectErr, setDetectErr] = useState('');
  const [smartHint, setSmartHint] = useState('');

  const [costPreview, setCostPreview] = useState<any>(null);
  const [costErr, setCostErr] = useState('');

  const [strategies, setStrategies] = useState<StrategyMeta[]>([]);
  useEffect(() => { fetchStrategies().then(setStrategies).catch(() => {}); }, []);

  const selectedMeta = strategies.find(s => s.name === form.strategy);

  /** Switch strategy; for non-classic strategies seed strategyParams from schema. */
  const handleStrategyChange = (name: string) => {
    if (CLASSIC_SET.has(name)) { onChange({ strategy: name }); return; }
    const meta = strategies.find(s => s.name === name);
    const seed = name === 'CUSTOM'
      ? defaultCustomParams()
      : (meta ? defaultsFromSchema(meta.schema) : {});
    onChange({ strategy: name, strategyParams: seed });
  };

  const handleAutoDetect = async () => {
    try {
      setDetecting(true);
      setDetectErr('');
      const data = await fetchGridBounds(
        form.symbol,
        form.source,
        form.interval,
        form.startDate,
        form.endDate
      );
      onChange({
        lowerBound: data.bounds.lower_bound,
        upperBound: data.bounds.upper_bound,
      });
      setAutoInfo({
        current: data.stats.current_price,
        low: data.stats.min_price,
        high: data.stats.max_price,
        pctChange: data.stats.pct_change
      });
    } catch (e: any) {
      setDetectErr(e.message);
    } finally {
      setDetecting(false);
    }
  };

  const isIndian = form.source === 'nse' || form.source === 'bse';

  const updateCostPreview = async () => {
    if (!isIndian) return;
    try {
      setCostErr('');
      const data = await fetchIndianCostPreview(
        form.marketType,
        form.brokerageModel,
        form.brokerageFlat,
        100_000
      );
      setCostPreview(data);
    } catch (e: any) {
      setCostErr(e.message);
    }
  };

  const InputRow = ({ label, value, type = 'text', field, min, max, step }: any) => (
    <div className="flex justify-between items-center mb-3">
      <label className="text-sm font-medium text-[var(--tv-text)]">{label}</label>
      <input
        type={type}
        min={min} max={max} step={step}
        className="w-24 px-3 py-1.5 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] text-right border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]"
        value={value}
        onChange={e => onChange({ [field]: type === 'number' ? Number(e.target.value) : e.target.value })}
      />
    </div>
  );

  const SelectRow = ({ label, value, field, options }: any) => (
    <div className="flex flex-col mb-3">
      <label className="text-sm font-medium text-[var(--tv-text)] mb-1">{label}</label>
      <select
        className="w-full px-3 py-2 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]"
        value={value}
        onChange={e => onChange({ [field]: e.target.value })}
      >
        {options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );

  return (
    <div className="w-full h-full overflow-y-auto bg-[var(--tv-s1)] p-5 flex flex-col hide-scrollbar shadow-sm z-10" style={{ color: 'var(--tv-text)' }}>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xl font-bold tracking-tight text-[var(--tv-accent)]">TradeVed</h2>
        <span className="text-xs bg-[var(--tv-s2)] px-2 py-0.5 rounded text-[var(--tv-muted)]">v1.0</span>
      </div>

      {/* Dataset Section */}
      <div className="mb-6 pb-4 border-b border-[var(--tv-border)]">
        <h3 className="text-xs font-semibold uppercase text-[var(--tv-muted)] mb-4">Dataset</h3>
        
        {/* Source — resets symbol to first option when switched */}
        <div className="flex flex-col mb-3">
          <label className="text-sm font-medium text-[var(--tv-text)] mb-1">Source</label>
          <select
            className="w-full px-3 py-2 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]"
            value={form.source}
            onChange={e => {
              const src = e.target.value as any;
              const first = SYMBOL_OPTIONS[src]?.[0]?.value ?? '';
              setSmartHint('');
              onChange({
                source:     src,
                symbol:     first,
                marketType: 'equity_delivery',
              });
            }}
          >
            {[
              {value: 'binance',  label: 'Binance'},
              {value: 'yfinance', label: 'Yahoo Finance'},
              {value: 'nse',       label: 'NSE (India)'},
              {value: 'bse',       label: 'BSE (India)'},
            ].map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        {/* Symbol picker */}
        <div className="flex flex-col mb-3">
          <label className="text-sm font-medium text-[var(--tv-text)] mb-1">Symbol</label>
          <select
            className="w-full px-3 py-2 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]"
            value={form.symbol}
            onChange={e => { setSmartHint(''); onChange({ symbol: e.target.value }); }}
          >
            {(SYMBOL_OPTIONS[form.source] ?? SYMBOL_OPTIONS['binance']).map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {form.symbol === '__custom__' && (
            <input
              type="text"
              placeholder="e.g. HDFCBANK or ETH/BTC"
              className="mt-2 w-full px-3 py-1.5 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] border border-[var(--tv-accent)] outline-none focus:ring-2 focus:ring-[var(--tv-accent)]"
              value={form.customSymbol}
              onChange={e => onChange({ customSymbol: e.target.value })}
            />
          )}
        </div>

        <SelectRow label="Interval" value={form.interval} field="interval" options={[
          {value: '15m', label: '15 Min'},
          {value: '1h', label: '1 Hour'},
          {value: '4h', label: '4 Hours'},
          {value: '1d', label: '1 Day'},
          {value: '1w', label: '1 Week'}
        ]} />

        {/* Date range presets */}
        <div className="mb-3">
          <label className="text-xs text-[var(--tv-muted)] block mb-1.5">Date Range</label>
          <div className="flex flex-wrap gap-1.5">
            {([
              { label: '1M', months: 1  },
              { label: '3M', months: 3  },
              { label: '6M', months: 6  },
              { label: '1Y', months: 12 },
            ] as const).map(({ label, months }) => {
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
                    onChange({ startDate: fmt(start), endDate: fmt(end), datePreset: label });
                  }}
                  className="px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all"
                  style={{
                    background:  isActive ? 'var(--tv-accent)' : 'var(--tv-s2)',
                    color:       isActive ? '#fff' : 'var(--tv-muted)',
                    fontWeight:  isActive ? 700 : 500,
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex gap-2 mb-3">
          <div className="flex-1">
            <label className="text-xs text-[var(--tv-muted)] block mb-1">Start Date</label>
            <input type="date" value={form.startDate}
              onChange={e => onChange({ startDate: e.target.value, datePreset: '' })}
              className="w-full bg-[var(--tv-s2)] rounded-lg px-2 py-1.5 text-xs border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]" />
          </div>
          <div className="flex-1">
            <label className="text-xs text-[var(--tv-muted)] block mb-1">End Date</label>
            <input type="date" value={form.endDate}
              onChange={e => onChange({ endDate: e.target.value, datePreset: '' })}
              className="w-full bg-[var(--tv-s2)] rounded-lg px-2 py-1.5 text-xs border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]" />
          </div>
        </div>
      </div>

      {/* Strategy Section */}
      <div className="mb-6 pb-4 border-b border-[var(--tv-border)]">
        <h3 className="text-xs font-semibold uppercase text-[var(--tv-muted)] mb-4">Strategy</h3>
        <div className="flex flex-col mb-3">
          <label className="text-sm font-medium text-[var(--tv-text)] mb-1">Algorithm</label>
          <select
            className="w-full px-3 py-2 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]"
            value={form.strategy}
            onChange={e => handleStrategyChange(e.target.value)}
          >
            {strategies.length === 0 ? (
              <>
                <option value="GRID">Grid Trading</option>
                <option value="DCA">DCA</option>
                <option value="PLA">Price Level Averaging (PLA)</option>
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
          {selectedMeta?.description && (
            <p className="text-[10px] text-[var(--tv-muted)] mt-1">{selectedMeta.description}</p>
          )}
        </div>

        {/* ── Schema-driven params for non-classic strategies ──────────────── */}
        {form.strategy === 'CUSTOM' && (
          <RuleBuilder
            value={form.strategyParams}
            onChange={next => onChange({ strategyParams: next })}
          />
        )}
        {!CLASSIC_SET.has(form.strategy) && form.strategy !== 'CUSTOM' && selectedMeta && (
          <StrategyParamsForm
            schema={selectedMeta.schema}
            value={form.strategyParams}
            onChange={next => onChange({ strategyParams: next })}
          />
        )}

        {form.strategy === 'GRID' && (
          <div className="pl-2 border-l-2 border-[var(--tv-border)] space-y-3 mt-4">
            <div className="flex justify-between items-center mb-2">
              <label className="text-sm font-medium">Auto-Detect Bounds</label>
              <button onClick={handleAutoDetect} disabled={detecting} className="px-2 py-1 bg-[var(--tv-accent)] text-white text-xs rounded hover:bg-[var(--tv-accent2)] transition-colors">
                {detecting ? 'Detecting...' : 'Auto-Fill'}
              </button>
            </div>
            {autoInfo && !detectErr && (
              <div className="text-[10px] text-[var(--tv-text)] mb-2 p-2 bg-[var(--tv-s2)] rounded">
                Current: <span className="font-bold text-[var(--tv-accent)]">${autoInfo.current?.toFixed(2)}</span> | Low: ${autoInfo.low?.toFixed(0)} | High: ${autoInfo.high?.toFixed(0)}
              </div>
            )}
            <InputRow label="Lower Bound" type="number" value={form.lowerBound} field="lowerBound" />
            <InputRow label="Upper Bound" type="number" value={form.upperBound} field="upperBound" />
            <InputRow label="Grid Levels" type="number" value={form.numLevels} field="numLevels" />
            <SelectRow label="Spacing" value={form.gridSpacing} field="gridSpacing" options={[
              {value: 'linear', label: 'Linear'},
              {value: 'exponential', label: 'Exponential'}
            ]} />
            <InputRow label="Invest per Level" type="number" value={form.gridInvestPerLevel} field="gridInvestPerLevel" />
          </div>
        )}

        {form.strategy === 'DCA' && (
          <div className="pl-2 border-l-2 border-[var(--tv-border)] space-y-3 mt-4">
            <InputRow label="Buy Interval (hrs)" type="number" value={form.buyIntervalHours} field="buyIntervalHours" />
            <InputRow label="Invest per Buy" type="number" value={form.dcaInvestPerBuy} field="dcaInvestPerBuy" />
            <InputRow label="Hold Days" type="number" value={form.holdDays} field="holdDays" />
            <SelectRow label="Exit Type" value={form.dcaExitType} field="dcaExitType" options={[
              {value: 'time', label: 'Time-based'},
              {value: 'profit', label: 'Profit Target'}
            ]} />
            {form.dcaExitType === 'profit' && (
              <InputRow label="Target Profit %" type="number" value={form.profitTargetPct} field="profitTargetPct" />
            )}
          </div>
        )}

        {form.strategy === 'PLA' && (
          <div className="pl-2 border-l-2 border-[var(--tv-border)] space-y-3 mt-4">
            <InputRow label="Fast EMA" type="number" value={form.fastEma} field="fastEma" />
            <InputRow label="Slow EMA" type="number" value={form.slowEma} field="slowEma" />
            <InputRow label="Invest Base (Lvl 1)" type="number" value={form.plaInvestPerLevel} field="plaInvestPerLevel" />
            <InputRow label="Lvl 2 Drop %" type="number" value={form.plaLvl2Pct} field="plaLvl2Pct" />
            <InputRow label="Lvl 3 Drop %" type="number" value={form.plaLvl3Pct} field="plaLvl3Pct" />
            <InputRow label="Lvl 4 Drop %" type="number" value={form.plaLvl4Pct} field="plaLvl4Pct" />
            <SelectRow label="Exit Type" value={form.plaExitType} field="plaExitType" options={[
              {value: 'crossover', label: 'EMA Crossover'},
              {value: 'take_profit', label: 'Take Profit'},
              {value: 'stop_loss', label: 'Stop Loss'}
            ]} />
            {form.plaExitType === 'take_profit' && (
              <InputRow label="Take Profit %" type="number" value={form.takeProfitPct} field="takeProfitPct" />
            )}
          </div>
        )}
      </div>

      {/* Capital & Fees */}
      <div className="mb-6 pb-4 border-b border-[var(--tv-border)]">
        <h3 className="text-xs font-semibold uppercase text-[var(--tv-muted)] mb-4">Capital & Costs</h3>
        <InputRow label="Capital" type="number" value={form.capital} field="capital" />
        <InputRow label="Fee %" type="number" value={form.feePct} field="feePct" step="0.01" />
        <InputRow label="Slippage %" type="number" value={form.slippagePct} field="slippagePct" step="0.01" />

        {isIndian && (
          <div className="mt-4 p-4 bg-[var(--tv-pastel-blue)] rounded-xl">
            <h4 className="text-xs font-semibold mb-2">Indian Markets Config</h4>
            <SelectRow label="Market Type" value={form.marketType} field="marketType" options={[
              {value: 'equity_delivery', label: 'Equity Delivery'},
              {value: 'equity_intraday', label: 'Equity Intraday'},
              {value: 'futures', label: 'F&O Futures'},
              {value: 'options', label: 'F&O Options'}
            ]} />
            <SelectRow label="Brokerage" value={form.brokerageModel} field="brokerageModel" options={[
              {value: 'flat', label: 'Flat (₹20)'},
              {value: 'percentage', label: 'Percentage'},
              {value: 'zero', label: 'Zero'}
            ]} />
            {form.brokerageModel === 'flat' && (
              <InputRow label="Flat Fee (₹)" type="number" value={form.brokerageFlat} field="brokerageFlat" />
            )}
            
            <button onClick={updateCostPreview} className="mt-2 text-xs text-[var(--tv-accent)] underline">
              Preview Costs (1L Turnover)
            </button>
            {costPreview && !costErr && (
              <div className="mt-2 text-[10px] text-[var(--tv-text)] bg-[var(--tv-bg)] p-2 rounded border border-[var(--tv-border)]">
                Total Fees: ₹{costPreview.total.toFixed(2)}<br/>
                (Brokerage: ₹{costPreview.brokerage.toFixed(2)}, STT: ₹{costPreview.stt.toFixed(2)})
              </div>
            )}
          </div>
        )}
      </div>

      {/* Validation */}
      <div className="mb-6 pb-4 border-b border-[var(--tv-border)]">
        <h3 className="text-xs font-semibold uppercase text-[var(--tv-muted)] mb-4">Validation</h3>
        <SelectRow label="Mode" value={form.validationMode} field="validationMode" options={[
          {value: 'none', label: 'None'},
          {value: 'holdout', label: 'Hold-out'},
          {value: 'walk_forward', label: 'Walk Forward'}
        ]} />
        {form.validationMode === 'holdout' && (
          <InputRow label="Train Ratio" type="number" value={form.trainRatio} field="trainRatio" step="0.1" />
        )}
        {form.validationMode === 'walk_forward' && (() => {
          const estCandles  = estimateCandles(form.startDate, form.endDate, form.interval);
          const needCandles = form.wfWindow + form.wfStep;
          const shortRange  = estCandles < needCandles;
          // How many more months needed (calendar months, rounded up)
          const extraCandles = needCandles - estCandles;
          const candlesPerMonth = (() => {
            const perDay: Record<string, number> = { '15m': 25, '1h': 6, '4h': 1.6, '1d': 1, '1w': 0.2 };
            return 21 * (perDay[form.interval] ?? 1);
          })();
          const extraMonths = Math.ceil(extraCandles / candlesPerMonth);
          return (
            <div>
              <div className="flex gap-2">
                <InputRow label="Window" type="number" value={form.wfWindow} field="wfWindow" />
                <InputRow label="Step" type="number" value={form.wfStep} field="wfStep" />
              </div>
              {shortRange && (
                <p className="text-[10px] text-red-600 bg-red-50 border border-red-200 rounded-lg px-2 py-1.5 mt-1 leading-snug">
                  ❌ Date range too short — ~{estCandles} candles estimated, need ≥{needCandles} (window + step).
                  Extend your date range by ~{extraMonths} more month{extraMonths !== 1 ? 's' : ''}, or reduce Window to ≤{Math.max(10, estCandles - form.wfStep)}.
                </p>
              )}
              {!shortRange && estCandles < needCandles * 2 && (
                <p className="text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5 mt-1 leading-snug">
                  ⚠️ Only ~{Math.floor((estCandles - form.wfWindow) / form.wfStep)} OOS window{Math.floor((estCandles - form.wfWindow) / form.wfStep) !== 1 ? 's' : ''} expected — a longer range gives more robust results.
                </p>
              )}
              {form.wfStep < 20 && (
                <p className="text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5 mt-1 leading-snug">
                  ⚠️ Step={form.wfStep} is very small — each OOS window will have only {form.wfStep} candles, too short for DCA/PLA cycles. Recommended: ≥30 for 1d data.
                </p>
              )}
              <p className="text-[10px] text-[var(--tv-muted)] mt-1 leading-snug">
                Window & Step in candles. For 1d data: 252 ≈ 1yr train, 63 ≈ 3-month test.
              </p>
            </div>
          );
        })()}
      </div>

      {/* ── Smart Fill (always visible, above Run) ── */}
      <div className="mb-3">
        <button
          type="button"
          onMouseDown={e => {
            e.preventDefault();          // prevent losing focus / scroll on mousedown
            const { updates, hint } = computeSmartDefaults(form);
            onChange(updates);
            setSmartHint(hint);
          }}
          className="w-full py-2.5 rounded-full text-sm font-bold text-white shadow-sm
            bg-[var(--tv-accent)] opacity-90 hover:opacity-100 active:scale-95 transition-all
            flex items-center justify-center gap-2"
        >
          ⚡ Smart Fill Settings
        </button>
        {smartHint && (
          <div className="mt-2 px-3 py-2 rounded-lg bg-green-50 border border-green-200 text-[10px] text-green-700 leading-relaxed">
            {smartHint}
          </div>
        )}
      </div>

      {/* Run Button */}
      <button
        onClick={onRun}
        disabled={loading}
        className={`w-full py-3.5 rounded-full font-bold transition-all text-white mt-auto shadow-sm hover:shadow-md ${
          loading 
            ? 'bg-gray-400 cursor-not-allowed' 
            : 'bg-[var(--tv-accent)] hover:bg-[var(--tv-accent-dark)] glow-pulse hover:-translate-y-0.5'
        }`}
      >
        {loading ? 'Running Backtest...' : 'Run Backtest'}
      </button>
    </div>
  );
}