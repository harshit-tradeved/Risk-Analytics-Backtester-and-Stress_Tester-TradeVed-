import { useState } from 'react';
import { setIdentity, track } from '../../analytics';

interface Props {
  onIdentified: () => void;
}

export default function IdentityGate({ onIdentified }: Props) {
  const [name,  setName]  = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim())  { setError('Please enter your name.');  return; }
    if (!email.trim() || !email.includes('@')) { setError('Please enter a valid email.'); return; }
    setIdentity(name.trim(), email.trim().toLowerCase());
    track('identify', { name: name.trim(), email: email.trim().toLowerCase() });
    onIdentified();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-3xl shadow-2xl p-8 w-full max-w-sm mx-4 fade-in">
        {/* Logo */}
        <div className="flex items-center gap-2 mb-6">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl font-black text-sm text-white"
               style={{ background: 'var(--tv-accent)' }}>
            TV
          </div>
          <span className="text-xl font-bold text-[var(--tv-text)]">TradeVed</span>
        </div>

        <h2 className="text-lg font-bold text-[var(--tv-text)] mb-1">Welcome, tester!</h2>
        <p className="text-sm text-[var(--tv-muted)] mb-5">
          This is an internal test build. Please enter your details so we can attribute your feedback.
          <br /><span className="text-xs opacity-70 mt-1 block">Your usage and feedback are recorded to help improve the product.</span>
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-[var(--tv-muted)] mb-1">Your name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Harshit Kumar"
              className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)] bg-gray-50"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-[var(--tv-muted)] mb-1">Work email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full px-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--tv-accent)] bg-gray-50"
            />
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button
            type="submit"
            className="w-full py-3 rounded-full font-bold text-sm text-white transition-all hover:-translate-y-0.5 hover:shadow-md"
            style={{ background: 'var(--tv-accent)' }}
          >
            Let me in
          </button>
        </form>
      </div>
    </div>
  );
}
