import { useEffect, useState } from 'react';
import { fetchAdminSummary, fetchAdminEvents, fetchAdminFeedback } from '../../api';
import { AdminSummary, AdminEvent, AdminFeedback } from '../../types';

interface Props {
  token: string;
}

type AdminTab = 'summary' | 'events' | 'feedback';

const CATEGORY_COLORS: Record<string, string> = {
  bug:    'bg-red-100 text-red-700',
  idea:   'bg-blue-100 text-blue-700',
  praise: 'bg-green-100 text-green-700',
  other:  'bg-gray-100 text-gray-700',
};

const CATEGORY_EMOJI: Record<string, string> = {
  bug: '🐞', idea: '💡', praise: '👍', other: '💬',
};

export default function AdminDashboard({ token }: Props) {
  const [tab,      setTab]      = useState<AdminTab>('summary');
  const [summary,  setSummary]  = useState<AdminSummary | null>(null);
  const [events,   setEvents]   = useState<AdminEvent[]>([]);
  const [feedback, setFeedback] = useState<AdminFeedback[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');

  const [eventUser,   setEventUser]   = useState('');
  const [eventType,   setEventType]   = useState('');

  useEffect(() => { loadSummary(); }, []);

  const loadSummary = async () => {
    setLoading(true); setError('');
    try { setSummary(await fetchAdminSummary(token)); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const loadEvents = async (overrideUser?: string) => {
    setLoading(true); setError('');
    try {
      setEvents(await fetchAdminEvents(token, {
        limit: 200,
        user:  overrideUser ?? (eventUser || undefined),
        type:  eventType || undefined,
      }));
    }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const loadFeedback = async () => {
    setLoading(true); setError('');
    try { setFeedback(await fetchAdminFeedback(token)); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const switchTab = (t: AdminTab, overrideUser?: string) => {
    setTab(t);
    if (t === 'summary')  loadSummary();
    if (t === 'events')   loadEvents(overrideUser);
    if (t === 'feedback') loadFeedback();
  };

  const fmt = (iso: string) => new Date(iso).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' });

  return (
    <div className="p-8 max-w-[1200px] mx-auto fade-in">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tv-text)]">Admin Dashboard</h1>
          <p className="text-sm text-[var(--tv-muted)] mt-0.5">Usage analytics and tester feedback</p>
        </div>
        <button onClick={() => switchTab(tab)}
          className="px-4 py-2 rounded-full text-sm font-semibold bg-white border border-gray-200 shadow-sm hover:bg-gray-50">
          ↺ Refresh
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-2 p-1 bg-white rounded-full tv-soft-shadow w-max mb-6">
        {([
          { key: 'summary',  label: '📊 Summary'  },
          { key: 'events',   label: '⚡ Events'    },
          { key: 'feedback', label: '💬 Feedback'  },
        ] as { key: AdminTab; label: string }[]).map(t => (
          <button key={t.key} onClick={() => switchTab(t.key)}
            className={`px-6 py-2 rounded-full text-sm font-semibold transition-all ${
              tab === t.key ? 'bg-[var(--tv-accent)] text-white shadow-sm' : 'text-gray-500 hover:bg-gray-50'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="p-4 rounded-2xl bg-red-50 border border-red-100 text-red-700 text-sm mb-6">{error}</div>
      )}

      {loading && (
        <div className="flex items-center gap-3 py-10 justify-center text-[var(--tv-muted)]">
          <div className="animate-spin rounded-full h-6 w-6 border-2 border-gray-200 border-t-[var(--tv-accent)]" />
          Loading…
        </div>
      )}

      {/* ── Summary ── */}
      {tab === 'summary' && !loading && summary && (
        <div className="space-y-6">
          {/* KPI cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: 'Total Events',    value: summary.total_events,    emoji: '⚡' },
              { label: 'Unique Sessions', value: summary.unique_sessions, emoji: '🖥️' },
              { label: 'Unique Testers',  value: summary.unique_users,    emoji: '👤' },
              { label: 'Feedback Items',  value: summary.total_feedback,  emoji: '💬' },
            ].map(k => (
              <div key={k.label} className="bg-white rounded-2xl p-5 tv-soft-shadow">
                <div className="text-2xl mb-1">{k.emoji}</div>
                <div className="text-2xl font-bold text-[var(--tv-text)]">{k.value.toLocaleString()}</div>
                <div className="text-xs text-[var(--tv-muted)] mt-0.5">{k.label}</div>
              </div>
            ))}
          </div>

          {/* Testers */}
          <div className="bg-white rounded-2xl p-6 tv-soft-shadow">
            <h2 className="font-bold text-[var(--tv-text)] mb-4">Testers</h2>
            {summary.users.length === 0 ? (
              <p className="text-sm text-[var(--tv-muted)]">No identified users yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--tv-muted)] border-b border-gray-100">
                    <th className="pb-2 font-semibold">Name</th>
                    <th className="pb-2 font-semibold">Email</th>
                    <th className="pb-2 font-semibold text-right">Events</th>
                    <th className="pb-2 font-semibold text-right">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.users.map(u => (
                    <tr
                      key={u.email}
                      onClick={() => { setEventUser(u.email); switchTab('events', u.email); }}
                      className="border-b border-gray-50 hover:bg-[var(--tv-accent)]/5 cursor-pointer group"
                      title={`View ${u.name ?? u.email}'s events`}
                    >
                      <td className="py-2 font-medium group-hover:text-[var(--tv-accent)] transition-colors">
                        {u.name ?? '—'} <span className="text-xs text-[var(--tv-muted)] opacity-0 group-hover:opacity-100 transition-opacity">→ view events</span>
                      </td>
                      <td className="py-2 text-[var(--tv-muted)]">{u.email}</td>
                      <td className="py-2 text-right font-mono">{u.event_count}</td>
                      <td className="py-2 text-right text-[var(--tv-muted)]">{u.last_seen ? fmt(u.last_seen) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Top events */}
          <div className="bg-white rounded-2xl p-6 tv-soft-shadow">
            <h2 className="font-bold text-[var(--tv-text)] mb-4">Top Actions</h2>
            <div className="space-y-2">
              {summary.top_events.slice(0, 15).map(e => {
                const max = summary.top_events[0]?.count ?? 1;
                return (
                  <div key={e.name} className="flex items-center gap-3">
                    <div className="flex-1 text-sm font-mono truncate text-[var(--tv-text)]">{e.name}</div>
                    <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${(e.count / max) * 100}%`, background: 'var(--tv-accent)' }} />
                    </div>
                    <div className="w-10 text-right text-sm font-bold text-[var(--tv-text)]">{e.count}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Feedback by category */}
          {summary.feedback_by_category.length > 0 && (
            <div className="bg-white rounded-2xl p-6 tv-soft-shadow">
              <h2 className="font-bold text-[var(--tv-text)] mb-4">Feedback Categories</h2>
              <div className="flex gap-3 flex-wrap">
                {summary.feedback_by_category.map(f => (
                  <div key={f.category} className={`px-4 py-2 rounded-full text-sm font-semibold ${CATEGORY_COLORS[f.category] ?? 'bg-gray-100 text-gray-700'}`}>
                    {CATEGORY_EMOJI[f.category] ?? '📌'} {f.category} — {f.count}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Events ── */}
      {tab === 'events' && !loading && (
        <div className="bg-white rounded-2xl p-6 tv-soft-shadow">
          <div className="flex gap-3 mb-4 flex-wrap">
            <input value={eventUser} onChange={e => setEventUser(e.target.value)}
              placeholder="Filter by email"
              className="px-3 py-2 rounded-xl border border-gray-200 text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)]" />
            <select value={eventType} onChange={e => setEventType(e.target.value)}
              className="px-3 py-2 rounded-xl border border-gray-200 text-sm bg-gray-50 focus:outline-none">
              <option value="">All types</option>
              <option value="action">action</option>
              <option value="page_view">page_view</option>
              <option value="api">api</option>
              <option value="error">error</option>
            </select>
            <button onClick={() => loadEvents()}
              className="px-4 py-2 rounded-full text-sm font-semibold bg-[var(--tv-accent)] text-white hover:opacity-90">
              Apply
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[var(--tv-muted)] border-b border-gray-100">
                  <th className="pb-2 font-semibold pr-4">Time</th>
                  <th className="pb-2 font-semibold pr-4">User</th>
                  <th className="pb-2 font-semibold pr-4">Type</th>
                  <th className="pb-2 font-semibold pr-4">Event</th>
                  <th className="pb-2 font-semibold">Page</th>
                </tr>
              </thead>
              <tbody>
                {events.map(e => (
                  <tr key={e.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-1.5 pr-4 text-[var(--tv-muted)] whitespace-nowrap">{fmt(e.created_at)}</td>
                    <td className="py-1.5 pr-4 text-[var(--tv-muted)] truncate max-w-[120px]">{e.user_name ?? e.user_email ?? 'anon'}</td>
                    <td className="py-1.5 pr-4">
                      <span className={`px-2 py-0.5 rounded-full font-semibold ${
                        e.event_type === 'api' ? 'bg-purple-100 text-purple-700' :
                        e.event_type === 'error' ? 'bg-red-100 text-red-700' :
                        e.event_type === 'page_view' ? 'bg-blue-100 text-blue-700' :
                        'bg-gray-100 text-gray-700'
                      }`}>{e.event_type}</span>
                    </td>
                    <td className="py-1.5 pr-4 font-mono">{e.event_name}</td>
                    <td className="py-1.5 text-[var(--tv-muted)]">{e.page ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {events.length === 0 && <p className="text-sm text-[var(--tv-muted)] mt-4">No events found.</p>}
          </div>
        </div>
      )}

      {/* ── Feedback ── */}
      {tab === 'feedback' && !loading && (
        <div className="space-y-4">
          {feedback.length === 0 && (
            <p className="text-sm text-[var(--tv-muted)]">No feedback yet.</p>
          )}
          {feedback.map(f => (
            <div key={f.id} className="bg-white rounded-2xl p-5 tv-soft-shadow">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`px-3 py-1 rounded-full text-xs font-bold ${CATEGORY_COLORS[f.category] ?? 'bg-gray-100 text-gray-700'}`}>
                    {CATEGORY_EMOJI[f.category] ?? '📌'} {f.category}
                  </span>
                  {f.rating && (
                    <span className="text-yellow-400 text-sm">{'★'.repeat(f.rating)}{'☆'.repeat(5 - f.rating)}</span>
                  )}
                  {f.page && (
                    <span className="text-xs px-2 py-0.5 bg-gray-100 rounded-full text-gray-600">{f.page}</span>
                  )}
                </div>
                <div className="text-xs text-[var(--tv-muted)] whitespace-nowrap">{fmt(f.created_at)}</div>
              </div>
              <p className="text-sm text-[var(--tv-text)] leading-relaxed mb-2">{f.message}</p>
              <div className="flex items-center gap-2 text-xs text-[var(--tv-muted)]">
                <span>👤 {f.user_name ?? 'Anonymous'}</span>
                {f.user_email && <span>· {f.user_email}</span>}
                {f.context && (
                  <span className="ml-2 font-mono bg-gray-50 px-2 py-0.5 rounded">
                    {(f.context as { symbol?: string }).symbol ?? ''} {(f.context as { strategy?: string }).strategy ?? ''}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
