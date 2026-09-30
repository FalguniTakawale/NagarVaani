/* Official portal — a separate product surface, not the citizen feed with
   extra buttons. Lives in #official-shell, completely outside the citizen
   page structure; switchToOfficialMode()/switchToCitizenMode() flip which
   of the two DOM trees is visible. All classes are .off-* (see styles.css). */
import { api, authUser, authToken, API_BASE, logout } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { CATEGORY_LABELS } from './feed.js';
import { nav, openComplaint } from './nav.js';

const ICON = { drainage: '🚰', water_supply: '🚰', road: '🛣️', garbage: '🗑️', electricity: '⚡', tree_hazard: '🌳', corruption: '⚠️', other: '❓' };
const LEVEL_LABEL = { ward_officer: 'Ward officer', municipal: 'Municipal commissioner', district: 'District collector', state: 'State official', central: 'Central ministry' };
const STATUS_LABEL = { open: 'Open', in_progress: 'In progress', resolved: 'Resolved', disputed: 'Disputed', rejected: 'Rejected' };

let currentView = 'queue';
let stats = null;
const detailCache = {};
let offMap = null, offMapLayer = null, offMapScope = 'ward';

/* ── mode switching ── */
export function switchToOfficialMode() {
  if (!authUser || authUser.role !== 'official') { nav('login'); return; }
  document.body.classList.add('official-mode');
  document.getElementById('official-shell').hidden = false;
  document.getElementById('off-user-name').textContent = authUser.name || 'Official';
  document.getElementById('off-user-level').textContent = LEVEL_LABEL[authUser.official_level] || 'Official';
  const verifyNav = document.getElementById('off-nav-verify');
  if (verifyNav) verifyNav.style.display = authUser.is_admin ? 'flex' : 'none';
  if (authUser.is_admin) refreshVerifyBadge();
  setOfficialView(currentView || 'queue');
}

export function switchToCitizenMode(page = 'home') {
  document.body.classList.remove('official-mode');
  document.getElementById('official-shell').hidden = true;
  const back = document.getElementById('official-portal-btn');
  if (back) back.hidden = !(authUser && authUser.role === 'official');
  nav(page);
}

export function offLogout() {
  logout();
  currentView = 'queue';
  stats = null;
  switchToCitizenMode('home');
  showToast('Signed out');
}

export function offOpenDetail(id) {
  // The citizen detail page is the full record; officials view it in citizen mode.
  switchToCitizenMode('detail');
  openComplaint(id);
}

