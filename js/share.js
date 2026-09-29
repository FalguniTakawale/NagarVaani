/* Share + Flag dialogs for the complaint detail page.
   Share: real Web Share API where the device has it, plus copy-link and
   direct WhatsApp / Telegram / X / Facebook / Email intents — no third-party
   SDKs, no tracking.
   Flag: a signed-in citizen reports the post (spam, misleading, ...). It is
   stored server-side (POST /complaints/{id}/flag) and shows up in the official
   portal's "Citizen reports" queue. Nothing is hidden automatically. */
import { api, requireLogin } from './api.js';
import { currentComplaintId } from './nav.js';
import { showToast, escapeHtml } from './ui.js';
import { t } from './i18n.js';

export function complaintShareUrl(id) {
  // Deep link handled in main.js: #complaint/<id> opens that complaint.
  return `${location.origin}${location.pathname}#complaint/${encodeURIComponent(id)}`;
}

function shareTitle() {
  const el = document.getElementById('detail-title');
  const txt = (el && el.textContent || '').trim();
  return txt ? `NagarVaani: ${txt.slice(0, 110)}` : 'A civic issue on NagarVaani';
}

function openOverlay(id) { document.getElementById(id).hidden = false; }
export function closeOverlay(id) { const el = document.getElementById(id); if (el) el.hidden = true; }

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove();
    return ok;
  }
}

/* ── SHARE ── */
export function openShare() {
  if (!currentComplaintId) return;
  const url = complaintShareUrl(currentComplaintId);
  const title = shareTitle();
  const text = encodeURIComponent(`${title}\n${url}`);
  const u = encodeURIComponent(url);
  document.getElementById('share-url').value = url;
  document.getElementById('share-native-btn').hidden = !navigator.share;
  document.getElementById('share-targets').innerHTML = [
    ['WhatsApp', '💬', `https://wa.me/?text=${text}`],
    ['Telegram', '✈️', `https://t.me/share/url?url=${u}&text=${encodeURIComponent(title)}`],
    ['X / Twitter', '𝕏', `https://twitter.com/intent/tweet?text=${encodeURIComponent(title)}&url=${u}`],
    ['Facebook', 'f', `https://www.facebook.com/sharer/sharer.php?u=${u}`],
    ['Email', '✉️', `mailto:?subject=${encodeURIComponent(title)}&body=${text}`],
  ].map(([name, icon, href]) =>
    `<a class="share-target" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer"><span class="share-target-icon">${icon}</span>${name}</a>`
  ).join('');
  openOverlay('share-overlay');
}

export async function shareNative() {
  if (!currentComplaintId || !navigator.share) return;
  try {
    await navigator.share({ title: shareTitle(), text: shareTitle(), url: complaintShareUrl(currentComplaintId) });
  } catch (err) {
    if (err && err.name !== 'AbortError') showToast(t('share.failed'));
  }
}

export async function copyShareLink() {
  const ok = await copyText(document.getElementById('share-url').value);
  showToast(ok ? t('share.copied') : t('share.copyfailed'));
}

/* ── FLAG ── */
export function openFlag() {
  if (!currentComplaintId) return;
  if (!requireLogin(t('flag.loginfirst'))) return;
  document.getElementById('flag-note').value = '';
  const first = document.querySelector('input[name="flag-reason"]');
  if (first) first.checked = true;
  document.getElementById('flag-error').textContent = '';
  openOverlay('flag-overlay');
}

export async function submitFlag() {
  const reason = (document.querySelector('input[name="flag-reason"]:checked') || {}).value;
  const note = document.getElementById('flag-note').value.trim();
  const btn = document.getElementById('flag-submit-btn');
  const err = document.getElementById('flag-error');
  if (!reason) { err.textContent = t('flag.pick'); return; }
  btn.disabled = true; err.textContent = '';
  try {
    await api(`/complaints/${currentComplaintId}/flag`, { method: 'POST', body: JSON.stringify({ reason, note: note || null }) });
    closeOverlay('flag-overlay');
    showToast(t('flag.done'));
  } catch (e) {
    err.textContent = e.message;   // e.g. "You've already reported this complaint"
  } finally {
    btn.disabled = false;
  }
}
