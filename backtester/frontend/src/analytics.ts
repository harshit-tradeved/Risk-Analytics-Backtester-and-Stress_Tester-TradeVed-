import { trackEvents, TrackEventPayload } from './api';

const SESSION_KEY  = 'tv_session_id';
const NAME_KEY     = 'tv_user_name';
const EMAIL_KEY    = 'tv_user_email';
const ADMIN_KEY    = 'tv_admin_token';
const FLUSH_MS     = 5_000;
const BATCH_SIZE   = 10;

function generateId(): string {
  return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function getSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = generateId();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

export function getIdentity(): { name: string | null; email: string | null } {
  return {
    name:  localStorage.getItem(NAME_KEY),
    email: localStorage.getItem(EMAIL_KEY),
  };
}

export function setIdentity(name: string, email: string): void {
  localStorage.setItem(NAME_KEY, name);
  localStorage.setItem(EMAIL_KEY, email);
}

export function getAdminToken(): string | null {
  return localStorage.getItem(ADMIN_KEY);
}

export function setAdminToken(token: string): void {
  localStorage.setItem(ADMIN_KEY, token);
}

// ── Event queue ──────────────────────────────────────────────────────────────

let _queue: TrackEventPayload[] = [];
let _flushTimer: ReturnType<typeof setTimeout> | null = null;

function _flush(): void {
  if (_queue.length === 0) return;
  const batch = _queue.splice(0, _queue.length);
  trackEvents(batch);
}

function _scheduleFlush(): void {
  if (_flushTimer) return;
  _flushTimer = setTimeout(() => {
    _flushTimer = null;
    _flush();
  }, FLUSH_MS);
}

// Flush on tab close/hide via sendBeacon
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') _flush();
  });
}

export function track(
  eventName: string,
  props?: Record<string, unknown>,
  eventType: string = 'action',
  page?: string,
): void {
  const { name, email } = getIdentity();
  _queue.push({
    session_id: getSessionId(),
    user_name:  name ?? undefined,
    user_email: email ?? undefined,
    event_type: eventType,
    event_name: eventName,
    page,
    props,
    user_agent: navigator.userAgent,
  });
  if (_queue.length >= BATCH_SIZE) {
    if (_flushTimer) { clearTimeout(_flushTimer); _flushTimer = null; }
    _flush();
  } else {
    _scheduleFlush();
  }
}

export function trackPageView(page: string): void {
  track('page_view', { page }, 'page_view', page);
}