/* ── shell ── */
export function setOfficialView(view) {
  currentView = view;
  document.querySelectorAll('#off-sidebar .off-nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  const main = document.getElementById('off-main');
  main.innerHTML = loadingPlaceholder();
  loadOfficialStats(); // also refreshes badges
  if (view === 'queue') loadOfficialQueue('queue');
  else if (view === 'all') loadOfficialQueue('all');
  else if (view === 'resolved') loadOfficialQueue('resolved');
  else if (view === 'map') loadHotspotMapFull();
  else if (view === 'flags') loadInvestmentFlags();
  else if (view === 'verify') loadVerificationQueue();
}

async function loadOfficialStats() {
  try {
    stats = await api('/stats/jurisdiction');
  } catch (err) {
    stats = null;
    showToast(err.message);
    return;
  }
  document.getElementById('off-user-jurisdiction').textContent = stats.jurisdiction;
  const totalOpen = stats.open + stats.in_progress + stats.disputed;
  setBadge('off-badge-critical', stats.critical);
  setBadge('off-badge-open', totalOpen);
  setBadge('off-badge-flags', stats.flagged);
  setBadge('off-badge-resolved', stats.resolved);
  document.getElementById('off-pulse').hidden = !(stats.critical > 0);
  renderTiles();
}

function setBadge(id, n) {
  const el = document.getElementById(id);
  el.textContent = n || '';
  el.hidden = !n;
}

function renderTiles() {
  const holder = document.getElementById('off-tiles');
  if (!holder || !stats) return;
  holder.innerHTML = `
    <div class="off-tile red"><div class="off-tile-label">Critical</div><div class="off-tile-num">${stats.critical}</div><div class="off-tile-sub">needs action</div></div>
    <div class="off-tile amber"><div class="off-tile-label">In progress</div><div class="off-tile-num">${stats.in_progress}</div><div class="off-tile-sub">&nbsp;</div></div>
    <div class="off-tile green"><div class="off-tile-label">Resolved</div><div class="off-tile-num">${stats.resolved}</div><div class="off-tile-sub">all time</div></div>
    <div class="off-tile blue"><div class="off-tile-label">Total open</div><div class="off-tile-num">${stats.open + stats.in_progress + stats.disputed}</div><div class="off-tile-sub">${stats.disputed ? stats.disputed + ' disputed' : '&nbsp;'}</div></div>`;
}

function sectionHeader(title, sub) {
  return `<div class="off-section-head">
    <div><div class="off-section-title">${title}</div>${sub ? `<div class="off-section-sub">${sub}</div>` : ''}</div>
    <span class="off-label">🏛️ Official View</span>
  </div>`;
}

/* ── queue / all / resolved ── */
const QUEUE_CONFIG = {
  queue: { title: 'My Queue', sub: 'Open complaints in your jurisdiction, severity-ranked. Votes don\'t reorder this list.', params: 'status_filter=open' },
  all: { title: 'All Complaints', sub: 'Every complaint in your jurisdiction, any status.', params: '' },
  resolved: { title: 'Resolved', sub: 'Closed by your office. Citizens can dispute these if the fix didn\'t hold.', params: 'status_filter=resolved' },
};

export async function loadOfficialQueue(kind = 'queue') {
  const cfg = QUEUE_CONFIG[kind] || QUEUE_CONFIG.queue;
  const main = document.getElementById('off-main');
  main.innerHTML = `
    ${sectionHeader(cfg.title, cfg.sub)}
    ${kind === 'queue' ? '<div class="off-tiles" id="off-tiles"></div>' : ''}
    <div class="off-table">
      <div class="off-thead">
        <div>Score</div><div></div><div>Complaint</div><div>Location</div><div>Age</div><div>Status</div><div>Actions</div>
      </div>
      <div id="off-rows">${loadingPlaceholder()}</div>
    </div>`;
  renderTiles();
  try {
    const items = await api(`/complaints?scope=jurisdiction&sort=priority&per_page=50${cfg.params ? '&' + cfg.params : ''}`);
    const rows = document.getElementById('off-rows');
    if (!items.length) {
      rows.innerHTML = `<div class="off-empty">Nothing here right now.</div>`;
      return;
    }
    rows.innerHTML = items.map(renderRow).join('');
  } catch (err) {
    document.getElementById('off-rows').innerHTML = `<div class="off-empty" style="color:#DC2626">${escapeHtml(err.message)}</div>`;
  }
}

function scoreClass(s) { return s >= 80 ? 'red' : s >= 55 ? 'amber' : 'green'; }

function relTime(iso) {
  if (!iso) return '—';
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 3600) return `${Math.max(1, Math.round(secs / 60))} min ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)} h ago`;
  const d = Math.round(secs / 86400);
  return d === 1 ? '1 day ago' : `${d} days ago`;
}

function actionButtons(c) {
  const s = c.status;
  const b = (label, action, disabled) =>
    `<button class="off-btn ${action}" ${disabled ? 'disabled' : ''} onclick="officialAction('${c.id}','${action}',this)">${label}</button>`;
  return `
    ${b('▶ Progress', 'in_progress', s === 'in_progress' || s === 'resolved')}
    ${b('✓ Resolve', 'resolve', s === 'resolved')}
    ${b('🚩 Flag', 'flag', false)}
    <button class="off-btn ghost" onclick="offOpenDetail('${c.id}')">→ Detail</button>`;
}

