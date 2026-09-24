import { api, authToken, authUser, requireLogin } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { currentSort, setCurrentSort } from './nav.js';
import { t } from './i18n.js';

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

export function renderComplaintCard(c, { underTitle = '' } = {}) {
  const isCritical = c.is_safety_risk || c.priority_score >= 85;
  const chips = [`<span class="chip chip-type">${CATEGORY_LABELS[c.category] || 'Other'}</span>`];
  if (c.is_safety_risk) chips.push(`<span class="chip chip-season">⚠ Safety risk</span>`);
  if (c.ward) chips.push(`<span class="chip chip-loc">Ward ${c.ward}</span>`);
  else if (c.city) chips.push(`<span class="chip chip-loc">${c.city}</span>`);
  if (c.linked_area_count > 0) chips.push(`<span class="chip chip-linked">+${c.linked_area_count} linked areas</span>`);

  return `
    <div class="complaint-card ${isCritical ? 'critical-card' : ''}" onclick="openComplaint('${c.id}')">
      <div class="cc-row">
        <div class="vote-col">
          <button class="vote-up" onclick="event.stopPropagation();quickVote('${c.id}', this)">▲</button>
          <div class="vote-count">${c.vote_count}</div>
          <div class="vote-label">votes</div>
        </div>
        <div class="cc-body">
          <div class="cc-title">${escapeHtml(c.text_translated || c.text_original)}</div>
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

/* ── MY COMPLAINTS ──
   Different card from the public feed: no vote column (you don't vote on your
   own), status is the hero, and the dispute button appears only on resolved
   ones — every item here is the current user's, so author == viewer. */
const STATUS_ICON = { open: '◌', in_progress: '↻', resolved: '✓', disputed: '⚑', rejected: '✕' };
const STATUS_KEY = { open: 'my.open', in_progress: 'my.inprogress', resolved: 'my.resolved', disputed: 'my.disputed', rejected: 'my.rejected' };
let myStatusFilter = '';
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

export async function loadFeed(page, { silent = false } = {}) {
  const listMap = { home: 'home-feed-list', trending: 'trending-feed-list', nearme: 'nearme-feed-list', mycomplaints: 'mycomplaints-feed-list' };
  const scopeMap = { home: 'ward', trending: 'trending', nearme: 'nearby', mycomplaints: 'mine' };
  const container = document.getElementById(listMap[page]);
  const scope = scopeMap[page];
  if (!container) return;

  if (scope === 'mine' && !authToken) {
    container.innerHTML = `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('js.mylogin')} <a style="color:var(--navy);cursor:pointer;" onclick="nav('login')">${t('js.signin')}</a></div>`;
    document.getElementById('my-subtitle').textContent = '';
    return;
  }

  const params = new URLSearchParams({ scope, sort: scope === 'mine' ? 'recent' : currentSort });
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
  if (page === 'home') {
    if (authUser && authUser.ward) params.set('ward', authUser.ward);
    const title = document.getElementById('home-feed-title');
    if (title) {
      title.textContent = authUser && (authUser.ward || authUser.area || authUser.city)
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
  fetchAndRenderFeed(container, params);
}

async function fetchAndRenderFeed(container, params, { render = renderComplaintCard, empty = null, after = null } = {}) {
  try {
    const complaints = await api('/complaints?' + params.toString());
    container.dataset.live = '1';
    if (after) after(complaints);
    if (!complaints.length) {
      container.innerHTML = empty || `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;"><span data-i18n="js.empty">${t('js.empty')}</span> <a style="color:var(--navy);cursor:pointer;" data-i18n="js.emptylink" onclick="nav('submit')">${t('js.emptylink')}</a>.</div>`;
      return;
    }
    container.innerHTML = complaints.map(render).join('');
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
