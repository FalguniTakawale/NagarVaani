/* Corruption reports — a separate, deliberately plain section. No votes
   (this isn't a popularity contest), no score badge (urgency scoring is
   for infrastructure), no seasonal chips. Category is pinned server-side
   via ComplaintCreate.category so the classifier can't file it as "other". */
import { api, authToken, authUser } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { t } from './i18n.js';

function renderCorruptionCard(c) {
  const where = [c.location_text, c.area, c.ward ? 'Ward ' + c.ward : null, c.city].filter(Boolean).slice(0, 2).join(' · ');
  const status = c.status || 'open';
  return `
    <div class="corr-card" onclick="openComplaint('${c.id}')">
      <div class="corr-card-text">${escapeHtml(c.text_translated || c.text_original)}</div>
      <div class="corr-card-meta">
        ${where ? `<span class="corr-chip">📍 ${escapeHtml(where)}</span>` : ''}
        <span class="corr-chip">🕐 ${c.created_at ? new Date(c.created_at).toLocaleDateString() : '—'}</span>
        <span class="corr-chip status ${status}">${status.replace('_', ' ')}</span>
        ${c.comment_count ? `<span class="corr-chip">💬 ${c.comment_count}</span>` : ''}
      </div>
    </div>`;
}

export async function loadCorruptionFeed() {
  const list = document.getElementById('corruption-feed-list');
  const count = document.getElementById('corr-count');
  // Viewing corruption reports (unlike submitting one) requires an account —
  // the backend enforces this too, this just avoids a raw 401 in the feed.
  if (!authToken) {
    count.textContent = '';
    list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('corr.loginrequired')} <a style="color:var(--navy);cursor:pointer;" onclick="nav('login')">${t('top.signin')}</a></div>`;
    return;
  }
  list.innerHTML = loadingPlaceholder();
  try {
    const items = await api('/complaints?scope=corruption&sort=recent&per_page=50');
    count.textContent = items.length ? `· ${t('corr.count', { n: items.length })}` : '';
    list.innerHTML = items.length
      ? items.map(renderCorruptionCard).join('')
      : `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('corr.empty')}</div>`;
  } catch (err) {
    list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--critical);font-size:13px;">${escapeHtml(err.message)}</div>`;
  }
}

export async function submitCorruption() {
  const text = document.getElementById('corr-text').value.trim();
  if (!text) { showToast(t('corr.describe')); return; }
  const btn = document.getElementById('corr-submit-btn');
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = t('js.reviewing');
  try {
    const payload = {
      text,
      category: 'corruption',
      anonymous: document.getElementById('corr-anon').checked,
      location_text: document.getElementById('corr-location').value.trim() || null,
      ward: authUser ? authUser.ward : null,
      city: authUser ? authUser.city : null,
      state: authUser ? authUser.state : null,
    };
    await api('/complaints', { method: 'POST', body: JSON.stringify(payload) });
    showToast(t('corr.submitted'));
    document.getElementById('corr-text').value = '';
    document.getElementById('corr-location').value = '';
    loadCorruptionFeed();
  } catch (err) {
    if (err.status === 422 && err.data && err.data.detail && err.data.detail.rejected) {
      const d = err.data.detail;
      showToast(`Rejected: ${d.reason}${d.suggested_rephrasing ? ' — try: "' + d.suggested_rephrasing + '"' : ''}`);
    } else if (err.status === 429) {
      showToast('Too many submissions from your connection — try again in a while');
    } else {
      showToast(err.message);
    }
  } finally {
    btn.disabled = false;
    btn.textContent = t('corr.submit');
  }
}
