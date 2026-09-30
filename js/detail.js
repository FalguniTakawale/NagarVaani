import { api, authUser, requireLogin } from './api.js';
import { showToast, escapeHtml } from './ui.js';
import { currentComplaintId } from './nav.js';
import { CATEGORY_LABELS, scoreBadgeClass, loadFeed } from './feed.js';
import { t, currentLang } from './i18n.js';

const LANG_NAMES = { en: 'English', hi: 'Hindi', mr: 'Marathi', ta: 'Tamil', te: 'Telugu', kn: 'Kannada', gu: 'Gujarati', bn: 'Bengali', pa: 'Punjabi', ur: 'Urdu', ml: 'Malayalam', or: 'Odia', as: 'Assamese' };
const langName = (code) => LANG_NAMES[(code || '').toLowerCase()] || (code ? code.toUpperCase() : 'original');

// Per-complaint cache so toggling Hide/Show doesn't re-hit Claude.
let complaintTranslation = null; // { id, target, translated, from }
const commentTexts = {};         // comment id -> original text (for the inline Translate link)

export async function doVote() {
  if (!currentComplaintId) return;
  if (!requireLogin(t('js.logintovote'))) return;
  try {
    const result = await api(`/complaints/${currentComplaintId}/vote`, { method: 'POST', body: JSON.stringify({}) });
    document.getElementById('vote-num').textContent = result.new_vote_count;
    document.getElementById('sidebar-votes').textContent = result.new_vote_count;
    document.getElementById('vote-btn').style.background = 'var(--saffron)';
    showToast(t('js.voted', { score: result.new_score }));
  } catch (err) {
    showToast(err.message);
  }
}

export async function doSameIssue() {
  if (!currentComplaintId) return;
  const areaName = (authUser && authUser.area) || prompt('Which area are you reporting this from?');
  if (!areaName) return;
  try {
    const result = await api(`/complaints/${currentComplaintId}/link-area`, {
      method: 'POST', body: JSON.stringify({ area_name: areaName }),
    });
    document.getElementById('linked-badge').textContent = result.new_linked_count + ' areas';
    document.getElementById('sidebar-linked').textContent = result.new_linked_count;
    showToast(`Your area linked — new score ${result.new_score}`);
  } catch (err) {
    showToast(err.message);
  }
}

export async function doDispute(id = currentComplaintId) {
  if (!id) return;
  if (!requireLogin('Log in to dispute a resolution')) return;
  const note = prompt('What still needs fixing? (optional — helps the official who reopens this)') || '';
  try {
    const result = await api(`/complaints/${id}/dispute`, {
      method: 'POST', body: JSON.stringify({ note }),
    });
    showToast(`Disputed — status now "${result.new_status}". Officials notified.`);
    const onDetail = document.getElementById('page-detail').classList.contains('active');
    if (onDetail) loadComplaintDetail(id); else loadFeed('mycomplaints');
  } catch (err) {
    showToast(err.message);
  }
}

// The compose-box avatar used to be a hardcoded "FT" in the markup — always
// showed whoever built the page's initials, regardless of who was actually
// signed in (or signed in as, e.g. the ramesh@test.com demo account). Same
// initials logic as the topbar avatar in api.js's applyAuthUI().
function updateCommentComposeAvatar() {
  const el = document.getElementById('comment-compose-avatar');
  if (!el) return;
  if (!authUser) { el.textContent = '?'; return; }
  el.textContent = String(authUser.name || '?').trim().split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
}

