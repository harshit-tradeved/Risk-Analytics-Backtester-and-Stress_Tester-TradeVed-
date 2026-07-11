import { BacktestResponse } from '../types';

interface Props {
  result:   BacktestResponse;
  symbol:   string;
  capital:  number;
  currency: string;
  /** Close prices for the tested period — enables a real buy-and-hold comparison */
  closePrices?: number[];
}

function fmt(n: number, dec = 0, locale = 'en-US') {
  return n.toLocaleString(locale, { maximumFractionDigits: dec });
}

function fmtCurrency(n: number, currency: string) {
  const locale = currency === '₹' ? 'en-IN' : 'en-US';
  return `${currency}${fmt(Math.abs(n), 0, locale)}`;
}

export default function PlainLanguageVerdict({ result, symbol, capital, currency, closePrices }: Props) {
  const r = result.results;
  if (!r) return null;

  const finalEquity      = r.final_equity ?? capital;
  const returnPct        = r.total_return_pct ?? 0;
  const maxDD            = r.max_drawdown_pct ?? 0;
  const sharpe           = r.sharpe_ratio ?? 0;
  const numTrades        = r.num_trades ?? 0;
  const annualReturn     = r.annualised_return_pct ?? 0;

  const gained = finalEquity > capital;

  // Real buy-and-hold return for the same symbol/period when price data is
  // available; the 8%/yr proxy is only the fallback.
  const bhPct = closePrices && closePrices.length >= 2 && closePrices[0] > 0
    ? ((closePrices[closePrices.length - 1] / closePrices[0]) - 1) * 100
    : null;
  const vsLong = bhPct !== null ? returnPct > bhPct : annualReturn > 8;

  // Plain-language headline
  const headlineVerb = gained ? 'would have grown to' : 'would have dropped to';
  const headlineAmt  = fmtCurrency(finalEquity, currency);
  const returnLabel  = gained
    ? `+${returnPct.toFixed(1)}% gain`
    : `${returnPct.toFixed(1)}% loss`;

  // DD warning
  const ddSevere = Math.abs(maxDD) > 20;
  const ddLabel  = `${Math.abs(maxDD).toFixed(1)}%`;

  // Verdict badge
  const verdict = numTrades === 0
    ? { label: 'No Trades', color: 'gray' }
    : sharpe >= 1.0 && gained
    ? { label: 'Looks Promising', color: 'green' }
    : gained && sharpe > 0
    ? { label: 'Modest Returns', color: 'yellow' }
    : { label: 'Underperforms', color: 'red' };

  const badgeStyle: Record<string, string> = {
    green:  'bg-green-50 text-green-700 border-green-200',
    yellow: 'bg-yellow-50 text-yellow-700 border-yellow-200',
    red:    'bg-red-50 text-red-700 border-red-200',
    gray:   'bg-gray-50 text-gray-600 border-gray-200',
  };

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden mb-6">
      {/* Top verdict strip */}
      <div className={`px-5 py-3 flex items-center justify-between border-b ${
        gained ? 'bg-green-50 border-green-100' : 'bg-red-50 border-red-100'
      }`}>
        <div className="flex items-center gap-2">
          <span className="text-lg">{gained ? '📈' : '📉'}</span>
          <span className="font-bold text-gray-900 text-sm">{symbol} — Reel Strategy Results</span>
        </div>
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${badgeStyle[verdict.color]}`}>
          {verdict.label}
        </span>
      </div>

      <div className="p-5">
        {/* Main headline */}
        <p className="text-base font-semibold text-gray-900 leading-snug mb-1">
          {fmtCurrency(capital, currency)} invested {headlineVerb}{' '}
          <span className={gained ? 'text-green-600' : 'text-red-600'}>{headlineAmt}</span>
          {' '}({returnLabel})
        </p>

        {/* DD sub-line */}
        <p className={`text-sm mt-1.5 ${ddSevere ? 'text-red-600' : 'text-gray-500'}`}>
          {ddSevere
            ? `But at one point you'd have been down ${ddLabel} — most people panic-sell here.`
            : `Maximum drawdown was ${ddLabel} — relatively contained.`}
        </p>

        {/* vs buy-and-hold note */}
        <p className="text-xs text-gray-400 mt-1">
          {bhPct !== null
            ? vsLong
              ? `Strategy returned ${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(1)}% vs ${bhPct >= 0 ? '+' : ''}${bhPct.toFixed(1)}% for simply holding ${symbol} over the same period — the strategy did better.`
              : `Strategy returned ${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(1)}% vs ${bhPct >= 0 ? '+' : ''}${bhPct.toFixed(1)}% for simply holding ${symbol} over the same period — buy-and-hold would have done better.`
            : vsLong
              ? `${annualReturn.toFixed(1)}% annual return — beats a simple buy-and-hold approach.`
              : `${annualReturn.toFixed(1)}% annual return — a simple buy-and-hold on ${symbol} may have done better.`
          }
        </p>

        {/* Key stats row */}
        <div className="mt-4 grid grid-cols-3 gap-3">
          {[
            { label: 'Sharpe Ratio',    value: sharpe.toFixed(2),       good: sharpe >= 1.0 },
            { label: 'Max Drawdown',    value: `-${ddLabel}`,           good: Math.abs(maxDD) < 15 },
            { label: 'Trades',          value: String(numTrades),       good: numTrades > 5 },
          ].map(s => (
            <div key={s.label} className="text-center bg-gray-50 rounded-lg py-2.5 px-2">
              <p className={`text-base font-bold ${s.good ? 'text-gray-900' : 'text-red-500'}`}>{s.value}</p>
              <p className="text-xs text-gray-400 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* Honest disclaimer */}
        <div className="mt-4 bg-amber-50 border border-amber-100 rounded-lg px-4 py-3">
          <p className="text-xs text-amber-700 leading-relaxed">
            <span className="font-semibold">Not financial advice.</span>{' '}
            Past performance does not guarantee future results. This backtest uses historical data
            and cannot account for future market conditions, liquidity, or execution quality.
            Always do your own research before trading.
          </p>
        </div>
      </div>
    </div>
  );
}
