import { api, authToken, authUser, requireLogin } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { currentSort, setCurrentSort } from './nav.js';
import { t, currentLang } from './i18n.js';

export const CATEGORY_LABELS = {
  drainage: 'Drainage', road: 'Road', garbage: 'Garbage', electricity: 'Electricity',
  tree_hazard: 'Tree hazard', water_supply: 'Water supply', corruption: 'Corruption', other: 'Other',
};

export function scoreBadgeClass(score) {
  if (score >= 80) return 'score-critical';
  if (score >= 55) return 'score-warn';
  return 'score-ok';
}

export function scoreLabel(score) {
  if (score >= 90) return 'CRITICAL';
  if (score >= 80) return 'PRIORITY';
  if (score >= 55) return 'MODERATE';
  return 'LOW';
}

/* Feed cards default to text_translated (English, set once at submission)
   or text_original — neither of which is guaranteed to match the viewer's
   own selected language. A Hindi-speaking voter with the UI set to Hindi
   should be able to read a Tamil complaint in Hindi before voting, not just
   in English. cardOriginals caches each card's true original text so
   translateCardTitle() can translate it to whatever language the viewer
   has selected, the same on-demand real translation already used on the
   detail page and on comments — just surfaced here too. */
const cardOriginals = {};

export function renderComplaintCard(c, { underTitle = '' } = {}) {
  const isCritical = c.is_safety_risk || c.priority_score >= 85;
  const chips = [`<span class="chip chip-type">${CATEGORY_LABELS[c.category] || 'Other'}</span>`];
  if (c.is_safety_risk) chips.push(`<span class="chip chip-season">⚠ Safety risk</span>`);
  if (c.ward) chips.push(`<span class="chip chip-loc">Ward ${c.ward}</span>`);
  else if (c.city) chips.push(`<span class="chip chip-loc">${c.city}</span>`);
  if (c.linked_area_count > 0) chips.push(`<span class="chip chip-linked">+${c.linked_area_count} linked areas</span>`);

  const lang = currentLang();
  const alreadyInViewerLang = c.detected_language && c.detected_language === lang;
  const displayText = alreadyInViewerLang ? (c.text_original || c.text_translated) : (c.text_translated || c.text_original);
  cardOriginals[c.id] = { text: c.text_original || c.text_translated, detected: c.detected_language };
  // English viewers already get text_translated; viewers whose language
  // matches the original need no translation either — only offer the link
  // when neither of those already covers it.
  const offerTranslate = lang !== 'en' && c.detected_language && !alreadyInViewerLang;

  return `
    <div class="complaint-card ${isCritical ? 'critical-card' : ''}" onclick="openComplaint('${c.id}')">
      <div class="cc-row">
        <div class="vote-col">
          <button class="vote-up" onclick="event.stopPropagation();quickVote('${c.id}', this)">▲</button>
          <div class="vote-count">${c.vote_count}</div>
          <div class="vote-label">votes</div>
        </div>
        <div class="cc-body">
          <div class="cc-title" id="cc-title-${c.id}">${escapeHtml(displayText)}</div>
          ${offerTranslate ? `<span class="cc-translate-link" data-cid="${c.id}" onclick="event.stopPropagation();translateCardTitle('${c.id}', this)">🌐 ${t('cc.translate')}</span>` : ''}
          ${underTitle}
          <div class="cc-chips">${chips.join('')}</div>
          <div class="cc-footer">
            <div class="cc-actions">
              <span class="cc-action">💬 ${c.comment_count} comments</span>
              <span class="cc-action">📸 ${c.image_count} photos</span>
            </div>
            <div class="score-badge ${scoreBadgeClass(c.priority_score)}"><span>Score ${Math.round(c.priority_score)}</span><span class="score-label">${scoreLabel(c.priority_score)}</span></div>
          </div>
        </div>
      </div>
    </div>`;
}

