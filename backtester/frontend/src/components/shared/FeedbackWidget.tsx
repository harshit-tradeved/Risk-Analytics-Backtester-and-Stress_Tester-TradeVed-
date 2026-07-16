import { useState } from 'react';
import { submitFeedback } from '../../api';
import { getSessionId, getIdentity, track } from '../../analytics';

type Category = 'bug' | 'idea' | 'praise' | 'other';

interface Props {
  page: string;
  context?: Record<string, unknown>;
}

const CATEGORIES: { key: Category; label: string; emoji: string }[] = [
  { key: 'bug',    label: 'Bug',   emoji: '🐞' },
  { key: 'idea',   label: 'Idea',  emoji: '💡' },
  { key: 'praise', label: 'Praise', emoji: '👍' },
  { key: 'other',  label: 'Other',  emoji: '💬' },
];

export default function FeedbackWidget({ page, context }: Props) {
  const [open,     setOpen]     = useState(false);
  const [category, setCategory] = useState<Category>('idea');
  const [rating,   setRating]   = useState<number | null>(null);
  const [message,  setMessage]  = useState('');
  const [status,   setStatus]   = useState<'idle' | 'sending' | 'done' | 'error'>('idle');

  const openWidget = () => {
    track('feedback_open', { page });
    setOpen(true);
    setStatus('idle');
    setMessage('');
    setRating(null);
    setCategory('idea');
  };

  const close = () => setOpen(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;
    setStatus('sending');
    try {
      const { name, email } = getIdentity();
      await submitFeedback({
        session_id: getSessionId(),
        user_name:  name ?? undefined,
        user_email: email ?? undefined,
        category,
        rating:     rating ?? undefined,
        message:    message.trim(),
        page,
        context,
      });
      track('feedback_submitted', { category, rating, page });
      setStatus('done');
    } catch {
      setStatus('error');
    }
  };

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={openWidget}
        title="Send feedback"
        className="fixed bottom-6 right-6 z-40 w-12 h-12 rounded-full shadow-lg flex items-center justify-center text-white text-xl transition-all hover:-translate-y-0.5 hover:shadow-xl"
        style={{ background: 'var(--tv-accent)' }}
      >
        💬
      </button>

      {/* Modal */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:justify-end p-4 sm:p-6 pointer-events-none">
          <div className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-sm pointer-events-auto fade-in mb-16 sm:mb-0">
            {status === 'done' ? (
              <div className="text-center py-4">
                <div className="text-4xl mb-3">🎉</div>
                <h3 className="text-lg font-bold text-[var(--tv-text)]">Thanks for the feedback!</h3>
                <p className="text-sm text-[var(--tv-muted)] mt-1 mb-4">Your input helps improve TradeVed.</p>
                <button onClick={close}
                  className="px-6 py-2 rounded-full text-sm font-semibold bg-gray-100 text-[var(--tv-text)] hover:bg-gray-200">
                  Close
                </button>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-bold text-[var(--tv-text)]">Send feedback</h3>
                  <button onClick={close} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                  {/* Category pills */}
                  <div className="flex gap-2 flex-wrap">
                    {CATEGORIES.map(c => (
                      <button
                        key={c.key}
                        type="button"
                        onClick={() => setCategory(c.key)}
                        className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all border ${
                          category === c.key
                            ? 'border-[var(--tv-accent)] text-[var(--tv-accent)] bg-lime-50'
                            : 'border-gray-200 text-gray-500 hover:border-gray-300'
                        }`}
                      >
                        {c.emoji} {c.label}
                      </button>
                    ))}
                  </div>

                  {/* Star rating */}
                  <div>
                    <p className="text-xs text-[var(--tv-muted)] mb-1">Rating (optional)</p>
                    <div className="flex gap-1">
                      {[1, 2, 3, 4, 5].map(n => (
                        <button
                          key={n}
                          type="button"
                          onClick={() => setRating(rating === n ? null : n)}
                          className={`text-xl transition-all ${n <= (rating ?? 0) ? 'text-yellow-400' : 'text-gray-300 hover:text-yellow-300'}`}
                        >
                          ★
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Message */}
                  <div>
                    <textarea
                      value={message}
                      onChange={e => setMessage(e.target.value)}
                      placeholder="What's on your mind?"
                      rows={3}
                      required
                      className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)] bg-gray-50"
                    />
                  </div>

                  {status === 'error' && (
                    <p className="text-xs text-red-500">Failed to send. Please try again.</p>
                  )}

                  <button
                    type="submit"
                    disabled={status === 'sending' || !message.trim()}
                    className="w-full py-2.5 rounded-full font-bold text-sm text-white disabled:opacity-50 transition-all hover:-translate-y-0.5"
                    style={{ background: 'var(--tv-accent)' }}
                  >
                    {status === 'sending' ? 'Sending…' : 'Submit feedback'}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