function renderRow(c) {
  const title = escapeHtml((c.text_translated || c.text_original || '').slice(0, 80));
  const loc = [c.ward ? 'Ward ' + c.ward : null, c.city].filter(Boolean).join(' · ') || (c.area || '—');
  return `
    <div class="off-row" id="off-row-${c.id}" data-status="${c.status}" onclick="expandQueueRow('${c.id}')">
      <div class="off-score ${scoreClass(c.priority_score)}">${Math.round(c.priority_score)}</div>
      <div class="off-icon" title="${CATEGORY_LABELS[c.category] || 'Other'}">${ICON[c.category] || ICON.other}</div>
      <div class="off-title">${title}${c.is_safety_risk ? ' <span class="off-safety">safety</span>' : ''}</div>
      <div class="off-loc">${escapeHtml(loc)}</div>
      <div class="off-age">${relTime(c.created_at)}</div>
      <div><span class="off-pill ${c.status}" id="off-pill-${c.id}">${STATUS_LABEL[c.status] || c.status}</span></div>
      <div class="off-actions" id="off-actions-${c.id}" onclick="event.stopPropagation()">${actionButtons(c)}</div>
    </div>
    <div class="off-expand" id="off-expand-${c.id}" hidden></div>`;
}

export async function expandQueueRow(id) {
  const box = document.getElementById('off-expand-' + id);
  if (!box) return;
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false;
  if (!detailCache[id]) {
    box.innerHTML = loadingPlaceholder();
    try {
      detailCache[id] = await api(`/complaints/${id}`);
    } catch (err) {
      box.innerHTML = `<div class="off-empty" style="color:#DC2626">${escapeHtml(err.message)}</div>`;
      return;
    }
  }
  const c = detailCache[id];
  box.innerHTML = `
    <div class="off-expand-grid">
      <div>
        <div class="off-kv-label">AI brief</div>
        <div class="off-kv">${escapeHtml(c.official_brief || '—')}</div>
        <div class="off-kv-label">Recommended action</div>
        <div class="off-kv accent">${escapeHtml(c.recommended_action || '—')}</div>
        <div class="off-kv-label">Citizen's own words</div>
        <div class="off-kv quote">“${escapeHtml(c.text_original)}”</div>
        <div class="off-kv-label">Cross-district signal</div>
        <div class="off-kv">${c.linked_area_count || 0} linked area${c.linked_area_count === 1 ? '' : 's'} · ${c.vote_count} votes · ${c.comment_count} comments</div>
      </div>
      <div>
        <div class="off-kv-label">Write response <span style="font-weight:400;color:#64748B">— visible to the citizen on the complaint</span></div>
        <textarea class="off-textarea" id="off-resp-${id}" placeholder="e.g. Inspection team dispatched, clearance begins Thursday."></textarea>
        <button class="off-btn primary" onclick="postOfficialResponse('${id}')">Send response</button>
        ${(c.comments || []).filter(cm => (cm.author_area || '').includes('Official')).map(cm => `
          <div class="off-prev-resp"><b>${escapeHtml(cm.author_name || 'Official')}</b> · ${new Date(cm.created_at).toLocaleDateString()}<br>${escapeHtml(cm.text)}</div>`).join('')}
      </div>
    </div>`;
}

export async function postOfficialResponse(id) {
  const ta = document.getElementById('off-resp-' + id);
  const text = ta.value.trim();
  if (!text) { showToast('Write a response first'); return; }
  try {
    await api(`/complaints/${id}/comments`, {
      method: 'POST',
      body: JSON.stringify({ text, author_name: authUser.name, author_area: 'Ward office · Official' }),
    });
    ta.value = '';
    delete detailCache[id];
    showToast('Response posted — the citizen will see it on the complaint');
    const box = document.getElementById('off-expand-' + id);
    box.hidden = true; expandQueueRow(id);
  } catch (err) {
    showToast(err.message);
  }
}