export async function translateCardTitle(id, linkEl) {
  const titleEl = document.getElementById('cc-title-' + id);
  const cached = cardOriginals[id];
  if (!titleEl || !cached) return;

  if (linkEl.dataset.translated === '1') {
    titleEl.textContent = linkEl.dataset.prevText;
    linkEl.textContent = '🌐 ' + t('cc.translate');
    linkEl.dataset.translated = '0';
    return;
  }

  const prevText = titleEl.textContent;
  linkEl.textContent = t('detail.translating');
  try {
    const result = await api('/translate', {
      method: 'POST', body: JSON.stringify({ text: cached.text, target_language: currentLang() }),
    });
    linkEl.dataset.prevText = prevText;
    titleEl.textContent = result.translated;
    linkEl.textContent = '🌐 ' + t('cc.showoriginal');
    linkEl.dataset.translated = '1';
  } catch (err) {
    linkEl.textContent = '🌐 ' + t('cc.translate');
    showToast(err.message);
  }
}

/* ── MY COMPLAINTS ──
   Different card from the public feed: no vote column (you don't vote on your
   own), status is the hero, and the dispute button appears only on resolved
   ones — every item here is the current user's, so author == viewer. */
const STATUS_ICON = { open: '◌', in_progress: '↻', resolved: '✓', disputed: '⚑', rejected: '✕' };
const STATUS_KEY = { open: 'my.open', in_progress: 'my.inprogress', resolved: 'my.resolved', disputed: 'my.disputed', rejected: 'my.rejected' };
let myStatusFilter = '';
let trendingAreaFilter = '';
let myPollTimer = null;

export function renderMyComplaintCard(c) {
  const status = c.status || 'open';
  const where = [c.location_text, c.area, c.ward ? 'Ward ' + c.ward : null, c.city].filter(Boolean).slice(0, 2).join(' · ');
  return `
    <div class="my-card" onclick="openComplaint('${c.id}')">
      <span class="my-status ${status}">${STATUS_ICON[status] || ''} ${t(STATUS_KEY[status] || 'my.open')}</span>
      <div class="my-body">
        <div class="my-title">${escapeHtml(c.text_translated || c.text_original)}</div>
        <div class="my-meta">
          <span>${t('my.score')} <b>${Math.round(c.priority_score)}</b></span>
          <span>${CATEGORY_LABELS[c.category] || 'Other'}</span>
          <span>${t('my.submitted')} ${c.created_at ? new Date(c.created_at).toLocaleDateString() : '—'}</span>
          ${where ? `<span>📍 ${escapeHtml(where)}</span>` : ''}
          ${c.comment_count ? `<span>💬 ${c.comment_count}</span>` : ''}
        </div>
        ${status === 'resolved' ? `<div class="my-actions"><button class="dispute-btn" onclick="event.stopPropagation();doDispute('${c.id}')">${t('my.dispute')}</button></div>` : ''}
      </div>
    </div>`;
}

export function setMyStatusFilter(status, btn) {
  myStatusFilter = status || '';
  document.querySelectorAll('#my-status-tabs .status-tab').forEach(b => b.classList.toggle('active', b === btn));
  loadFeed('mycomplaints');
}

export function filterTrendingByArea() {
  const input = document.getElementById('trending-area-filter');
  trendingAreaFilter = (input.value || '').trim();
  document.getElementById('trending-clear-filter-btn').style.display = trendingAreaFilter ? 'inline-block' : 'none';
  loadFeed('trending');
}

export function clearTrendingAreaFilter() {
  trendingAreaFilter = '';
  document.getElementById('trending-area-filter').value = '';
  document.getElementById('trending-clear-filter-btn').style.display = 'none';
  loadFeed('trending');
}

export function stopMyComplaintsPolling() {
  clearInterval(myPollTimer);
  myPollTimer = null;
}

function startMyComplaintsPolling() {
  stopMyComplaintsPolling();
  // Official status changes show up without a manual reload while this page is open.
  myPollTimer = setInterval(() => {
    const active = document.getElementById('page-mycomplaints').classList.contains('active');
    if (active) loadFeed('mycomplaints', { silent: true }); else stopMyComplaintsPolling();
  }, 60_000);
}

export function toggleSchemesPanel() {
  document.querySelector('.schemes-panel').classList.toggle('collapsed');
}

let schemesStatsLoaded = false;
async function loadSchemesStats() {
  if (schemesStatsLoaded) return; // real nationwide numbers, no need to refetch every trending visit
  try {
    const stats = await api('/stats/nationwide');
    document.getElementById('schemes-stat-resolved').textContent = stats.resolved.toLocaleString();
    document.getElementById('schemes-stat-pct').textContent = stats.total ? Math.round(stats.resolved / stats.total * 100) + '%' : '0%';
    document.getElementById('schemes-stat-states').textContent = stats.states_with_patterns.toLocaleString();
    schemesStatsLoaded = true;
  } catch (err) { /* schemes panel stats are supplementary — fail quietly */ }
}

