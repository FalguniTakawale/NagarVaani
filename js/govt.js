import { api, authUser, requireLogin } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { CATEGORY_LABELS } from './feed.js';

const OFFICIAL_LEVEL_LABELS = {
  ward_officer: 'Ward officer', municipal: 'Municipal commissioner', district: 'District collector',
  state: 'State official', central: 'Central ministry',
};

function jurisdictionLabel() {
  if (!authUser) return 'Ward 12 (demo)';
  const level = authUser.official_level;
  if (level === 'central') return 'Nationwide';
  if (level === 'state') return authUser.state || 'State';
  if (level === 'municipal' || level === 'district') return authUser.city || 'City';
  return authUser.ward ? `Ward ${authUser.ward}` : 'Ward';
}

let govtLoadedOnce = false;
export async function loadGovtDashboard() {
  document.getElementById('scope-btn-ward').textContent = jurisdictionLabel();

  // Default landing view respects jurisdiction — state/central officials land on
  // the national tab, everyone else lands on their own jurisdiction. This is a
  // *default*, not a restriction: the toggle stays clickable either way.
  if (!govtLoadedOnce && authUser && ['state', 'central'].includes(authUser.official_level)) {
    govtLoadedOnce = true;
    setGovtScope('national');
    return;
  }
  govtLoadedOnce = true;

  const useJurisdiction = authUser && authUser.role === 'official';
  const scopeParam = useJurisdiction ? 'jurisdiction' : 'ward';
  const wardFallback = '12';

  try {
    const statsUrl = useJurisdiction && authUser.official_level === 'ward_officer'
      ? `/stats/ward?ward=${encodeURIComponent(authUser.ward || wardFallback)}`
      : `/stats/ward?ward=${encodeURIComponent(authUser && authUser.ward ? authUser.ward : wardFallback)}`;
    const stats = await api(statsUrl);
    document.getElementById('govt-stat-critical').textContent = stats.critical;
    document.getElementById('govt-stat-inprogress').textContent = stats.in_progress;
    document.getElementById('govt-stat-resolved').textContent = stats.resolved;
    document.getElementById('govt-stat-open').textContent = stats.open;
  } catch (err) {
    showToast(err.message);
  }

  const list = document.getElementById('govt-briefs-list');
  if (!list.children.length || list.dataset.live === '1') list.innerHTML = loadingPlaceholder('Loading briefs…');
  try {
    const complaints = await api(`/complaints?scope=${scopeParam}&sort=priority&status_filter=open`);
    list.dataset.live = '1';
    if (!complaints.length) {
      list.innerHTML = `<div style="padding:16px;color:var(--slate);font-size:13px;">No open complaints in ${jurisdictionLabel()} right now.</div>`;
      return;
    }
    // Tier 1 — jurisdiction, severity-ranked. Tier 2/3 render once a brief is opened in detail.
    list.innerHTML = complaints.map(c => `
      <div class="brief-card ${c.priority_score >= 80 ? 'urgent' : ''}">
        <div class="brief-top">
          <div class="brief-title">${escapeHtml((c.text_translated || c.text_original).slice(0, 90))}</div>
          <div style="text-align:right;"><div class="brief-score" style="${c.priority_score < 80 ? 'color:var(--warn)' : ''}">${Math.round(c.priority_score)}</div><div class="brief-score-label">AI SCORE</div></div>
        </div>
        <div class="brief-summary">Category: ${CATEGORY_LABELS[c.category] || 'Other'} · ${c.vote_count} votes · ${c.linked_area_count} linked areas.</div>
        <div class="brief-footer">
          <div class="brief-action-btns">
            <button class="b-btn primary" onclick="markInProgress('${c.id}', this)">Mark in progress</button>
            <button class="b-btn secondary" onclick="endorseComplaint('${c.id}')">Endorse</button>
            <button class="b-btn secondary" onclick="openComplaint('${c.id}')">View detail</button>
          </div>
        </div>
      </div>`).join('');
  } catch (err) {
    if (list.querySelector('.loading-state')) {
      list.innerHTML = `<div style="padding:16px;color:var(--critical);font-size:13px;">Couldn't load briefs — ${escapeHtml(err.message)}</div>`;
    }
    showToast(err.message);
  }
}

export async function endorseComplaint(id) {
  if (!requireLogin('Log in as an official to endorse')) return;
  if (!authUser || authUser.role !== 'official') { showToast('Only officials can endorse — this signal carries more weight than a citizen vote'); return; }
  try {
    // Endorsement currently rides the same solidarity-vote path with an official's
    // token — it is flagged is_solidarity so it's visibly distinct from a local vote.
    // A dedicated weighted endorsement multiplier is the next scoring iteration.
    const result = await api(`/complaints/${id}/vote`, { method: 'POST', body: JSON.stringify({ is_solidarity: true }) });
    showToast(`Endorsed for escalation — score ${result.new_score}`);
  } catch (err) {
    showToast(err.message);
  }
}

