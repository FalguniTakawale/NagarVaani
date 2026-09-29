/* Two standalone pages — Our Impact, and Organizations/Volunteers/NGOs.
   Deliberately NOT a shared tabbed hub: each is reached directly from the
   landing page or footer and stays on its own page, no switching back into
   a shared container. Everything here is either a real working action
   (mailto CTAs, honestly labeled) or clearly marked as an example/concept —
   no invented partners, no testimonials attributed to real or fictional
   people, no fabricated impact numbers. */
import { api } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { CATEGORY_LABELS } from './feed.js';
import { t } from './i18n.js';

/* ── OUR IMPACT ──
   Real resolved-complaint data now. The single highest-priority resolved
   complaint gets a big editorial pull-quote treatment above the rest. */
let impactLoaded = false;
export async function loadImpactPage() {
  const quoteEl = document.getElementById('gi-happy-quote');
  const list = document.getElementById('gi-happy-list');
  if (impactLoaded) return;
  list.innerHTML = loadingPlaceholder();
  try {
    const stats = await api('/stats/nationwide');
    document.getElementById('impact-stat-resolved').textContent = stats.resolved.toLocaleString();
    document.getElementById('impact-stat-critical').textContent = stats.critical.toLocaleString();
  } catch (err) { /* stat blocks are supplementary — fail quietly */ }

  try {
    const items = await api('/complaints?scope=trending&status_filter=resolved&sort=priority&per_page=7');
    if (!items.length) {
      quoteEl.innerHTML = '';
      list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('gi.happy.empty')}</div>`;
      return;
    }
    const [featured, ...rest] = items;
    const featuredText = featured.text_translated || featured.text_original || '';
    quoteEl.innerHTML = `
      <div class="gi-quote-block">
        <div class="gi-quote-mark">"</div>
        <div class="gi-quote-text">${escapeHtml(featuredText.slice(0, 220))}${featuredText.length > 220 ? '…' : ''}</div>
        <div class="gi-quote-byline">${escapeHtml(CATEGORY_LABELS[featured.category] || 'Issue')} · ${t('stat.resolved')}</div>
      </div>`;
    list.innerHTML = rest.length ? `<div class="gi-happy-grid">${rest.map(c => `
      <div class="gi-happy-card">
        <div class="gi-happy-check">✓</div>
        <div class="gi-happy-text">${escapeHtml((c.text_translated || c.text_original || '').slice(0, 140))}${(c.text_translated || c.text_original || '').length > 140 ? '…' : ''}</div>
        <div class="gi-happy-meta">${escapeHtml(CATEGORY_LABELS[c.category] || 'Issue')} · ${t('stat.resolved')}</div>
      </div>`).join('')}</div>` : '';
    impactLoaded = true;
  } catch (err) {
    list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--critical);font-size:13px;">${escapeHtml(err.message)}</div>`;
  }
}

/* Supporter marquee strip — the "backed by" scroll seen on startup sites.
   Clearly names are placeholders (DEMO), not real backers — duplicated
   once so the CSS animation loops seamlessly. */
const DEMO_SUPPORTERS = ['GreenStep Foundation', 'Clean City Co-op', 'BuildRight Infra', 'Ward 12 Volunteers', 'CivicFirst Trust'];
let supporterStripBuilt = false;
function buildSupporterStrip() {
  const track = document.getElementById('supporter-track');
  if (!track || supporterStripBuilt) return;
  supporterStripBuilt = true;
  const label = t('gi.demo.ribbon');
  const items = [...DEMO_SUPPORTERS, ...DEMO_SUPPORTERS]
    .map(name => `<span>${escapeHtml(name)} <span style="opacity:0.5;">(${label})</span></span>`).join('');
  track.innerHTML = items;
}

export function sendVolunteerInterest() {
  const name = document.getElementById('gi-vol-name').value.trim();
  const email = document.getElementById('gi-vol-email').value.trim();
  const city = document.getElementById('gi-vol-city').value.trim();
  const interest = document.getElementById('gi-vol-interest').value;
  if (!name || !email) { showToast(t('gi.vol.needfields')); return; }

  const subject = encodeURIComponent(`NagarVaani volunteer interest — ${name}`);
  const body = encodeURIComponent(
    `Name: ${name}\nEmail: ${email}\nCity/area: ${city || '—'}\nInterested in: ${interest}\n`
  );
  window.location.href = `mailto:nagarvaani.gdg@gmail.com?subject=${subject}&body=${body}`;
}

export function sendOrgPartnerInterest() {
  const subject = encodeURIComponent('NagarVaani organization partnership interest');
  const body = encodeURIComponent('Organization name:\nType (NGO / corporate CSR / business):\nHow you\'d like to help:\nContact person:\n');
  window.location.href = `mailto:nagarvaani.gdg@gmail.com?subject=${subject}&body=${body}`;
}

