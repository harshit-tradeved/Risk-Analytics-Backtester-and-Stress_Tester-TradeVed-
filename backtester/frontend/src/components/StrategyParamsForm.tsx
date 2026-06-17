import { ParamSchema } from '../types';

/**
 * Schema-driven strategy parameter form.
 *
 * Renders inputs generically from a strategy's `schema` (GET /api/strategies),
 * honoring per-param type, `group` (section headers), and `depends_on`
 * (conditional visibility). Writes values into the flat `value` bag and emits
 * the full updated bag via `onChange`. Used by Sidebar + StressSidebar for
 * every non-classic strategy, so new backend strategies need zero frontend work.
 *
 * `array` params are edited as comma-separated values (used by PLA-style lists);
 * the rule-builder strategy (CUSTOM) is handled by a dedicated RuleBuilder, not
 * this generic renderer.
 */
export interface StrategyParamsFormProps {
  schema:   Record<string, ParamSchema>;
  value:    Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

function visible(p: ParamSchema, value: Record<string, unknown>): boolean {
  if (!p.depends_on) return true;
  return value[p.depends_on.field] === p.depends_on.value;
}

export default function StrategyParamsForm({ schema, value, onChange }: StrategyParamsFormProps) {
  const set = (name: string, v: unknown) => onChange({ ...value, [name]: v });

  // Group params by their `group` field, preserving declaration order.
  const groups: Record<string, [string, ParamSchema][]> = {};
  const order: string[] = [];
  for (const [name, p] of Object.entries(schema)) {
    const g = p.group ?? 'Parameters';
    if (!(g in groups)) { groups[g] = []; order.push(g); }
    groups[g].push([name, p]);
  }

  const fieldCls =
    'w-28 px-3 py-1.5 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] text-right border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]';
  const selectCls =
    'w-full px-3 py-2 bg-[var(--tv-s2)] rounded-lg text-sm text-[var(--tv-text)] border-none outline-none focus:ring-2 focus:ring-[var(--tv-accent)]';

  return (
    <div className="pl-2 border-l-2 border-[var(--tv-border)] space-y-3 mt-4">
      {order.map(g => (
        <div key={g} className="space-y-3">
          {order.length > 1 && (
            <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--tv-muted)] pt-1">{g}</div>
          )}
          {groups[g].map(([name, p]) => {
            if (!visible(p, value)) return null;
            const cur = value[name] ?? p.default;

            if (p.type === 'select') {
              return (
                <div key={name} className="flex flex-col mb-1">
                  <label className="text-sm font-medium text-[var(--tv-text)] mb-1" title={p.help}>{p.label}</label>
                  <select className={selectCls} value={String(cur)} onChange={e => set(name, e.target.value)}>
                    {(p.options ?? []).map(o => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
                  </select>
                </div>
              );
            }

            if (p.type === 'bool') {
              return (
                <div key={name} className="flex justify-between items-center mb-1">
                  <label className="text-sm font-medium text-[var(--tv-text)]" title={p.help}>{p.label}</label>
                  <input type="checkbox" checked={Boolean(cur)} onChange={e => set(name, e.target.checked)}
                         className="w-4 h-4 accent-[var(--tv-accent)]" />
                </div>
              );
            }

            if (p.type === 'array') {
              const text = Array.isArray(cur) ? (cur as unknown[]).join(', ') : String(cur ?? '');
              return (
                <div key={name} className="flex flex-col mb-1">
                  <label className="text-sm font-medium text-[var(--tv-text)] mb-1" title={p.help}>{p.label}</label>
                  <input type="text" className={selectCls + ' text-right'} value={text}
                         placeholder="comma-separated"
                         onChange={e => set(name, e.target.value.split(',').map(s => {
                           const n = Number(s.trim());
                           return s.trim() === '' ? null : (Number.isNaN(n) ? s.trim() : n);
                         }).filter(v => v !== null))} />
                </div>
              );
            }

            // number / text
            const isNum = p.type === 'number';
            return (
              <div key={name} className="flex justify-between items-center mb-1">
                <label className="text-sm font-medium text-[var(--tv-text)]" title={p.help}>{p.label}</label>
                <input
                  type={isNum ? 'number' : 'text'}
                  min={p.min} max={p.max} step={p.step}
                  className={fieldCls}
                  value={cur as string | number}
                  onChange={e => set(name, isNum ? Number(e.target.value) : e.target.value)}
                />
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/** Seed a strategyParams bag from a schema's defaults. */
export function defaultsFromSchema(schema: Record<string, ParamSchema>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, p] of Object.entries(schema)) out[name] = p.default;
  return out;
}