/* in_progress | resolve | flag — updates the row in place, no reload */
export async function officialAction(id, action, btn) {
  if (btn) btn.disabled = true;
  try {
    let newStatus = null;
    if (action === 'in_progress' || action === 'resolve') {
      newStatus = action === 'resolve' ? 'resolved' : 'in_progress';
      await api(`/complaints/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status: newStatus }) });
    } else if (action === 'flag') {
      const note = prompt('Flag for investment review — optional note for the senior reviewer:') ;
      if (note === null) { if (btn) btn.disabled = false; return; }
      await api(`/complaints/${id}/comments`, {
        method: 'POST',
        body: JSON.stringify({ text: `[OFFICIAL FLAG] ${note || 'Flagged for investment review'}`.trim(), author_name: authUser.name, author_area: 'Ward office · Official' }),
      });
      showToast('Flagged for investment review');
    }

    // In-place row update
    const row = document.getElementById('off-row-' + id);
    if (row && newStatus) {
      row.dataset.status = newStatus;
      const pill = document.getElementById('off-pill-' + id);
      pill.className = 'off-pill ' + newStatus; pill.textContent = STATUS_LABEL[newStatus];
      document.getElementById('off-actions-' + id).innerHTML = actionButtons({ id, status: newStatus });
      showToast(`Status: ${STATUS_LABEL[newStatus]}`);
      if (currentView === 'queue' && newStatus === 'resolved') row.classList.add('off-row-done');
    }
    delete detailCache[id];
    loadOfficialStats();
    updateMapPopup(id, newStatus);
  } catch (err) {
    showToast(err.status === 403 ? 'Official access required' : err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ── hotspot map ── */
export async function loadHotspotMapFull() {
  const main = document.getElementById('off-main');
  main.innerHTML = `
    ${sectionHeader('Hotspot Map', 'Every geotagged complaint, sized and coloured by AI score. Click a pin to act on it.')}
    <div class="off-map-toolbar">
      <div class="off-scope">
        <button class="off-scope-btn ${offMapScope === 'ward' ? 'active' : ''}" onclick="setOffMapScope('ward')">${stats ? stats.jurisdiction : 'My jurisdiction'}</button>
        <button class="off-scope-btn ${offMapScope === 'national' ? 'active' : ''}" onclick="setOffMapScope('national')">National</button>
      </div>
      <div class="off-legend"><span class="dot red"></span> ≥80 &nbsp; <span class="dot amber"></span> ≥55 &nbsp; <span class="dot green"></span> &lt;55</div>
    </div>
    <div class="off-map" id="off-map"></div>`;
  offMap = null;
  await drawOffMap();
}

export function setOffMapScope(scope) {
  offMapScope = scope;
  document.querySelectorAll('.off-scope-btn').forEach((b, i) => b.classList.toggle('active', (i === 0) === (scope === 'ward')));
  drawOffMap();
}

function jurisdictionMapParams() {
  const lvl = authUser.official_level;
  if (lvl === 'ward_officer' && authUser.ward) return { scope: 'ward', ward: authUser.ward };
  if ((lvl === 'municipal' || lvl === 'district') && authUser.city) return { scope: 'city', city: authUser.city };
  if (lvl === 'state' && authUser.state) return { scope: 'state', state: authUser.state };
  return { scope: 'national' };
}

async function drawOffMap() {
  if (typeof L === 'undefined') return;
  const el = document.getElementById('off-map');
  if (!el) return;
  if (!offMap) {
    offMap = L.map(el, { zoomControl: true, attributionControl: false });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(offMap);
    offMapLayer = L.layerGroup().addTo(offMap);
    setTimeout(() => offMap.invalidateSize(), 60);
  }
  offMapLayer.clearLayers();
  const params = offMapScope === 'national' ? { scope: 'national' } : jurisdictionMapParams();
  params.status_filter = '';  // all statuses — resolved pins matter on a map too
  let points = [];
  try {
    points = await api('/stats/map?' + new URLSearchParams(params).toString());
  } catch (err) { showToast(err.message); }

  if (!points.length) {
    offMap.setView(offMapScope === 'national' ? [20.5937, 78.9629] : [18.5308, 73.8479], offMapScope === 'national' ? 5 : 12);
    return;
  }
  const bounds = [];
  points.forEach(p => {
    const color = p.score >= 80 ? '#DC2626' : p.score >= 55 ? '#D97706' : '#16A34A';
    const m = L.circleMarker([p.lat, p.lng], { radius: 7 + (p.score / 100) * 12, color: 'white', weight: 2, fillColor: color, fillOpacity: 0.85 });
    m.bindPopup(mapPopupHtml(p, color), { minWidth: 240 });
    m.addTo(offMapLayer);
    bounds.push([p.lat, p.lng]);
  });
  offMap.fitBounds(bounds, { padding: [30, 30], maxZoom: offMapScope === 'national' ? 6 : 14 });
}

function mapPopupHtml(p, color) {
  return `<div class="off-popup" id="off-popup-${p.id}">
    <div class="off-popup-title">${escapeHtml(p.label)}</div>
    <div class="off-popup-meta"><span style="color:${color};font-weight:700">Score ${Math.round(p.score)}</span> · ${CATEGORY_LABELS[p.category] || 'Other'}${p.ward ? ' · Ward ' + p.ward : ''}</div>
    <div class="off-popup-actions">
      <button class="off-btn in_progress" onclick="officialAction('${p.id}','in_progress',this)">▶ In progress</button>
      <button class="off-btn resolve" onclick="officialAction('${p.id}','resolve',this)">✓ Resolve</button>
      <button class="off-btn ghost" onclick="offOpenDetail('${p.id}')">→ Detail</button>
    </div>
    <div class="off-popup-status" id="off-popup-status-${p.id}"></div>
  </div>`;
}

function updateMapPopup(id, newStatus) {
  const el = document.getElementById('off-popup-status-' + id);
  if (el && newStatus) el.textContent = 'Now: ' + STATUS_LABEL[newStatus];
}

/* ── investment flags ── */
const COST_RE = /₹\s?[\d.,]+(?:\s?(?:–|-|to)\s?[\d.,]+)?\s?(?:crore|cr|lakhs?|l|k)?/i;

export async function loadInvestmentFlags() {
  const main = document.getElementById('off-main');
  main.innerHTML = `
    ${sectionHeader('Investment Flags', 'Complaints your office flagged as infrastructure gaps — the list a senior or state-level reviewer works from.')}
    <div class="off-table flags">
      <div class="off-thead"><div>Complaint</div><div>Score</div><div>Recommended cost</div><div>Flagged by</div><div>Date</div></div>
      <div id="off-rows">${loadingPlaceholder()}</div>
    </div>
    <div style="margin-top:28px">
      ${sectionHeader('Data-driven project priorities', 'Unresolved demand by state and problem type, joined with Census-2011 population and mapped to the real central scheme that funds it. A triage aid — not a costed plan.')}
      <div style="margin:-4px 0 8px"><button class="b-btn secondary" onclick="downloadPrioritiesCsv(this)">⬇ Download CSV</button></div>
      <div id="off-priorities">${loadingPlaceholder()}</div>
    </div>`;
  loadProjectPriorities();
  try {
    const items = await api('/complaints/flagged');
    const rows = document.getElementById('off-rows');
    if (!items.length) {
      rows.innerHTML = `<div class="off-empty">No flags yet. Use <b>🚩 Flag</b> on a complaint in the queue to add it here.</div>`;
      return;
    }
    rows.innerHTML = items.map(f => {
      const cost = (f.recommended_action || '').match(COST_RE);
      return `
        <div class="off-row flags" onclick="offOpenDetail('${f.id}')">
          <div class="off-title">${ICON[f.category] || ICON.other} ${escapeHtml(f.title)}${f.flag_note ? `<div class="off-flag-note">“${escapeHtml(f.flag_note)}”</div>` : ''}</div>
          <div class="off-score ${scoreClass(f.priority_score)}">${Math.round(f.priority_score)}</div>
          <div class="off-cost">${cost ? escapeHtml(cost[0]) : '<span style="color:#94A3B8">not estimated</span>'}${f.recommended_action ? `<div class="off-cost-src">${escapeHtml(f.recommended_action.slice(0, 90))}${f.recommended_action.length > 90 ? '…' : ''}</div>` : ''}</div>
          <div>${escapeHtml(f.flagged_by || 'Official')}</div>
          <div class="off-age">${f.flagged_at ? new Date(f.flagged_at).toLocaleDateString() : '—'}</div>
        </div>`;
    }).join('');
  } catch (err) {
    document.getElementById('off-rows').innerHTML = `<div class="off-empty" style="color:#DC2626">${escapeHtml(err.message)}</div>`;
  }
}

/* Fetch with the auth header (a plain <a href> can't send it), then save the blob. */
export async function downloadPrioritiesCsv(btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(API_BASE + '/stats/priorities.csv', { headers: { Authorization: 'Bearer ' + authToken } });
    if (!res.ok) throw new Error(res.status === 403 ? 'Official access required' : `Download failed (${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement('a'), { href: url, download: 'nagarvaani_priority_projects.csv' });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    showToast(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadProjectPriorities() {
  const box = document.getElementById('off-priorities');
  try {
    const { items, method } = await api('/stats/priorities');
    if (!items.length) { box.innerHTML = `<div class="off-empty">No unresolved complaints with a state yet.</div>`; return; }
    box.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12.5px">
      <thead><tr style="text-align:left;color:#64748B"><th>State</th><th>Problem</th><th>Open</th><th>Avg severity</th><th>Per million people</th><th>Index</th><th>Suggested funding scheme</th></tr></thead>
      <tbody>${items.map(r => `<tr style="border-top:1px solid #E2E8F0">
        <td>${escapeHtml(r.state)}</td><td>${escapeHtml(r.category.replace('_', ' '))}</td><td>${r.open_complaints}</td>
        <td>${r.avg_severity}</td><td>${r.complaints_per_million ?? '—'}</td><td><b>${r.priority_index}</b></td>
        <td>${escapeHtml(r.suggested_funding_scheme)}</td></tr>`).join('')}</tbody></table></div>
      <div style="font-size:11px;color:#94A3B8;margin-top:6px">Method: ${escapeHtml(method)}</div>`;
  } catch (err) {
    box.innerHTML = `<div class="off-empty" style="color:#DC2626">${escapeHtml(err.message)}</div>`;
  }
}

/* ── official verifications (admin only) ──
   There's no real government employee registry to check a signup against —
   this is the manual trust boundary instead: an official's account can't do
   anything official-only (require_official on the backend) until an admin
   approves it here. Approval replaces their login with a system-issued email
   and a generated password, emailed to the work address they applied with. */
async function refreshVerifyBadge() {
  try {
    const items = await api('/admin/pending-officials');
    setBadge('off-badge-verify', items.length);
  } catch (_) { /* not an admin, or endpoint unreachable — badge just stays hidden */ }
}

export async function loadVerificationQueue() {
  const main = document.getElementById('off-main');
  main.innerHTML = `
    ${sectionHeader('Official Verifications', "Signups can't be checked against a real government employee registry — review each one and approve or reject by hand.")}
    <div id="verify-rows">${loadingPlaceholder()}</div>`;
  try {
    const items = await api('/admin/pending-officials');
    setBadge('off-badge-verify', items.length);
    const rows = document.getElementById('verify-rows');
    if (!items.length) {
      rows.innerHTML = `<div class="off-empty">No pending official applications right now.</div>`;
      return;
    }
    rows.innerHTML = items.map(p => `
      <div class="off-row" style="grid-template-columns:1fr auto;align-items:center;padding:14px 16px;">
        <div>
          <div class="off-title">${escapeHtml(p.name)}</div>
          <div style="font-size:12px;color:#64748B;margin-top:2px;">
            ${escapeHtml(p.requested_email || '—')} · ${escapeHtml(LEVEL_LABEL[p.official_level] || p.official_level || '—')}
            · ${escapeHtml(p.ward ? 'Ward ' + p.ward : (p.city || p.state || '—'))}
          </div>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="off-btn resolve" onclick="approveOfficialApplication('${p.id}', this)">✓ Approve</button>
          <button class="off-btn" style="border-color:#DC2626;color:#991B1B;" onclick="rejectOfficialApplication('${p.id}', this)">✕ Reject</button>
        </div>
      </div>`).join('');
  } catch (err) {
    document.getElementById('verify-rows').innerHTML = `<div class="off-empty" style="color:#DC2626">${escapeHtml(err.message)}</div>`;
  }
}

export async function approveOfficialApplication(id, btn) {
  if (btn) btn.disabled = true;
  try {
    const result = await api(`/admin/officials/${id}/approve`, { method: 'POST' });
    showToast(result.emailed
      ? `Approved — credentials emailed. Login: ${result.new_email}`
      : `Approved — SMTP not configured. Relay these yourself: ${result.new_email} / ${result.temporary_password}`);
    loadVerificationQueue();
  } catch (err) {
    showToast(err.message);
    if (btn) btn.disabled = false;
  }
}

export async function rejectOfficialApplication(id, btn) {
  if (btn) btn.disabled = true;
  try {
    await api(`/admin/officials/${id}/reject`, { method: 'POST', body: JSON.stringify({}) });
    showToast('Application rejected');
    loadVerificationQueue();
  } catch (err) {
    showToast(err.message);
    if (btn) btn.disabled = false;
  }
}