let govtSchemesPageLoaded = false;
export async function loadGovtSchemesPage() {
  if (govtSchemesPageLoaded) return;
  try {
    const stats = await api('/stats/nationwide');
    document.getElementById('gs-stat-resolved').textContent = stats.resolved.toLocaleString();
    document.getElementById('gs-stat-pct').textContent = stats.total ? Math.round(stats.resolved / stats.total * 100) + '%' : '0%';
    document.getElementById('gs-stat-states').textContent = stats.states_with_patterns.toLocaleString();
    govtSchemesPageLoaded = true;
  } catch (err) { /* supplementary — fail quietly */ }
}

let landingStatsLoaded = false;
export async function loadLandingStats() {
  if (landingStatsLoaded) return;
  try {
    const stats = await api('/stats/nationwide');
    document.getElementById('landing-stat-total').textContent = stats.total.toLocaleString();
    document.getElementById('landing-stat-resolved').textContent = stats.resolved.toLocaleString();
    document.getElementById('landing-stat-states').textContent = stats.states_with_patterns.toLocaleString();
    landingStatsLoaded = true;
  } catch (err) { /* supplementary — fail quietly */ }
}

/* ── PAGINATION (Home + Trending/nationwide) ──
   10 per page with Previous / Next. The API returns just a list, so "Next" is offered
   when a page comes back full; a full-but-last page just shows an empty next page,
   which steps itself back. Any change of sort/filter/tab starts again at page 1. */
const PAGE_SIZE = 10;
const feedPageNo = { home: 1, trending: 1 };

