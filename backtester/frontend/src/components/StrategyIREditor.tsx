import { useState, useEffect } from 'react';
import { StrategyIR, IRRule } from '../types';

interface Props {
  ir:           StrategyIR;
  gaps:         string[];
  onChange:     (updated: StrategyIR) => void;
  onConfirm:    () => void;
  loading:      boolean;
  serverErrors?: string[];
}

function ruleToHuman(rule: IRRule): string {
  const side = (op: IRRule['left'] | IRRule['right']) => {
    if (!op) return '?';
    if ('value'     in op && op.value  !== undefined) return String(op.value);
    if ('price'     in op && op.price)  return op.price;
    if ('indicator' in op && op.indicator) {
      const params = op.params
        ? '(' + Object.entries(op.params).map(([k, v]) => `${k}=${v}`).join(', ') + ')'
        : '';
      return `${op.indicator.toUpperCase()}${params}`;
    }
    return JSON.stringify(op);
  };
  const opMap: Record<string, string> = {
    '>': '>', '>=': '≥', '<': '<', '<=': '≤',
    cross_above: 'crosses above', cross_below: 'crosses below',
  };
  return `${side(rule.left)} ${opMap[rule.operator] ?? rule.operator} ${side(rule.right)}`;
}

function RulesList({ rules, label }: { rules: IRRule[]; label: string }) {
  if (!rules?.length) return null;
  return (
    <div className="mb-3">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <ul className="space-y-1">
        {rules.map((r, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <span className="mt-0.5 w-4 h-4 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[10px] font-bold flex-shrink-0">{i + 1}</span>
            <code className="text-gray-800 bg-gray-50 border border-gray-100 rounded px-2 py-0.5">{ruleToHuman(r)}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function StrategyIREditor({ ir, gaps, onChange, onConfirm, loading, serverErrors = [] }: Props) {
  const [showRaw, setShowRaw] = useState(false);
  const [rawText, setRawText] = useState(JSON.stringify(ir, null, 2));
  const [rawError, setRawError] = useState('');

  // Sync rawText when the ir prop changes (e.g. after re-analyze)
  useEffect(() => {
    setRawText(JSON.stringify(ir, null, 2));
    setRawError('');
    setShowRaw(false);
  }, [ir]);

  const isCustom = ir.strategy === 'CUSTOM';
  const params   = (ir.params ?? {}) as Record<string, unknown>;
  const logic    = isCustom ? String(params.logic ?? 'AND') : null;
  const entryRules: IRRule[] = isCustom ? ((params.entry_rules ?? []) as IRRule[]) : [];
  const exitRules:  IRRule[] = isCustom ? ((params.exit_rules  ?? []) as IRRule[]) : [];

  const hasGaps       = gaps.length > 0;
  const hasErrors     = rawError.length > 0;
  // Server-reported errors gate the run button in BOTH views — the parent
  // clears them when the user applies an edited IR, so they're never stale.
  const hasServerErrs = serverErrors.length > 0;

  function applyRaw() {
    try {
      const parsed = JSON.parse(rawText);
      if (!parsed.strategy || !parsed.params) throw new Error("Must have 'strategy' and 'params' keys");
      onChange(parsed as StrategyIR);
      setRawError('');
      setShowRaw(false);
    } catch (e: any) {
      setRawError(e.message);
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 text-sm">Extracted Strategy</h3>
          <p className="text-xs text-gray-500 mt-0.5">Review before running the backtest</p>
        </div>
        <button onClick={() => setShowRaw(v => !v)}
          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium px-2 py-1 rounded border border-indigo-200 hover:bg-indigo-50 transition-colors">
          {showRaw ? 'View readable' : 'Edit JSON'}
        </button>
      </div>

      <div className="p-5">
        {/* Strategy name badge */}
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs text-gray-500">Strategy:</span>
          <span className="px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 font-semibold text-xs border border-indigo-100">
            {ir.strategy}
          </span>
          {isCustom && logic && (
            <span className="px-2.5 py-0.5 rounded-full bg-gray-50 text-gray-600 font-medium text-xs border border-gray-200">
              Rules combined with {logic}
            </span>
          )}
        </div>

        {showRaw ? (
          <div>
            <textarea
              className="w-full font-mono text-xs bg-gray-50 border border-gray-200 rounded-lg p-3 h-64 resize-y focus:outline-none focus:border-indigo-400"
              value={rawText}
              onChange={e => setRawText(e.target.value)}
              spellCheck={false}
            />
            {rawError && (
              <p className="text-red-600 text-xs mt-1">{rawError}</p>
            )}
            <button onClick={applyRaw}
              className="mt-2 text-xs px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium">
              Apply JSON changes
            </button>
          </div>
        ) : isCustom ? (
          <>
            <RulesList rules={entryRules} label="Buy when" />
            <RulesList rules={exitRules}  label="Sell when" />
            {!exitRules.length && (
              <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
                No exit rules extracted — strategy will hold until end of period. Add exit rules in the JSON editor if needed.
              </p>
            )}
          </>
        ) : (
          <div className="space-y-2">
            {Object.entries(params).map(([k, v]) => (
              <div key={k} className="flex items-center gap-3 text-sm">
                <span className="text-gray-500 w-36 truncate">{k.replace(/_/g, ' ')}</span>
                <code className="text-gray-900 bg-gray-50 border border-gray-100 rounded px-2 py-0.5 text-xs">
                  {JSON.stringify(v)}
                </code>
              </div>
            ))}
          </div>
        )}

        {/* Server-side IR validation errors */}
        {hasServerErrs && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="text-xs font-semibold text-red-700 mb-1.5">IR validation errors — use "Edit JSON" to fix:</p>
            <ul className="space-y-1">
              {serverErrors.map((e, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-red-600">
                  <span className="mt-0.5 text-red-400">✕</span>
                  <span>{e}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Gaps / REQUIRES_SPECIFICATION warnings */}
        {hasGaps && (
          <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            <p className="text-xs font-semibold text-yellow-800 mb-1.5">
              Missing information — review before running:
            </p>
            <ul className="space-y-1">
              {gaps.map((g, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-yellow-700">
                  <span className="mt-0.5 text-yellow-500">⚠</span>
                  <span>{g}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-yellow-600 mt-2">
              Use "Edit JSON" to fill in missing values or adjust defaults.
            </p>
          </div>
        )}
      </div>

      {/* Confirm button */}
      <div className="px-5 py-4 border-t border-gray-100 bg-gray-50">
        <button
          onClick={onConfirm}
          disabled={loading || hasErrors || hasServerErrs}
          className={`w-full py-2.5 rounded-lg font-semibold text-sm transition-all ${
            loading || hasErrors || hasServerErrs
              ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
              : 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm'
          }`}>
          {loading ? 'Running backtest…' : hasServerErrs ? 'Fix IR errors before running' : 'Looks right — run backtest'}
        </button>
        {hasGaps && !loading && (
          <p className="text-center text-xs text-gray-400 mt-2">
            You can run with gaps — defaults will be used where info is missing.
          </p>
        )}
      </div>
    </div>
  );
}
