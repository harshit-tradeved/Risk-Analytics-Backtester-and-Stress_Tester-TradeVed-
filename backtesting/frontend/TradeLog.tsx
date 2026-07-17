import { useState } from 'react';
import { Trade } from '@app/types';

interface Props { trades: Trade[]; currency?: string; }

type SortKey = keyof Trade | 'duration';
type SortDir = 'asc' | 'desc';

/* ── TradeVed palette ─────────────────────────────────────────────────── */
const GREEN  = 'var(--tv-green)';
const RED    = 'var(--tv-red)';
const GREY   = 'var(--tv-muted)';
const TEXT   = 'var(--tv-text)';
const DIM    = 'var(--tv-dim)';
const CARD   = 'var(--tv-s1)';
const BORDER = 'var(--tv-border)';

export default function TradeLog({ trades, currency = '$' }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'entry_time', dir: 'asc' });
  const locale   = currency === '₹' ? 'en-IN' : 'en-US';
  const fmtPrice = (n: number) => `${currency}${n.toLocaleString(locale, { maximumFractionDigits: 2 })}`;

  if (!trades.length) {
    return (
      <div className="flex items-center justify-center h-40 rounded-xl"
        style={{ background: CARD, border: `1px solid ${BORDER}` }}>
        <p style={{ color: GREY }}>No completed trades in this backtest.</p>
      </div>
    );
  }

  /* Compute durations */
  const rows = trades.map((t, i) => {
    let durH = 0;
    try {
      if (t.entry_time && t.exit_time) {
        durH = (new Date(t.exit_time).getTime() - new Date(t.entry_time).getTime()) / 3_600_000;
      }
    } catch { /* */ }
    return { ...t, _i: i + 1, duration: durH };
  });

  /* Sort */
  const sorted = [...rows].sort((a, b) => {
    const av = (a as any)[sort.key];
    const bv = (b as any)[sort.key];
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sort.dir === 'asc' ? cmp : -cmp;
  });

  const toggleSort = (key: SortKey) => {
    setSort(prev => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }));
  };

  const winners    = trades.filter(t => t.pnl > 0).length;
  const losers     = trades.length - winners;
  const totalPnl   = trades.reduce((s, t) => s + t.pnl, 0);
  const winRate    = winners / trades.length;

  return (
    <div className="fade-in">
      {/* Summary bar */}
      <div className="flex flex-wrap gap-4 mb-3 px-1 pb-3"
        style={{ borderBottom: `1px solid ${BORDER}` }}>
        <Stat label="Total"    value={trades.length.toString()} />
        <Stat label="Winners"  value={winners.toString()} color={GREEN} />
        <Stat label="Losers"   value={losers.toString()}  color={RED}   />
        <Stat label="Win Rate" value={`${(winRate * 100).toFixed(1)}%`}
          color={winRate >= 0.5 ? GREEN : RED} />
        <Stat label="Gross P&L"
          value={`${totalPnl >= 0 ? '+' : ''}${fmtPrice(Math.abs(totalPnl))}`}
          color={totalPnl >= 0 ? GREEN : RED} />
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl" style={{ border: `1px solid ${BORDER}` }}>
        <table className="w-full text-xs" style={{ background: CARD }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BORDER}` }}>
              {[
                { key: '_i',          label: '#'        },
                { key: 'entry_time',  label: 'Entry'    },
                { key: 'entry_price', label: 'Entry $'  },
                { key: 'exit_time',   label: 'Exit'     },
                { key: 'exit_price',  label: 'Exit $'   },
                { key: 'quantity',    label: 'Qty'      },
                { key: 'pnl',         label: 'P&L ($)'  },
                { key: 'pnl_pct',     label: 'P&L (%)'  },
                { key: 'fees',        label: 'Fees'     },
                { key: 'duration',    label: 'Duration' },
              ].map(col => (
                <th key={col.key}
                  onClick={() => toggleSort(col.key as SortKey)}
                  className="px-3 py-2.5 text-left font-semibold cursor-pointer select-none
                    whitespace-nowrap transition-colors"
                  style={{ color: sort.key === col.key ? GREEN : GREY }}>
                  {col.label}
                  {sort.key === col.key && (
                    <span className="ml-1 text-[#A8EC3A]">{sort.dir === 'asc' ? '↑' : '↓'}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t, i) => {
              const pnlColor = t.pnl > 0 ? GREEN : t.pnl < 0 ? RED : GREY;
              const dur      = t.duration < 48
                ? `${t.duration.toFixed(1)}h`
                : `${(t.duration / 24).toFixed(1)}d`;
              return (
                <tr key={i}
                  className="transition-colors"
                  style={{ borderBottom: `1px solid ${BORDER}` }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--tv-s3)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="px-3 py-2" style={{ color: DIM }}>{t._i}</td>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: TEXT }}>{fmtTime(t.entry_time)}</td>
                  <td className="px-3 py-2" style={{ color: TEXT }}>
                    {fmtPrice(t.entry_price)}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap" style={{ color: TEXT }}>
                    {t.exit_time ? fmtTime(t.exit_time) : '—'}
                  </td>
                  <td className="px-3 py-2" style={{ color: TEXT }}>
                    {t.exit_price ? fmtPrice(t.exit_price) : '—'}
                  </td>
                  <td className="px-3 py-2" style={{ color: TEXT }}>{t.quantity.toFixed(6)}</td>
                  <td className="px-3 py-2 font-bold" style={{ color: pnlColor }}>
                    {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(4)}
                  </td>
                  <td className="px-3 py-2 font-bold" style={{ color: pnlColor }}>
                    {(t.pnl_pct * 100) >= 0 ? '+' : ''}{(t.pnl_pct * 100).toFixed(2)}%
                  </td>
                  <td className="px-3 py-2" style={{ color: DIM }}>{t.fees.toFixed(4)}</td>
                  <td className="px-3 py-2" style={{ color: DIM }}>
                    {t.duration > 0 ? dur : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, color = TEXT }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex gap-1.5 items-baseline">
      <span className="text-xs" style={{ color: GREY }}>{label}:</span>
      <span className="text-sm font-bold" style={{ color }}>{value}</span>
    </div>
  );
}

function fmtTime(ts: string) {
  try { return ts.replace('T', ' ').slice(0, 16); }
  catch { return ts; }
}