function renderPager(page, container, count) {
  const id = page + '-pager';
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div');
    el.id = id; el.className = 'feed-pager';
    container.insertAdjacentElement('afterend', el);
  }
  const n = feedPageNo[page];
  const hasNext = count >= PAGE_SIZE;
  if (n === 1 && !hasNext) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <button class="pager-btn" ${n <= 1 ? 'disabled' : ''} onclick="feedGoPage('${page}', ${n - 1})">← Previous</button>
    <span class="pager-info">Page ${n}</span>
    <button class="pager-btn" ${hasNext ? '' : 'disabled'} onclick="feedGoPage('${page}', ${n + 1})">Next →</button>`;
}

export function feedGoPage(page, n) {
  feedPageNo[page] = Math.max(1, n);
  loadFeed(page, { keepPage: true });
  const top = document.getElementById(page === 'home' ? 'home-feed-list' : 'trending-feed-list');
  if (top) top.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export async function loadFeed(page, { silent = false, keepPage = false } = {}) {
  if (feedPageNo[page] !== undefined && !keepPage) feedPageNo[page] = 1;
  if (page === 'trending') loadSchemesStats();
  const listMap = { home: 'home-feed-list', trending: 'trending-feed-list', nearme: 'nearme-feed-list', mycomplaints: 'mycomplaints-feed-list', myvotes: 'myvotes-feed-list' };
  const scopeMap = { home: 'ward', trending: 'trending', nearme: 'nearby', mycomplaints: 'mine', myvotes: 'voted' };
  const subtitleMap = { mycomplaints: 'my-subtitle', myvotes: 'myvotes-subtitle' };
  const container = document.getElementById(listMap[page]);
  const scope = scopeMap[page];
  if (!container) return;

  if ((scope === 'mine' || scope === 'voted') && !authToken) {
    container.innerHTML = `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('js.mylogin')} <a style="color:var(--navy);cursor:pointer;" onclick="nav('login')">${t('js.signin')}</a></div>`;
    const subtitleEl = document.getElementById(subtitleMap[page]);
    if (subtitleEl) subtitleEl.textContent = '';
    return;
  }

  const params = new URLSearchParams({ scope, sort: scope === 'mine' ? 'recent' : currentSort });
  if (feedPageNo[page] !== undefined) { params.set('per_page', String(PAGE_SIZE)); params.set('page', String(feedPageNo[page])); }
  if (scope === 'trending' && trendingAreaFilter) params.set('near_text', trendingAreaFilter);
  if (scope === 'mine') {
    if (myStatusFilter) params.set('status_filter', myStatusFilter);
    params.set('per_page', '50');
    if (!silent) container.innerHTML = loadingPlaceholder();
    await fetchAndRenderFeed(container, params, {
      render: renderMyComplaintCard,
      empty: myStatusFilter
        ? `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('my.nomatch')}</div>`
        : `<div style="padding:32px;text-align:center;color:var(--slate);font-size:13px;">${t('my.empty')}<br><a style="color:var(--navy);cursor:pointer;font-weight:600;" onclick="nav('submit')">${t('my.emptylink')}</a></div>`,
      after: (items) => { document.getElementById('my-subtitle').textContent = t('my.count', { n: items.length }); },
    });
    startMyComplaintsPolling();
    return;
  }
  if (scope === 'voted') {
    params.set('per_page', '50');
    if (!silent) container.innerHTML = loadingPlaceholder();
    await fetchAndRenderFeed(container, params, {
      empty: `<div style="padding:32px;text-align:center;color:var(--slate);font-size:13px;">${t('myvotes.empty')}</div>`,
      after: (items) => { document.getElementById('myvotes-subtitle').textContent = t('myvotes.count', { n: items.length }); },
    });
    return;
  }
  let knownLocation = true;
  if (page === 'home') {
    if (authUser && authUser.ward) params.set('ward', authUser.ward);
    else if (authUser && authUser.city) params.set('city', authUser.city);   // ward is optional at signup
    knownLocation = !!(authUser && (authUser.ward || authUser.area || authUser.city));
    const title = document.getElementById('home-feed-title');
    if (title) {
      title.textContent = knownLocation
        ? `Issues in ${[authUser.ward ? 'Ward ' + authUser.ward : null, authUser.area, authUser.city].filter(Boolean).join(' · ')}`
        : t('feed.home.title');
    }
  }

  // Only show the loading state if the list is empty or already holds real
  // results — leave the static demo cards alone on first load so a slow or
  // unreachable backend still leaves something to look at.
  if (!container.children.length || container.dataset.live === '1') {
    container.innerHTML = loadingPlaceholder();
  }

  if (scope === 'nearby' && navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      pos => { params.set('lat', pos.coords.latitude); params.set('lng', pos.coords.longitude); fetchAndRenderFeed(container, params); },
      () => fetchAndRenderFeed(container, params)
    );
    return;
  }
  // The backend deliberately returns nothing for scope=ward with no known
  // location (rather than an unfiltered nationwide dump) — explain why,
  // don't just say "no complaints" as if the ward were genuinely empty.
  const emptyOverride = (page === 'home' && !knownLocation)
    ? `<div style="padding:32px;text-align:center;color:var(--slate);font-size:13px;">${t('feed.home.nolocation')}<br><a style="color:var(--navy);cursor:pointer;font-weight:600;" onclick="nav('login')">${t('js.signin')}</a> · <a style="color:var(--navy);cursor:pointer;font-weight:600;" onclick="nav('trending')">${t('nav.trending')}</a> · <a style="color:var(--navy);cursor:pointer;font-weight:600;" onclick="nav('nearme')">${t('nav.nearme')}</a></div>`
    : null;
  fetchAndRenderFeed(container, params, emptyOverride ? { empty: emptyOverride } : undefined);
}

async function fetchAndRenderFeed(container, params, { render = renderComplaintCard, empty = null, after = null } = {}) {
  try {
    const complaints = await api('/complaints?' + params.toString());
    container.dataset.live = '1';
    if (after) after(complaints);
    const pgName = params.get('scope') === 'trending' ? 'trending' : params.get('scope') === 'ward' ? 'home' : null;
    if (!complaints.length && pgName && feedPageNo[pgName] > 1) {   // ran past the last page
      feedPageNo[pgName] -= 1;
      return fetchAndRenderFeed(container, (() => { const p = new URLSearchParams(params); p.set('page', String(feedPageNo[pgName])); return p; })(), { render, empty, after });
    }
    if (!complaints.length) {
      if (pgName) { const el = document.getElementById(pgName + '-pager'); if (el) el.innerHTML = ''; }
      container.innerHTML = empty || `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;"><span data-i18n="js.empty">${t('js.empty')}</span> <a style="color:var(--navy);cursor:pointer;" data-i18n="js.emptylink" onclick="nav('submit')">${t('js.emptylink')}</a>.</div>`;
      return;
    }
    container.innerHTML = complaints.map(render).join('');
    const pg = params.get('scope') === 'trending' ? 'trending' : params.get('scope') === 'ward' ? 'home' : null;
    if (pg && feedPageNo[pg] !== undefined) renderPager(pg, container, complaints.length);
  } catch (err) {
    if (container.querySelector('.loading-state')) {
      container.innerHTML = `<div style="padding:24px;text-align:center;color:var(--critical);font-size:13px;">Couldn't load complaints — ${escapeHtml(err.message)}</div>`;
    }
    // Otherwise the static demo cards are still in place — leave them as the fallback.
    showToast(err.message);
  }
}

