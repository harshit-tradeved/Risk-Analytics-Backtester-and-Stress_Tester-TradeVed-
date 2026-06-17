import { useEffect, useState } from 'react';
import { IndicatorMeta } from '../types';
import { fetchIndicators } from '../api';

/**
 * Rule builder UI for the CUSTOM strategy ("strategies we can create").
 *
 * Lets the user compose entry/exit condition rows over the indicator catalog
 * (GET /api/indicators) and serializes them into `strategyParams` in the shape
 * the backend CustomStrategy evaluator expects:
 *   { entry_rules:[rule], exit_rules:[rule], logic:'AND'|'OR',
 *     invest_per_trade_usd, quantity }
 * where rule = { left:{indicator,params,output}|{price}, operator, right:{value}|{indicator,...} }.
 */
const OPERATORS = ['>', '>=', '<', '<=', 'cross_above', 'cross_below'] as const;
const PRICE_COLS = ['close', 'open', 'high', 'low', 'volume'] as const;

type Operand =
  | { price: string }
  | { indicator: string; params: Record<string, number>; output: string }
  | { value: number };

interface Rule { left: Operand; operator: string; right: Operand }

export interface RuleBuilderProps {
  value:    Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

function firstOutput(ind: IndicatorMeta): string { return ind.outputs[0]; }
function defaultParams(ind: IndicatorMeta): Record<string, number> {
  const p: Record<string, number> = {};
  for (const param of ind.params) p[param.name] = param.default;
  return p;
}

export default function RuleBuilder({ value, onChange }: RuleBuilderProps) {
  const [catalog, setCatalog] = useState<IndicatorMeta[]>([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    fetchIndicators().then(c => setCatalog(c.indicators)).catch(e => setErr(String(e.message ?? e)));
  }, []);

  const entry = (value.entry_rules as Rule[] | undefined) ?? [];
  const exit  = (value.exit_rules  as Rule[] | undefined) ?? [];
  const logic = (value.logic as string) ?? 'AND';

  const patch = (k: string, v: unknown) => onChange({ ...value, [k]: v });

  const byKey = (k: string) => catalog.find(i => i.key === k);

  const newRule = (): Rule => {
    const ind = catalog[0];
    return {
      left: ind ? { indicator: ind.key, params: defaultParams(ind), output: firstOutput(ind) } : { price: 'close' },
      operator: '<',
      right: { value: 30 },
    };
  };

  const updateRules = (kind: 'entry' | 'exit', rules: Rule[]) =>
    patch(kind === 'entry' ? 'entry_rules' : 'exit_rules', rules);

  const setOperand = (rule: Rule, side: 'left' | 'right', op: Operand): Rule => ({ ...rule, [side]: op });

  const renderOperand = (rule: Rule, side: 'left' | 'right', rules: Rule[], idx: number, kind: 'entry' | 'exit') => {
    const op = rule[side];
    const kindOf = 'value' in op ? 'value' : 'price' in op ? 'price' : 'indicator';
    const commit = (next: Operand) => {
      const nr = [...rules]; nr[idx] = setOperand(rule, side, next); updateRules(kind, nr);
    };
    return (
      <div className="flex flex-col gap-1">
        <select
          className="px-2 py-1 bg-[var(--tv-s2)] rounded text-xs"
          value={kindOf}
          onChange={e => {
            const t = e.target.value;
            if (t === 'value') commit({ value: 0 });
            else if (t === 'price') commit({ price: 'close' });
            else { const ind = catalog[0]; commit(ind ? { indicator: ind.key, params: defaultParams(ind), output: firstOutput(ind) } : { value: 0 }); }
          }}
        >
          {side === 'right' && <option value="value">Value</option>}
          <option value="indicator">Indicator</option>
          <option value="price">Price</option>
        </select>

        {'value' in op && (
          <input type="number" className="w-20 px-2 py-1 bg-[var(--tv-s2)] rounded text-xs text-right"
                 value={op.value} onChange={e => commit({ value: Number(e.target.value) })} />
        )}
        {'price' in op && (
          <select className="px-2 py-1 bg-[var(--tv-s2)] rounded text-xs" value={op.price}
                  onChange={e => commit({ price: e.target.value })}>
            {PRICE_COLS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
        {'indicator' in op && (
          <>
            <select className="px-2 py-1 bg-[var(--tv-s2)] rounded text-xs" value={op.indicator}
                    onChange={e => {
                      const ind = byKey(e.target.value)!;
                      commit({ indicator: ind.key, params: defaultParams(ind), output: firstOutput(ind) });
                    }}>
              {catalog.map(i => <option key={i.key} value={i.key}>{i.label}</option>)}
            </select>
            {(byKey(op.indicator)?.outputs.length ?? 0) > 1 && (
              <select className="px-2 py-1 bg-[var(--tv-s2)] rounded text-xs" value={op.output}
                      onChange={e => commit({ ...op, output: e.target.value })}>
                {byKey(op.indicator)!.outputs.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {byKey(op.indicator)?.params.map(pr => (
              <input key={pr.name} type="number" title={pr.name}
                     className="w-20 px-2 py-1 bg-[var(--tv-s2)] rounded text-xs text-right"
                     value={op.params[pr.name] ?? pr.default}
                     onChange={e => commit({ ...op, params: { ...op.params, [pr.name]: Number(e.target.value) } })} />
            ))}
          </>
        )}
      </div>
    );
  };

  const renderRuleList = (kind: 'entry' | 'exit', rules: Rule[]) => (
    <div className="space-y-2">
      {rules.map((rule, idx) => (
        <div key={idx} className="flex items-start gap-2 p-2 bg-[var(--tv-bg)] rounded border border-[var(--tv-border)]">
          {renderOperand(rule, 'left', rules, idx, kind)}
          <select className="px-2 py-1 bg-[var(--tv-s2)] rounded text-xs mt-0" value={rule.operator}
                  onChange={e => { const nr = [...rules]; nr[idx] = { ...rule, operator: e.target.value }; updateRules(kind, nr); }}>
            {OPERATORS.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          {renderOperand(rule, 'right', rules, idx, kind)}
          <button className="text-[var(--tv-red,#e74)] text-xs ml-auto mt-1"
                  onClick={() => updateRules(kind, rules.filter((_, i) => i !== idx))}>✕</button>
        </div>
      ))}
      <button className="text-xs text-[var(--tv-accent)] underline"
              onClick={() => updateRules(kind, [...rules, newRule()])}>+ Add {kind} rule</button>
    </div>
  );

  if (err) return <div className="text-xs text-red-500 mt-4">Failed to load indicators: {err}</div>;
  if (!catalog.length) return <div className="text-xs text-[var(--tv-muted)] mt-4">Loading indicators…</div>;

  return (
    <div className="pl-2 border-l-2 border-[var(--tv-border)] space-y-4 mt-4">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--tv-muted)] mb-2">Entry Rules</div>
        {renderRuleList('entry', entry)}
      </div>
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--tv-muted)] mb-2">Exit Rules</div>
        {renderRuleList('exit', exit)}
      </div>
      <div className="flex justify-between items-center">
        <label className="text-sm font-medium">Combine With</label>
        <select className="px-3 py-1.5 bg-[var(--tv-s2)] rounded-lg text-sm" value={logic}
                onChange={e => patch('logic', e.target.value)}>
          <option value="AND">AND</option>
          <option value="OR">OR</option>
        </select>
      </div>
      <div className="flex justify-between items-center">
        <label className="text-sm font-medium">Invest / Trade (USD)</label>
        <input type="number" className="w-28 px-3 py-1.5 bg-[var(--tv-s2)] rounded-lg text-sm text-right"
               value={(value.invest_per_trade_usd as number) ?? 1000}
               onChange={e => patch('invest_per_trade_usd', Number(e.target.value))} />
      </div>
    </div>
  );
}

/** Seed default CUSTOM params (mirrors backend CustomStrategy.default_params). */
export function defaultCustomParams(): Record<string, unknown> {
  return {
    entry_rules: [{ left: { indicator: 'rsi', params: { length: 14 }, output: 'rsi' }, operator: '<', right: { value: 30 } }],
    exit_rules:  [{ left: { indicator: 'rsi', params: { length: 14 }, output: 'rsi' }, operator: '>', right: { value: 70 } }],
    logic: 'AND',
    invest_per_trade_usd: 1000,
    quantity: 0.01,
  };
}