export async function markInProgress(id, btn) {
  if (!requireLogin('Log in as an official to update status')) return;
  try {
    await api(`/complaints/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status: 'in_progress' }) });
    showToast('Status: In progress');
    btn.closest('.brief-card').style.opacity = '0.6';
  } catch (err) {
    showToast(err.status === 403 ? 'Only officials can update status' : err.message);
  }
}

/* ── HOTSPOT MAPS — live data from GET /api/stats/map ── */
export function setGovtScope(scope) {
  document.getElementById('govt-view-ward').classList.toggle('active', scope === 'ward');
  document.getElementById('govt-view-national').classList.toggle('active', scope === 'national');
  document.getElementById('scope-btn-ward').classList.toggle('active', scope === 'ward');
  document.getElementById('scope-btn-national').classList.toggle('active', scope === 'national');
  setTimeout(initGovtMaps, 50);
}

let wardMap = null, nationalMap = null;
export async function initGovtMaps() {
  if (typeof L === 'undefined') return;

  const wardEl = document.getElementById('hotspot-map-ward');
  if (wardEl && wardEl.offsetParent !== null && !wardMap) {
    wardMap = L.map(wardEl, { zoomControl: false, attributionControl: false }).setView([18.5679, 73.8087], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(wardMap);
    await loadHotspots(wardMap, { scope: 'ward', ward: (authUser && authUser.ward) || '12' });
  }
  if (wardMap) setTimeout(() => wardMap.invalidateSize(), 100);

  const natEl = document.getElementById('hotspot-map-national');
  if (natEl && natEl.offsetParent !== null && !nationalMap) {
    nationalMap = L.map(natEl, { zoomControl: false, attributionControl: false }).setView([20.5937, 78.9629], 4.3);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(nationalMap);
    await loadHotspots(nationalMap, { scope: 'national' });
  }
  if (nationalMap) setTimeout(() => nationalMap.invalidateSize(), 100);
}

// Fallback points, shown only if the backend has no geotagged complaints yet
// (empty seed DB) or is unreachable — so the map isn't blank during a demo.
const DEMO_HOTSPOTS = {
  ward: [
    { lat: 18.5308, lng: 73.8479, score: 94, label: 'Shivaji Nagar drain · 8 linked areas' },
    { lat: 18.5362, lng: 73.8079, score: 88, label: 'Koregaon Park fallen tree' },
    { lat: 18.5590, lng: 73.7868, score: 61, label: 'Baner Road pothole cluster' },
  ],
  national: [
    { lat: 25.7521, lng: 71.3962, score: 96, label: 'Barmer, Rajasthan — well contamination, 280 families' },
    { lat: 18.5308, lng: 73.8479, score: 92, label: 'Pune, Maharashtra — monsoon drainage, 14 wards' },
    { lat: 20.9374, lng: 77.7796, score: 89, label: 'Amravati, Vidarbha — heatwave power cuts' },
    { lat: 12.9698, lng: 77.7500, score: 72, label: 'Whitefield, Bengaluru — arterial road' },
  ],
};

async function loadHotspots(map, { scope, ward }) {
  try {
    const params = new URLSearchParams({ scope });
    if (ward) params.set('ward', ward);
    const points = await api(`/stats/map?${params.toString()}`);
    const hotspots = points.length
      ? points.map(p => ({
          lat: p.lat, lng: p.lng, score: p.score,
          label: `${p.label} · ${CATEGORY_LABELS[p.category] || 'Other'}${p.linked_area_count ? ` · ${p.linked_area_count} linked areas` : ''}`,
        }))
      : DEMO_HOTSPOTS[scope];
    hotspots.forEach(h => addHotspotMarker(map, h));
  } catch (err) {
    DEMO_HOTSPOTS[scope].forEach(h => addHotspotMarker(map, h));
  }
}

function addHotspotMarker(map, h) {
  const color = h.score >= 85 ? '#DC2626' : h.score >= 65 ? '#D97706' : '#16A34A';
  const radius = 8 + (h.score / 100) * 14;
  L.circleMarker([h.lat, h.lng], {
    radius, color: 'white', weight: 2, fillColor: color, fillOpacity: 0.75
  }).bindTooltip(h.label + ' · score ' + h.score).addTo(map);
}