export function sortToggle(btn) {
  btn.closest('.sort-group').querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  setCurrentSort(btn.dataset.sort || 'priority');
  const activePage = document.querySelector('.page.active').id.replace('page-', '');
  loadFeed(activePage);
}

export function selectCat(btn) {
  btn.closest('.category-grid').querySelectorAll('.cat-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
}

// Only reachable on the static placeholder cards, before loadFeed() replaces them with real data (or if the backend is unreachable).
export function voteUp(btn) {
  const countEl = btn.nextElementSibling;
  countEl.textContent = parseInt(countEl.textContent) + 1;
  btn.style.borderColor = 'var(--saffron)';
  btn.style.color = 'var(--saffron-dark)';
  btn.style.background = 'var(--saffron-light)';
  showToast('Demo card — connect to a real complaint to vote for real');
}

export async function quickVote(id, btn) {
  if (!requireLogin(t('js.logintovote'))) return;
  try {
    const result = await api(`/complaints/${id}/vote`, { method: 'POST', body: JSON.stringify({}) });
    const countEl = btn.nextElementSibling;
    countEl.textContent = result.new_vote_count;
    btn.style.borderColor = 'var(--saffron)';
    btn.style.color = 'var(--saffron-dark)';
    btn.style.background = 'var(--saffron-light)';
    showToast(t('js.voted', { score: result.new_score }));
  } catch (err) {
    showToast(err.message);
  }
}

/* ── RIGHT-PANEL DASHBOARD STATS — real counts, not the old hardcoded demo
   numbers. Ward if known, else city, else nationwide; same fallback the
   backend itself applies if we don't pass one. ── */
export async function loadDashboardStats() {
  const params = new URLSearchParams();
  if (authUser && authUser.ward) params.set('ward', authUser.ward);
  else if (authUser && authUser.city) params.set('city', authUser.city);

  try {
    const stats = await api('/stats/ward?' + params.toString());
    document.getElementById('dashboard-stats-label').textContent = t('panel.statslabel', { label: stats.label });
    document.getElementById('stat-open').textContent = stats.open;
    document.getElementById('stat-resolved').textContent = stats.resolved;
    document.getElementById('stat-critical').textContent = stats.critical;
    document.getElementById('stat-inprogress').textContent = stats.in_progress;
    document.getElementById('resolution-fill-bar').style.width = stats.resolved_pct + '%';
    document.getElementById('dashboard-resolution-text').textContent = t('panel.resolutiontext', { pct: stats.resolved_pct });
  } catch (err) {
    // Right-panel stats are a nice-to-have, not core functionality — fail
    // quietly rather than toast an error over a feed page load.
    document.getElementById('dashboard-stats-label').textContent = t('panel.statslabel', { label: '—' });
  }

  loadGovtUpdates(params);
  loadMyComplaintsPanel();
}

/* Right-panel "Your complaints": the signed-in user's own latest complaints (real
   data — this used to be three hardcoded example rows). Empty state when none. */
async function loadMyComplaintsPanel() {
  const list = document.getElementById('mycomplaints-panel-list');
  if (!list) return;
  if (!authToken) { list.innerHTML = ''; return; }
  try {
    const items = await api('/complaints?scope=mine&sort=recent&per_page=3');
    const pill = {
      resolved: ['status-resolved', 'pill.resolved'], in_progress: ['status-progress', 'pill.progress'], open: ['status-open', 'pill.open'],
      disputed: ['status-open', 'my.disputed'], rejected: ['status-open', 'my.rejected'],
    };
    list.innerHTML = items.length
      ? items.map(c => {
          const [cls, key] = pill[c.status] || pill.open;
          const title = (c.text_translated || c.text_original || '').slice(0, 60);
          return `<div class="my-complaint-item" style="cursor:pointer" onclick="openComplaint('${escapeHtml(c.id)}')"><div class="my-c-title">${escapeHtml(title)}</div><span class="status-pill ${cls}">${t(key)}</span></div>`;
        }).join('')
      : `<div style="font-size:11.5px;color:var(--slate-light);padding:4px 0 8px;">${t('panel.nomine')}</div>`;
  } catch (err) {
    list.innerHTML = '';
  }
}

const STATUS_ICON_GOVT = { open: '◌', in_progress: '↻', resolved: '✓', disputed: '⚑', rejected: '✕' };
const STATUS_LABEL_KEY_GOVT = { open: 'my.open', in_progress: 'my.inprogress', resolved: 'my.resolved', disputed: 'my.disputed', rejected: 'my.rejected' };

function relTimeShort(iso) {
  if (!iso) return '';
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 3600) return `${Math.max(1, Math.round(secs / 60))} min ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)} h ago`;
  const d = Math.round(secs / 86400);
  return d === 1 ? '1 day ago' : `${d} days ago`;
}

