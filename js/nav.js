import { loadFeed, stopMyComplaintsPolling, loadDashboardStats, loadGovtSchemesPage, loadLandingStats } from './feed.js';
import { authToken } from './api.js';
import { loadComplaintDetail } from './detail.js';
import { loadGovtDashboard, initGovtMaps } from './govt.js';
import { loadNearMe, stopNearMePolling } from './nearme.js';
import { loadCorruptionFeed } from './corruption.js';
import { showToast } from './ui.js';
import { updateSubmitAuthNotice } from './submit.js';
import { loadForOfficials } from './forofficials.js';
import { loadImpactPage, initOrgSupportPage } from './getinvolved.js';
import { showChatbotWidget } from './chatbot.js';
import { initGoogleSignIn } from './auth.js';

// Trending is deliberately NOT in this list — it's a standalone public
// preview (top issues + a "sign in for more" prompt), not part of the
// signed-in app shell, so it never gets the left-nav/right-panel chrome.
export const feedPages = ['home', 'nearme', 'mycomplaints', 'myvotes'];

// The wrapper div for each page carries its real layout mode (three-panel
// pages must stay flex; everything else lays itself out via an inner child).
const pageDisplay = {
  home: 'flex', nearme: 'flex', mycomplaints: 'flex', myvotes: 'flex',
  detail: 'block', submit: 'block', govt: 'block', login: 'block', corruption: 'block',
  landing: 'block', about: 'block', track: 'block', forofficials: 'block',
  govtschemes: 'block', trending: 'block', impact: 'block', orgsupport: 'block',
};

export let currentComplaintId = null;
export let currentSort = 'priority';
export function setCurrentSort(sort) { currentSort = sort; }

// The app is a single document — nav() only ever swaps which .page is
// visible, it never changes the URL. Without history entries of our own,
// the browser's back button has nothing internal to step through and just
// leaves the whole app. We push one history entry per navigation (and swap
// pages on popstate instead of pushing again) so back/forward move between
// in-app pages first, the way a normal multi-page site would.
let historyStarted = false;

export function nav(page, opts = {}) {
  const { fromPopstate = false } = opts;
  stopMyComplaintsPolling();
  stopNearMePolling();
  document.querySelectorAll('.page').forEach(p => {
    p.classList.remove('active');
    p.style.display = 'none';
    p.style.opacity = '0';
  });

  const target = document.getElementById('page-' + page);
  target.classList.add('active');
  target.style.transition = 'none';
  target.style.display = pageDisplay[page] || 'block';
  target.style.opacity = '0';
  // Force a reflow so the browser registers the 0-opacity state before we
  // transition to 1 — otherwise the fade-in never has anything to animate from.
  void target.offsetHeight;
  target.style.transition = 'opacity 0.18s ease';
  target.style.opacity = '1';

  const leftNav = document.getElementById('left-nav');
  const rightPanel = document.getElementById('right-panel');
  const showNav = feedPages.includes(page);
  const showRight = feedPages.includes(page);

  leftNav.style.display = showNav ? 'flex' : 'none';
  rightPanel.style.display = showRight ? 'flex' : 'none';

  // Update active nav item
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const navEl = document.getElementById('nav-' + page);
  if (navEl) navEl.classList.add('active');

  if (page === 'govt') { loadGovtDashboard(); setTimeout(initGovtMaps, 50); }
  if (page === 'forofficials') loadForOfficials();
  if (page === 'govtschemes') loadGovtSchemesPage();
  if (page === 'landing') loadLandingStats();
  showChatbotWidget(page === 'home');
  if (page === 'impact') loadImpactPage();
  if (page === 'orgsupport') initOrgSupportPage();
  if (page === 'submit') updateSubmitAuthNotice();
  if (page === 'login') initGoogleSignIn();
  if (page === 'corruption') loadCorruptionFeed();
  else if (page === 'nearme') loadNearMe();
  else if (page === 'trending') {
    loadFeed('trending');
    const cta = document.getElementById('trending-signin-cta');
    if (cta) cta.hidden = !!authToken;
  }
  else if (feedPages.includes(page)) loadFeed(page);
  if (feedPages.includes(page)) loadDashboardStats();

  if (!fromPopstate) {
    const state = { page, id: page === 'detail' ? currentComplaintId : undefined };
    // The very first nav() call is the initial render, not a user action —
    // replace that entry instead of pushing, so one "back" press from the
    // first page a visitor sees behaves like leaving the site (correct),
    // rather than landing on a phantom duplicate of the same page.
    if (!historyStarted) {
      historyStarted = true;
      history.replaceState(state, '', '#' + page);
    } else {
      history.pushState(state, '', '#' + page);
    }
  }
}

export function openComplaint(id) {
  currentComplaintId = id;
  nav('detail');
  loadComplaintDetail(id);
}

window.addEventListener('popstate', (e) => {
  const state = e.state || { page: 'landing' };
  if (state.page === 'detail' && state.id) {
    currentComplaintId = state.id;
    nav('detail', { fromPopstate: true });
    loadComplaintDetail(state.id);
  } else {
    nav(state.page || 'landing', { fromPopstate: true });
  }
});

/* The topbar search box's only real job right now: let anyone — including a
   guest with no account — paste the complaint ID they were given after
   submitting and jump straight to it. There's no broader text search across
   complaints yet, so this only handles the ID case; openComplaint() already
   shows a clear "couldn't load this complaint" if the ID doesn't match. */
export function topbarSearch(query) {
  const q = (query || '').trim();
  if (!q) { showToast('Type a complaint ID to look it up.'); return; }
  const input = document.getElementById('topbar-search-input');
  if (input) input.value = '';
  openComplaint(q);
}

/* Same idea as topbarSearch, but as its own dedicated, clearly-labeled page —
   more discoverable for someone who was never signed in and wouldn't think
   to use the topbar search box for this. */
export function trackComplaintById() {
  const input = document.getElementById('track-id-input');
  const q = (input.value || '').trim();
  if (!q) { showToast('Enter the complaint ID you were given.'); return; }
  openComplaint(q);
}
