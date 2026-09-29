/* ══════════════════════════════════════════════════════════════════════════
   API CLIENT + AUTH STATE
   Run the API locally first: cd Backend && source .venv/bin/activate &&
   uvicorn main:app --reload --port 8000
═══════════════════════════════════════════════════════════════════════════ */
// Local: the static HTML is opened from disk or a dev server, API on :8000.
// Deployed: FastAPI serves the frontend itself, so the API is same-origin.
import { t } from './i18n.js';

export const API_BASE = (window.location.hostname === 'localhost' ||
                         window.location.hostname === '127.0.0.1' ||
                         window.location.protocol === 'file:')
  ? 'http://127.0.0.1:8000/api'
  : '/api';

export let authToken = localStorage.getItem('nv_token') || null;
export let authUser = JSON.parse(localStorage.getItem('nv_user') || 'null');

export async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers);
  if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;

  let res;
  try {
    res = await fetch(API_BASE + path, Object.assign({}, opts, { headers }));
  } catch (err) {
    throw new Error('Backend unreachable — is uvicorn running on ' + API_BASE + '?');
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_) {
      // Non-JSON body — a proxy error page, a stack trace, etc. Surface the
      // status rather than a confusing "Unexpected token <" from JSON.parse.
      data = { detail: `Server returned ${res.status} ${res.statusText || ''}`.trim() };
    }
  }
  if (!res.ok) {
    const detail = data && data.detail;
    const msg = typeof detail === 'object' && detail !== null
      ? (detail.reason || detail.msg || JSON.stringify(detail))
      : (detail || res.statusText || `Request failed (${res.status})`);
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export function requireLogin(message) {
  if (authToken) return true;
  showToastRef(message || t('js.loginfirst'));
  setTimeout(() => navRef('login'), 600);
  return false;
}

// showToast (ui.js) and nav (nav.js) both depend on auth state, and auth state
// is depended on by nearly everything else — importing them directly here would
// create a real circular dependency at module-eval time. These setters let
// main.js wire the references once everything is loaded, instead.
let showToastRef = () => {};
let navRef = () => {};
let showHelpRef = () => {};
let refreshNotifDotRef = () => {};
let modeRefs = { official: () => {}, citizen: () => {} };
export function setUiRefs(showToastFn, navFn, modes, showHelpFn, refreshNotifDotFn) {
  showToastRef = showToastFn;
  navRef = navFn;
  if (modes) modeRefs = modes;
  if (showHelpFn) showHelpRef = showHelpFn;
  if (refreshNotifDotFn) refreshNotifDotRef = refreshNotifDotFn;
}

export function logout() {
  authToken = null;
  authUser = null;
  try { localStorage.removeItem('nv_token'); localStorage.removeItem('nv_user'); } catch (_) {}
  applyAuthUI();
}

export function storeSession(token, user) {
  authToken = token;
  authUser = user;
  localStorage.setItem('nv_token', token);
  localStorage.setItem('nv_user', JSON.stringify(user));
  applyAuthUI();
}

export function applyAuthUI() {
  const avatar = document.getElementById('avatar-btn');
  const signinBtn = document.getElementById('signin-topbtn');
  const signoutBtn = document.getElementById('signout-topbtn');
  const portalBtn = document.getElementById('official-portal-btn');
  const myPanel = document.getElementById('mycomplaints-panel');
  const guestPanel = document.getElementById('mycomplaints-panel-guest');
  const myPanelEmail = document.getElementById('mycomplaints-panel-email');
  // An official whose account hasn't been admin-approved yet has no
  // official-only access on the backend (require_official rejects them) —
  // treat them as a citizen here too, rather than opening a dashboard that
  // would just 403 on every call.
  const isOfficial = !!(authUser && authUser.role === 'official' && authUser.official_status === 'approved');
  const isPendingOfficial = !!(authUser && authUser.role === 'official' && authUser.official_status === 'pending');
  if (authUser) {
    const initials = String(authUser.name || '?').trim().split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
    avatar.textContent = initials || '?';
    avatar.onclick = () => (isOfficial ? modeRefs.official() : navRef('mycomplaints'));
    signinBtn.style.display = 'none';
    if (signoutBtn) signoutBtn.hidden = false;
  } else {
    // Guests already have a dedicated "Sign in" button in the topbar, so this
    // "?" avatar circle is repurposed as the Help & FAQ trigger instead of
    // duplicating that sign-in action.
    avatar.textContent = '?';
    avatar.title = 'Help';
    avatar.onclick = () => showHelpRef();
    signinBtn.style.display = 'inline-block';
    if (signoutBtn) signoutBtn.hidden = true;
  }
  // The "Your complaints" widget in the right panel is account-specific —
  // never show it (or a real email) to a signed-out visitor.
  if (myPanel && guestPanel) {
    myPanel.hidden = !authUser;
    guestPanel.hidden = !!authUser;
    if (authUser && myPanelEmail) myPanelEmail.textContent = authUser.email || 'your email';
  }
  const tgStatus = document.getElementById('telegram-link-status');
  const tgBtn = document.getElementById('telegram-link-btn');
  if (tgStatus && tgBtn) {
    const linked = !!(authUser && authUser.telegram_chat_id);
    tgStatus.textContent = linked ? t('panel.telegramlinked') : t('panel.telegramnotlinked');
    tgStatus.classList.toggle('linked', linked);
    tgBtn.hidden = linked;
  }
  if (portalBtn) portalBtn.hidden = !isOfficial;
  refreshNotifDotRef();
  // Officials land in their own portal; everyone else gets the citizen app.
  if (isOfficial) modeRefs.official(); else modeRefs.citizen();
}

let _tgPollTimer = null;

export async function startTelegramLink() {
  if (!authToken) { navRef('login'); return; }
  const btn = document.getElementById('telegram-link-btn');
  btn.disabled = true;
  try {
    const result = await api('/auth/telegram-link-code', { method: 'POST' });
    window.open(result.deep_link, '_blank');
    showToastRef(t('panel.telegramopened'));

    // Poll for up to a minute — the person just needs to tap "Start" in the
    // Telegram app/web client that just opened, no manual refresh needed.
    clearInterval(_tgPollTimer);
    let attempts = 0;
    _tgPollTimer = setInterval(async () => {
      attempts++;
      try {
        const me = await api('/auth/me');
        if (me.telegram_chat_id) {
          clearInterval(_tgPollTimer);
          authUser = Object.assign({}, authUser, me);
          authToken = me.access_token;
          localStorage.setItem('nv_token', authToken);
          localStorage.setItem('nv_user', JSON.stringify(authUser));
          applyAuthUI();
          showToastRef(t('panel.telegramlinkedtoast'));
        }
      } catch (_) { /* transient — keep polling until the attempt cap */ }
      if (attempts >= 20) clearInterval(_tgPollTimer); // ~60s at 3s intervals
    }, 3000);
  } catch (err) {
    showToastRef(err.message);
  } finally {
    btn.disabled = false;
  }
}