async function loadGovtUpdates(scopeParams) {
  const list = document.getElementById('govt-updates-list');
  if (!list) return;
  try {
    const updates = await api('/stats/recent-updates?' + scopeParams.toString());
    list.innerHTML = updates.length
      ? updates.map(u => `
        <div class="govt-item">
          <div class="govt-title-s">${escapeHtml(u.title)}</div>
          <div class="govt-meta">${STATUS_ICON_GOVT[u.status] || ''} ${t(STATUS_LABEL_KEY_GOVT[u.status] || 'my.open')} · ${relTimeShort(u.created_at)}</div>
        </div>`).join('')
      : `<div style="font-size:11.5px;color:var(--slate-light);padding:4px 0;">${t('panel.noupdates')}</div>`;
  } catch (err) {
    list.innerHTML = '';
  }
}

/* ── NOTIFICATION BELL ──
   Real status changes on complaints the signed-in user actually filed —
   not a hardcoded "3 updates" toast. Guests get an honest sign-in prompt
   instead of a number that means nothing for an anonymous visitor. */
export async function toggleNotifMenu(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('notif-menu');
  const willOpen = menu.hidden;
  document.querySelectorAll('.lang-menu, .notif-menu').forEach(m => m.hidden = true);
  if (!willOpen) return;
  menu.hidden = false;

  const list = document.getElementById('notif-menu-list');
  if (!authToken) {
    list.innerHTML = `<div class="notif-menu-empty notif-menu-guest">${t('notif.guest')} <a onclick="nav('login')">${t('top.signin')}</a></div>`;
    return;
  }
  list.innerHTML = loadingPlaceholder();
  try {
    const updates = await api('/stats/my-updates?limit=5');
    list.innerHTML = updates.length
      ? updates.map(u => `
        <div class="notif-menu-item">
          <div class="notif-menu-item-title">${escapeHtml(u.title)}</div>
          <div class="notif-menu-item-meta">${STATUS_ICON_GOVT[u.status] || ''} ${t(STATUS_LABEL_KEY_GOVT[u.status] || 'my.open')} · ${relTimeShort(u.created_at)}</div>
        </div>`).join('')
      : `<div class="notif-menu-empty">${t('notif.empty')}</div>`;
    document.getElementById('notif-dot').hidden = true; // seen, now that the panel is open
  } catch (err) {
    list.innerHTML = `<div class="notif-menu-empty">${escapeHtml(err.message)}</div>`;
  }
}

// Called after login and on initial load for an already-signed-in user —
// lights the dot only if there's a real status change to see.
export async function refreshNotifDot() {
  const dot = document.getElementById('notif-dot');
  if (!dot) return;
  if (!authToken) { dot.hidden = true; return; }
  try {
    const updates = await api('/stats/my-updates?limit=1');
    dot.hidden = updates.length === 0;
  } catch (err) {
    dot.hidden = true;
  }
}

document.addEventListener('click', (e) => {
  const menu = document.getElementById('notif-menu');
  if (menu && !menu.hidden && !e.target.closest('.notif-wrap')) menu.hidden = true;
});
