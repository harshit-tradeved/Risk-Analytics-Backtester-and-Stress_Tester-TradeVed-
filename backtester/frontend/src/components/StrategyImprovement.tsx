import { ImproveResponse } from '../types';

interface Props {
  result:   ImproveResponse;
  currency: string;
}

function fmt(n: number, dec = 2, locale = 'en-US') {
  return n.toLocaleString(locale, { maximumFractionDigits: dec, minimumFractionDigits: 0 });
}

function DiffRowView({ row, currency }: { row: ImproveResponse['diff'][number]; currency: string }) {
  const isMoney = row.key === 'final_equity' || row.key === 'total_fees_paid';
  const isPct   = row.label.includes('%') || row.key === 'sharpe_ratio' || row.key === 'sortino_ratio' || row.key === 'calmar_ratio' || row.key === 'profit_factor';
  const fmtVal = (v: number) => isMoney ? `${currency}${fmt(v, 0)}` : `${fmt(v, 2)}${row.label.includes('%') ? '%' : ''}`;

  const color = row.better === true ? 'text-green-600' : row.better === false ? 'text-red-600' : 'text-gray-500';
  const arrow = row.delta > 0 ? '▲' : row.delta < 0 ? '▼' : '—';

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="py-2 pr-3 text-xs text-gray-500">{row.label}</td>
      <td className="py-2 px-3 text-sm text-gray-700 text-right">{fmtVal(row.original)}</td>
      <td className="py-2 px-3 text-sm text-gray-900 font-semibold text-right">{fmtVal(row.improved)}</td>
      <td className={`py-2 pl-3 text-xs font-semibold text-right ${color}`}>
        {arrow} {fmtVal(Math.abs(row.delta))}
        {row.pct_change !== null && Math.abs(row.pct_change) < 10000 && (
          <span className="ml-1 opacity-70">({row.pct_change >= 0 ? '+' : ''}{fmt(row.pct_change, 1)}%)</span>
        )}
      </td>
    </tr>
  );
}

export default function StrategyImprovement({ result, currency }: Props) {
  const { problems, changes, diff, judge, improved_result } = result;

  const riskColor: Record<string, string> = {
    low:     'bg-green-50 text-green-700 border-green-200',
    medium:  'bg-yellow-50 text-yellow-700 border-yellow-200',
    high:    'bg-red-50 text-red-700 border-red-200',
    unknown: 'bg-gray-50 text-gray-600 border-gray-200',
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-base font-bold text-gray-900">🔍 Diagnosis & Improvement</h3>
        <span className="text-xs text-gray-400">Confidence {(result.confidence * 100).toFixed(0)}%</span>
      </div>

      {/* Problems */}
      {problems.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <h4 className="text-sm font-semibold text-gray-900 mb-2">Problems found in the original backtest</h4>
          <ul className="space-y-1.5">
            {problems.map((p, i) => (
              <li key={i} className="text-sm text-gray-600 flex gap-2">
                <span className="text-red-400 mt-0.5">•</span><span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Changes made */}
      {changes.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
          <h4 className="text-sm font-semibold text-gray-900 mb-2">Changes applied</h4>
          <div className="space-y-2">
            {changes.map((c, i) => (
              <div key={i} className="text-sm bg-gray-50 rounded-lg px-3 py-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">{c.field}</span>
                  <span className="text-gray-400 text-xs line-through">{String(c.before)}</span>
                  <span className="text-gray-400">→</span>
                  <span className="text-gray-900 font-semibold text-xs">{String(c.after)}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">{c.reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Diff table — real, engine-computed numbers */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm overflow-x-auto">
        <h4 className="text-sm font-semibold text-gray-900 mb-1">Original vs. Improved (both re-run on identical data)</h4>
        <p className="text-xs text-gray-400 mb-3">
          These numbers come from actually re-running the improved strategy through the backtest engine — not a prediction.
        </p>
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left text-xs text-gray-400 font-medium pb-2">Metric</th>
              <th className="text-right text-xs text-gray-400 font-medium pb-2">Original</th>
              <th className="text-right text-xs text-gray-400 font-medium pb-2">Improved</th>
              <th className="text-right text-xs text-gray-400 font-medium pb-2">Δ Change</th>
            </tr>
          </thead>
          <tbody>
            {diff.map(row => <DiffRowView key={row.key} row={row} currency={currency} />)}
          </tbody>
        </table>
      </div>

      {/* Judge verdict */}
      <div className={`rounded-xl border p-4 ${judge.approved ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="text-lg">{judge.approved ? '✅' : '⚠️'}</span>
            <span className="font-bold text-sm text-gray-900">
              Judge LLM: {judge.approved ? 'Verified — no issues found' : 'Flagged issues'}
            </span>
          </div>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${riskColor[judge.overfit_risk] ?? riskColor.unknown}`}>
            Overfit risk: {judge.overfit_risk}
          </span>
        </div>
        {judge.notes && <p className="text-sm text-gray-600 mt-2">{judge.notes}</p>}
        {judge.issues.length > 0 && (
          <ul className="mt-2 space-y-1">
            {judge.issues.map((iss, i) => (
              <li key={i} className="text-xs text-amber-700 flex gap-1.5">
                <span>•</span><span>{iss}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-gray-400 mt-3 italic">
          The Judge audits the process (are changes real, is the diff consistent, is this overfit) —
          it does not recompute or alter the backtest numbers above.
        </p>
      </div>

      {improved_result.results.num_trades === 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          The improved strategy produced 0 trades on this data — treat this as a failed improvement, not a win.
        </div>
      )}
    </div>
  );
}
