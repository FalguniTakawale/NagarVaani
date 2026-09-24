import { loadFeed, stopMyComplaintsPolling } from './feed.js';
import { loadComplaintDetail } from './detail.js';
import { loadGovtDashboard, initGovtMaps } from './govt.js';
import { loadNearMe } from './nearme.js';
import { loadCorruptionFeed } from './corruption.js';

export const feedPages = ['home', 'trending', 'nearme', 'mycomplaints'];

// The wrapper div for each page carries its real layout mode (three-panel
// pages must stay flex; everything else lays itself out via an inner child).
const pageDisplay = {
  home: 'flex', trending: 'flex', nearme: 'flex', mycomplaints: 'flex',
  detail: 'block', submit: 'block', govt: 'block', login: 'block', corruption: 'block',
  landing: 'block',
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
  if (page === 'corruption') loadCorruptionFeed();
  else if (page === 'nearme') loadNearMe();
  else if (feedPages.includes(page)) loadFeed(page);

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