export async function postComment() {
  if (!currentComplaintId) return;
  const input = document.getElementById('comment-input');
  const text = input.value.trim();
  if (!text) { showToast('Write something first'); return; }
  try {
    const result = await api(`/complaints/${currentComplaintId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ text, author_name: authUser ? authUser.name : 'Anonymous', author_area: authUser ? authUser.area : null }),
    });
    input.value = '';
    showToast(result.message);
    loadComplaintDetail(currentComplaintId); // refresh comment list + linked areas
  } catch (err) {
    showToast(err.message);
  }
}

export async function doTranslate() {
  if (!currentComplaintId) return;
  const btn = document.getElementById('translate-btn');
  const box = document.getElementById('translate-result');
  const target = currentLang();

  // Toggle if we already have this translation.
  if (complaintTranslation && complaintTranslation.id === currentComplaintId && complaintTranslation.target === target) {
    box.hidden = !box.hidden;
    btn.textContent = box.hidden ? t('detail.showtranslation') : t('detail.hidetranslation');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span class="translate-spinner"></span>${t('detail.translating')}`;
  try {
    const result = await api(`/complaints/${currentComplaintId}/translate`, {
      method: 'POST', body: JSON.stringify({ target_language: target }),
    });
    complaintTranslation = { id: currentComplaintId, target, translated: result.translated, from: result.detected_language };
    document.getElementById('translate-from').textContent = t('detail.translatedfrom', { lang: langName(result.detected_language) }) + (result.romanized ? ' (written in English letters)' : '');
    document.getElementById('translate-translated').textContent = result.translated;
    box.hidden = false;
    btn.textContent = t('detail.hidetranslation');
  } catch (err) {
    btn.textContent = t('detail.translate');
    showToast(err.message);
  } finally {
    btn.disabled = false;
  }
}

export async function translateComment(id, link) {
  const holder = document.getElementById('ct-' + id);
  if (!holder) return;
  if (holder.dataset.loaded === '1') { // toggle
    holder.hidden = !holder.hidden;
    link.textContent = holder.hidden ? t('comment.translate') : t('comment.hide');
    return;
  }
  link.innerHTML = `<span class="translate-spinner"></span>${t('detail.translating')}`;
  try {
    const result = await api('/translate', {
      method: 'POST', body: JSON.stringify({ text: commentTexts[id] || '', target_language: currentLang() }),
    });
    holder.innerHTML = `<div class="translate-from">${t('detail.translatedfrom', { lang: langName(result.detected_language) })}</div>${escapeHtml(result.translated)}`;
    holder.dataset.loaded = '1';
    holder.hidden = false;
    link.textContent = t('comment.hide');
  } catch (err) {
    link.textContent = t('comment.translate');
    showToast(err.message);
  }
}

/* ── COMPLAINT DETAIL ── */
// Severity (L1+L3+L4+L5) decides ranking; the seasonal multiplier amplifies it;
// the vote multiplier is applied last as a gentle nudge that can never invert
// a severity-based ranking — matches score_complaint() in ai_engine.py.
const BREAKDOWN_ADDITIVE = {
  l1_safety: ['L1', 'lv1', 'Immediate safety risk'],
  l3_type_weight: ['L3', 'lv3', 'Problem type base weight'],
  l4_population: ['L4', 'lv3', 'Population density adjustment'],
  l5_pattern_bonus: ['L5', 'lv5', 'Cross-district pattern bonus'],
};

function renderBreakdown(breakdown) {
  if (!breakdown) return '';
  const max = Math.max(...Object.keys(BREAKDOWN_ADDITIVE).map(k => breakdown[k] || 0), 1);
  const rows = Object.entries(BREAKDOWN_ADDITIVE).map(([key, [level, cls, label]]) => {
    const value = breakdown[key];
    if (value === undefined) return '';
    const pct = Math.min(100, (value / max) * 100);
    return `<div class="breakdown-row">
      <span class="breakdown-level ${cls}">${level}</span>
      <span class="breakdown-factor">${label}</span>
      <div class="breakdown-bar-wrap"><div class="breakdown-bar" style="width:${pct}%;background:var(--navy)"></div></div>
      <span class="breakdown-value">+${value}</span>
    </div>`;
  }).join('');

  const seasonRow = breakdown.l2_seasonal_multiplier !== undefined ? `<div class="breakdown-row">
      <span class="breakdown-level lv2">L2</span>
      <span class="breakdown-factor">${breakdown.l2_season || 'season'} amplifier on severity (${breakdown.severity_subtotal ?? '?'} → ${breakdown.severity_after_season ?? '?'})</span>
      <div class="breakdown-bar-wrap"><div class="breakdown-bar" style="width:100%;background:var(--warn)"></div></div>
      <span class="breakdown-value">×${breakdown.l2_seasonal_multiplier}</span>
    </div>` : '';

  const voteRow = breakdown.vote_multiplier !== undefined ? `<div class="breakdown-row">
      <span class="breakdown-level lv6">Votes</span>
      <span class="breakdown-factor">${breakdown.vote_count ?? 0} votes — gentle nudge, weakest signal, cannot flip severity ranking</span>
      <div class="breakdown-bar-wrap"><div class="breakdown-bar" style="width:${Math.min(100,(breakdown.vote_multiplier-1)*500)}%;background:var(--slate-light)"></div></div>
      <span class="breakdown-value">×${breakdown.vote_multiplier}</span>
    </div>` : '';

  return rows + seasonRow + voteRow;
}

export async function loadComplaintDetail(id) {
  document.getElementById('detail-title').textContent = 'Loading…';
  document.getElementById('detail-chips').innerHTML = '';
  document.getElementById('detail-meta').innerHTML = '';
  updateCommentComposeAvatar();
  try {
    const c = await api(`/complaints/${id}`);
    const isCritical = c.is_safety_risk || c.priority_score >= 80;
    document.querySelector('#page-detail .detail-hero').classList.toggle('critical', isCritical);
    const scorePanel = document.querySelector('#page-detail .score-panel');
    const scoreNumEl = document.getElementById('detail-score-num');
    const tone = isCritical
      ? { bg: 'var(--critical-bg)', border: '#FECACA', fg: 'var(--critical)' }
      : c.priority_score >= 55
        ? { bg: 'var(--warn-bg)', border: '#FDE68A', fg: 'var(--warn)' }
        : { bg: 'var(--success-bg)', border: '#BBF7D0', fg: 'var(--success)' };
    scorePanel.style.background = tone.bg;
    scorePanel.style.borderColor = tone.border;
    scoreNumEl.style.color = tone.fg;
    document.getElementById('sidebar-score').style.color = tone.fg;

    document.getElementById('detail-title').textContent = c.text_translated || c.text_original;
    document.getElementById('detail-chips').innerHTML = `
      <span class="chip chip-type">${CATEGORY_LABELS[c.category] || 'Other'}</span>
      ${c.ward ? `<span class="chip chip-loc">Ward ${c.ward}</span>` : ''}
      ${c.city ? `<span class="chip chip-loc">${escapeHtml(c.city)}</span>` : ''}
      ${c.is_safety_risk ? `<span class="chip chip-critical">Safety risk</span>` : ''}`;
    document.getElementById('detail-meta').innerHTML = `
      <div class="detail-meta-item">🕐 ${new Date(c.created_at).toLocaleDateString()}</div>
      <div class="detail-meta-item">📍 ${escapeHtml(c.location_text || c.area || c.city || 'Unknown location')}</div>
      <div class="detail-meta-item">🌐 ${(c.detected_language || 'en').toUpperCase()}</div>`;

    document.getElementById('detail-score-num').textContent = Math.round(c.priority_score);
    document.getElementById('detail-score-rank').textContent = c.status;
    document.getElementById('sidebar-score').textContent = Math.round(c.priority_score);
    document.getElementById('breakdown-title').textContent = `Why this scores ${Math.round(c.priority_score)} — AI score breakdown`;
    document.getElementById('breakdown-rows').innerHTML = renderBreakdown(c.score_breakdown);
    document.getElementById('breakdown-note').textContent = 'Votes are L6 — the weakest signal. Safety risk, season, and cross-district patterns dominate the score.';

    document.getElementById('translate-original-text').textContent = c.text_original;
    const tBtn = document.getElementById('translate-btn');
    const tBox = document.getElementById('translate-result');
    if (complaintTranslation && complaintTranslation.id === id && complaintTranslation.target === currentLang()) {
      // Re-render after a vote/comment: keep the translation the user already opened.
      document.getElementById('translate-from').textContent = t('detail.translatedfrom', { lang: langName(complaintTranslation.from) });
      document.getElementById('translate-translated').textContent = complaintTranslation.translated;
      tBox.hidden = false; tBtn.textContent = t('detail.hidetranslation');
    } else {
      tBox.hidden = true; tBtn.textContent = t('detail.translate');
    }

    document.getElementById('vote-num').textContent = c.vote_count;
    document.getElementById('sidebar-votes').textContent = c.vote_count;
    document.getElementById('sidebar-linked').textContent = c.linked_area_count;
    document.getElementById('linked-badge').textContent = c.linked_area_count + ' areas';

    const gallery = document.getElementById('gallery-grid');
    const images = c.image_urls || [];
    document.getElementById('gallery-title').textContent = `Photos & evidence — ${images.length} file${images.length === 1 ? '' : 's'}`;
    // Whole section (header included) disappears when there are no images.
    document.getElementById('gallery-section').style.display = images.length ? 'block' : 'none';
    gallery.innerHTML = images.map(img => {
      // Only http(s) URLs; opened via a data attribute (not inline JS) so a quote in the URL can't break out.
      const rawUrl = /^https?:\/\//i.test(img.url || '') ? img.url : '';
      const url = escapeHtml(rawUrl);
      const alt = escapeHtml(img.caption || 'Complaint photo');
      return `
      <div class="gallery-item">
        <div class="gallery-thumb" data-url="${url}" onclick="window.open(this.dataset.url,'_blank','noopener,noreferrer')">
          <img src="${url}" loading="lazy" alt="${alt}" style="width:100%;height:100%;object-fit:cover;"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
          <div style="display:none;width:100%;height:100%;align-items:center;justify-content:center;flex-direction:column;gap:4px;font-size:12px;color:var(--slate);">📷<span>Image unavailable</span></div>
          ${img.is_360 ? '<div class="gallery-360-badge">360°</div>' : ''}
        </div>
        <div class="gallery-caption"><div class="gallery-caption-label">Caption</div>${escapeHtml(img.caption || '')}</div>
      </div>`;
    }).join('');

    const linkedItems = document.getElementById('linked-items');
    linkedItems.innerHTML = (c.linked_areas || []).map(la => `
      <div class="linked-item">
        <div class="linked-item-left"><div class="linked-dot"></div><div><div class="linked-name">${escapeHtml(la.area_name)}</div><div class="linked-how">${la.complaint_count} complaint(s)</div></div></div>
        <span class="linked-tag ${la.link_type === 'nlp' ? 'nlp' : 'btn-linked'}">${la.link_type === 'nlp' ? 'NLP detected' : 'Button linked'}</span>
      </div>`).join('') || `<div style="font-size:12px;color:var(--slate);">No linked areas yet.</div>`;

    document.getElementById('comment-count-label').textContent = c.comment_count + ' comments';
    document.getElementById('sidebar-comments').textContent = c.comment_count;
    (c.comments || []).forEach(cm => { commentTexts[cm.id] = cm.text; });
    document.getElementById('comments-list').innerHTML = (c.comments || []).map(cm => `
      <div class="comment">
        <div class="comment-avatar" style="background:var(--navy)">${(cm.author_name || 'A').slice(0,2).toUpperCase()}</div>
        <div class="comment-bubble">
          <div class="comment-top"><span class="comment-author">${escapeHtml(cm.author_name || 'Anonymous')}</span>${cm.author_area ? `<span class="comment-location-tag">${escapeHtml(cm.author_area)}</span>` : ''}<span class="comment-time">${new Date(cm.created_at).toLocaleDateString()}<a class="comment-translate" onclick="translateComment('${cm.id}', this)">${t('comment.translate')}</a><a class="comment-translate speak-btn" data-speak="comment" title="Read aloud" role="button" aria-label="Read this comment aloud">🔊</a></span></div>
          <div class="comment-text">${escapeHtml(cm.text)}</div>
          <div class="comment-translation" id="ct-${cm.id}" hidden></div>
          ${cm.detected_places && cm.detected_places.length ? `<div class="comment-nlp-tag">🔍 AI detected "${cm.detected_places.join('", "')}" → auto-linked</div>` : ''}
        </div>
      </div>`).join('') || `<div style="font-size:12px;color:var(--slate);">No comments yet — be the first to add context.</div>`;

    const statusTrack = document.getElementById('status-track');
    const steps = ['open', 'in_progress', 'resolved'];
    const currentIdx = steps.indexOf(c.status);
    statusTrack.innerHTML = steps.map((s, i) => `
      <div class="status-step">
        <div class="status-line-col"><div class="status-circle ${i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'pending'}">${i < currentIdx ? '✓' : i === currentIdx ? '↻' : '◌'}</div>${i < steps.length - 1 ? `<div class="status-vline ${i < currentIdx ? 'done' : ''}"></div>` : ''}</div>
        <div class="status-content"><div class="status-name">${s.replace('_', ' ')}</div></div>
      </div>`).join('') + (c.status === 'disputed' ? `
      <div class="status-step">
        <div class="status-line-col"><div class="status-circle active">⚑</div></div>
        <div class="status-content"><div class="status-name">disputed</div><div class="status-desc">Reopened by the complainant — not actually fixed</div></div>
      </div>` : '');

    // Only the original complainant can dispute, and only once it's marked resolved —
    // the backend enforces both; this just avoids showing a button that will 403/400.
    const disputeBtn = document.getElementById('dispute-btn');
    const isAuthor = !!c.is_author;
    disputeBtn.style.display = (c.status === 'resolved' && isAuthor) ? 'flex' : 'none';

    document.getElementById('govt-response-section').style.display = c.official_brief ? 'block' : 'none';
    document.getElementById('govt-response-text').textContent = c.official_brief || '';
    document.getElementById('infra-flag-section').style.display = c.recommended_action ? 'block' : 'none';
    document.getElementById('infra-flag-text').textContent = c.recommended_action || '';

    loadRelatedComplaints(id);
  } catch (err) {
    document.getElementById('detail-title').textContent = "Couldn't load this complaint";
    document.getElementById('detail-meta').innerHTML = `<div class="detail-meta-item" style="color:var(--critical)">${escapeHtml(err.message)}</div>`;
    showToast(err.message);
  }
}

function statusPill(st) {
  const label = { open: 'Open', in_progress: 'In progress', resolved: 'Resolved', disputed: 'Disputed', rejected: 'Rejected' }[st] || st;
  const color = st === 'resolved' ? 'var(--success)' : st === 'disputed' ? 'var(--critical)' : 'var(--slate)';
  return `<span style="font-size:11px;font-weight:600;color:${color};margin-left:6px;">${escapeHtml(label)}</span>`;
}

function relatedRow(c) {
  const where = [c.ward ? `Ward ${c.ward}` : '', c.city || '', c.state || ''].filter(Boolean).join(', ');
  return `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);cursor:pointer;" onclick="openComplaint('${escapeHtml(c.id)}')">
    <span>${escapeHtml(c.text)}${where ? ` <span style="color:var(--slate-light);">· ${escapeHtml(where)}</span>` : ''}${statusPill(c.status)}</span>
    <span class="score-badge ${scoreBadgeClass(c.priority_score)}" style="min-width:auto;">Score ${Math.round(c.priority_score)}</span>
  </div>`;
}

async function loadRelatedComplaints(id) {
  const section = document.getElementById('related-section');
  try {
    const related = await api(`/complaints/${id}/related`);
    const { similar_in_area: sim, cross_pattern: cross, elsewhere = [], summary } = related;
    if (!sim.length && !cross.length && !elsewhere.length) {
      section.style.display = 'none';
      return;
    }
    section.style.display = 'block';
    const c = summary && summary.in_city;
    document.getElementById('related-summary').innerHTML = summary
      ? `${c ? `In <b>${escapeHtml(summary.city)}</b>: ${c.total} report(s) of this kind of problem — <b>${c.resolved}</b> resolved, <b>${c.unresolved}</b> still unresolved. ` : ''}Nationwide: ${summary.nationwide.total} reported, ${summary.nationwide.resolved} resolved.`
      : '';
    document.getElementById('related-similar').innerHTML = sim.length
      ? sim.map(relatedRow).join('')
      : 'No other reports of this kind in your city yet.';
    document.getElementById('related-cross').innerHTML = cross.length
      ? cross.map(relatedRow).join('')
      : 'No cross-pattern matches yet — link an area to surface these.';
    document.getElementById('related-elsewhere').innerHTML = elsewhere.length
      ? elsewhere.map(relatedRow).join('')
      : 'No reports of this kind from other cities yet.';
  } catch (err) {
    section.style.display = 'none';
  }
}



/* ── SHARE ── */
function closeModal() { const m = document.getElementById('nv-modal-back'); if (m) m.remove(); }
function openModal(html) {
  closeModal();
  const back = document.createElement('div');
  back.className = 'nv-modal-back'; back.id = 'nv-modal-back';
  back.innerHTML = `<div class="nv-modal" role="dialog" aria-modal="true">${html}</div>`;
  back.addEventListener('click', (e) => { if (e.target === back) closeModal(); });
  document.body.appendChild(back);
}
window.closeNvModal = closeModal;

export async function shareComplaint() {
  if (!currentComplaintId) return;
  const url = `${location.origin}${location.pathname}#detail/${encodeURIComponent(currentComplaintId)}`;
  const title = (document.getElementById('detail-title').textContent || 'Civic issue').slice(0, 120);
  const text = `NagarVaani — ${title}`;
  // Native share sheet on phones (WhatsApp, Messages, etc. appear automatically).
  if (navigator.share) {
    try { await navigator.share({ title: 'NagarVaani', text, url }); return; }
    catch (e) { if (e && e.name === 'AbortError') return; }
  }
  const e = encodeURIComponent;
  openModal(`<h3>Share this issue</h3><div class="sub">${escapeHtml(url)}</div>
    <div class="nv-share-grid">
      <a target="_blank" rel="noopener noreferrer" href="https://wa.me/?text=${e(text + ' ' + url)}">WhatsApp</a>
      <a target="_blank" rel="noopener noreferrer" href="https://t.me/share/url?url=${e(url)}&text=${e(text)}">Telegram</a>
      <a target="_blank" rel="noopener noreferrer" href="https://twitter.com/intent/tweet?text=${e(text)}&url=${e(url)}">X / Twitter</a>
      <a target="_blank" rel="noopener noreferrer" href="https://www.facebook.com/sharer/sharer.php?u=${e(url)}">Facebook</a>
      <a href="mailto:?subject=${e(text)}&body=${e(url)}">Email</a>
      <button type="button" id="nv-copy-link">Copy link</button>
    </div>
    <button class="nv-btn" onclick="closeNvModal()">Close</button>`);
  document.getElementById('nv-copy-link').onclick = async () => {
    try { await navigator.clipboard.writeText(url); showToast('Link copied'); closeModal(); }
    catch { prompt('Copy this link:', url); }
  };
}

/* ── FLAG (citizen report → admin moderation queue) ── */
export function flagComplaint() {
  if (!currentComplaintId) return;
  openModal(`<h3>Flag this complaint</h3><div class="sub">Sends it to a moderator for review. It stays visible until reviewed.</div>
    <select id="flag-reason">
      <option value="spam">Spam / advertisement</option>
      <option value="fake">Fake or false report</option>
      <option value="abusive">Abusive or hateful</option>
      <option value="duplicate">Duplicate of another complaint</option>
      <option value="other">Something else</option>
    </select>
    <textarea id="flag-note" rows="2" maxlength="500" placeholder="Optional details"></textarea>
    <div class="nv-share-grid"><button class="nv-btn" onclick="closeNvModal()">Cancel</button><button class="nv-btn primary" id="flag-submit">Submit flag</button></div>`);
  document.getElementById('flag-submit').onclick = async () => {
    try {
      const r = await api(`/complaints/${currentComplaintId}/report`, {
        method: 'POST',
        body: JSON.stringify({ reason: document.getElementById('flag-reason').value, note: document.getElementById('flag-note').value }),
      });
      closeModal(); showToast(r.message);
    } catch (err) { showToast(err.message); }
  };
}