/* Example galleries — real, subject-matched photography from Pexels (free
   to hotlink under their license), picked by hand for actual relevance:
   real garbage/landfill/street-cleaning/volunteer photos, not generic
   unrelated stock. Captions still say "example" since these aren't
   NagarVaani's own documented before/afters — but the imagery itself is
   real and on-topic. Rendered as a vertical stack of big showcase cards
   (soft shadow, alternating tone, slight tilt) — built once per container.
   Deliberately no scroll-triggered reveal animation: with this many real
   photos on one page, IntersectionObserver timing got unreliable and cards
   could be stuck invisible — visibility isn't worth trading for a flourish. */
const PEXELS = (id) => `https://images.pexels.com/photos/${id}/pexels-photo-${id}.jpeg?auto=compress&cs=tinysrgb&w=900`;

const BEFORE_AFTER_ITEMS = [
  // Real Indian street littered with garbage -> real bagged/collected waste
  { before: PEXELS(2382894), after: PEXELS(11529940), captionKey: 'gi.gallery.ba1' },
  // Real overflowing landfill waste -> real street being actively swept clean
  { before: PEXELS(3174347), after: PEXELS(10094811), captionKey: 'gi.gallery.ba2' },
  // Real drain/gutter grate -> real volunteers planting a sapling
  { before: PEXELS(10419020), after: PEXELS(11130997), captionKey: 'gi.gallery.ba3' },
];

function buildBeforeAfterGrid() {
  const grid = document.getElementById('gi-ba-grid');
  if (!grid || grid.dataset.built) return;
  grid.dataset.built = '1';
  grid.innerHTML = BEFORE_AFTER_ITEMS.map((item) => `
    <div class="gi-showcase-card">
      <div class="gi-showcase-ba-imgs">
        <div class="gi-showcase-ba-half"><span class="gi-showcase-tag">BEFORE</span><img src="${item.before}" alt="" loading="lazy" /></div>
        <div class="gi-showcase-ba-half"><span class="gi-showcase-tag">AFTER</span><img src="${item.after}" alt="" loading="lazy" /></div>
      </div>
      <div class="gi-showcase-foot"><div class="gi-showcase-caption">${t(item.captionKey)}</div></div>
    </div>`).join('');
}

const SHOUTOUT_ITEMS = [
  { src: PEXELS(11583513), captionKey: 'gi.gallery.shout1' },   // volunteer cleaning a beach, solo
  { src: PEXELS(12079506), captionKey: 'gi.gallery.shout2' },   // group of volunteers cleaning a beach
  { src: PEXELS(13183243), captionKey: 'gi.gallery.shout3' },   // sanitation worker sorting recyclables
  { src: PEXELS(10807130), captionKey: 'gi.gallery.shout4' },   // street sweeper at work
];

function buildShoutoutGrid() {
  const grid = document.getElementById('gi-shoutout-grid');
  if (!grid || grid.dataset.built) return;
  grid.dataset.built = '1';
  grid.innerHTML = SHOUTOUT_ITEMS.map((item) => `
    <div class="gi-showcase-card">
      <div class="gi-showcase-img-wrap"><img src="${item.src}" alt="" loading="lazy" /></div>
      <div class="gi-showcase-foot">
        <div class="gi-showcase-caption">${t(item.captionKey)}</div>
        <div class="gi-showcase-sub">🎉 ${t('gi.gallery.example')}</div>
      </div>
    </div>`).join('');
}

const GALLERY_ITEMS = [
  { src: PEXELS(11115607), captionKey: 'gi.gallery.cap1' },  // municipal garbage collection truck
  { src: PEXELS(11130997), captionKey: 'gi.gallery.cap2' },  // kids planting a tree
  { src: PEXELS(10419020), captionKey: 'gi.gallery.cap3' },  // drain/gutter grate
  { src: PEXELS(11529940), captionKey: 'gi.gallery.cap4' },  // bagged collected waste
];

let galleryBuilt = false;
export function initOrgSupportPage() {
  buildSupporterStrip();
  buildBeforeAfterGrid();
  buildShoutoutGrid();

  const grid = document.getElementById('gi-ig-grid');
  if (!grid || galleryBuilt) return;
  galleryBuilt = true;

  grid.innerHTML = GALLERY_ITEMS.map((item) => `
    <div class="gi-showcase-card">
      <div class="gi-showcase-img-wrap"><img src="${item.src}" alt="" loading="lazy" /></div>
      <div class="gi-showcase-foot">
        <div class="gi-showcase-caption">${t(item.captionKey)}</div>
        <div class="gi-showcase-sub">🤍 ${t('gi.gallery.example')}</div>
      </div>
    </div>`).join('');
}
