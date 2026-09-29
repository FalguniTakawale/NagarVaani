/* Near Me — a real map of what's around the user, not the ward feed again.
   Pins come from GET /api/stats/map (all geotagged complaints) and are cut to
   the radius client-side; the list comes from GET /api/complaints?scope=nearby
   which does the same cut server-side and returns distance_km per row. */
import { api } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { renderComplaintCard, CATEGORY_LABELS } from './feed.js';
import { t } from './i18n.js';

// Pin color = priority (matches the score badge colors everywhere else in
// the app); pin icon = issue type. Two channels on one marker so a glance at
// the map answers "how urgent" and "what kind" at once, not just "how far".
const CATEGORY_ICON = {
  drainage: '💧', road: '🛣️', garbage: '🗑️', electricity: '⚡',
  tree_hazard: '🌳', water_supply: '🚰', other: '📍',
};

const state = { lat: null, lng: null, radius: 3, sort: 'distance', place: null, denied: false, heatmap: false };
let map = null, youMarker = null, radiusCircle = null, pinLayer = null;
let heatCanvas = null, heatPoints = [];
let lastPoints = [];
let pollTimer = null;

const ZOOM_FOR_RADIUS = { 1: 15, 3: 14, 5: 13, 10: 12 };

export function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371, toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1), dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function fmtKm(d) { return d < 1 ? `${Math.round(d * 1000)} m` : `${d.toFixed(1)} km`; }

/* ── entry ── */
export function loadNearMe() {
  loadWeeklyResolved();
  startNearMePolling();
  if (state.lat !== null) { renderAll(); return; }
  locate();
}

export function refreshNearMe() {
  state.place = null;
  locate(true);
}

// The manual location form used to appear ONLY when GPS genuinely failed —
// but most laptops/desktops resolve *some* location via GPS/IP even without
// a precise fix, so if geolocation succeeds (returning wherever the device
// actually is, which is meaningless for testing an India-focused app from
// outside India), the form never showed and there was no other way to pick
// a specific city to test with. This always reveals it on demand instead of
// toggling — a toggle read ambiguously once GPS had already auto-shown it.
export function showNearMeManual() {
  document.getElementById('nearme-manual').hidden = false;
  setTimeout(() => document.getElementById('nearme-manual-input').focus(), 50);
}

export function hideNearMeManual() {
  document.getElementById('nearme-manual').hidden = true;
}

// Real-time reactivity: a complaint resolved by an official while this page
// is open should disappear from the map/list without the user reloading.
// /stats/map already excludes resolved by default — polling just re-asks it
// periodically instead of caching the first answer forever.
export function stopNearMePolling() {
  clearInterval(pollTimer);
  pollTimer = null;
}

function startNearMePolling() {
  stopNearMePolling();
  pollTimer = setInterval(() => {
    const active = document.getElementById('page-nearme').classList.contains('active');
    if (!active) { stopNearMePolling(); return; }
    if (state.lat !== null) { loadPins(); loadList(); }
  }, 30_000);
}

function locate(force = false) {
  const sub = document.getElementById('nearme-subtitle');
  sub.textContent = t('nearme.locating');
  document.getElementById('nearme-manual').hidden = true;
  if (!navigator.geolocation) { onDenied(); return; }
  navigator.geolocation.getCurrentPosition(
    pos => { state.denied = false; setPosition(pos.coords.latitude, pos.coords.longitude); },
    () => onDenied(),
    { enableHighAccuracy: true, timeout: 8000, maximumAge: force ? 0 : 60_000 }
  );
}

function onDenied() {
  state.denied = true;
  document.getElementById('nearme-subtitle').textContent = t('nearme.denied');
  document.getElementById('nearme-manual').hidden = false;
  document.getElementById('nearme-feed-list').innerHTML = '';
  setTimeout(() => document.getElementById('nearme-manual-input').focus(), 50);
}

/* GPS denied: geocode the typed place with Nominatim so the same radius flow
   works; if that fails, fall back to a text filter on the backend.

   City/State matter here because plain free-text search is genuinely
   ambiguous — "S B Road" (Senapati Bapat Road) exists in several Indian
   cities, and Nominatim's top-ranked global match for it is Mumbai's, not
   Pune's, with no way to tell from the area name alone. Passing city/state
   as Nominatim's own *structured* query fields (not just appended text)
   scopes the search server-side instead of hoping the free-text ranking
   guesses right. */
export async function nearMeManual() {
  const q = document.getElementById('nearme-manual-input').value.trim();
  if (!q) return;
  const city = document.getElementById('nearme-manual-city').value.trim();
  const stateName = document.getElementById('nearme-manual-state').value;
  const list = document.getElementById('nearme-feed-list');
  list.innerHTML = loadingPlaceholder();
  try {
    const params = city
      ? new URLSearchParams({ street: q, city, state: stateName, country: 'India', format: 'json', limit: '1' })
      : new URLSearchParams({ q, countrycodes: 'in', format: 'json', limit: '1' });
    const res = await fetch(`https://nominatim.openstreetmap.org/search?${params.toString()}`);
    let hits = await res.json();
    // A street name Nominatim doesn't have indexed for that exact city (common
    // for smaller lanes) returns nothing structured — retry as free text
    // scoped by appending city/state, still far better than no scoping at all.
    if (!hits.length && city) {
      const fallback = new URLSearchParams({ q: `${q}, ${city}, ${stateName}, India`, countrycodes: 'in', format: 'json', limit: '1' });
      const res2 = await fetch(`https://nominatim.openstreetmap.org/search?${fallback.toString()}`);
      hits = await res2.json();
    }
    if (hits.length) {
      state.place = hits[0].display_name.split(',').slice(0, 2).join(',');
      setPosition(parseFloat(hits[0].lat), parseFloat(hits[0].lon), { keepPlace: true });
      return;
    }
  } catch (_) { /* fall through to text filter */ }
  // Text filter, no map — city (if given) scopes it server-side too, same
  // reasoning as the structured geocode attempt above.
  try {
    const textParams = new URLSearchParams({ scope: 'nearby', near_text: q, sort: 'priority', per_page: '50' });
    if (city) textParams.set('city', city);
    const items = await api(`/complaints?${textParams.toString()}`);
    document.getElementById('nearme-subtitle').textContent = items.length
      ? `${items.length} · "${q}"${city ? ', ' + city : ''}` : t('nearme.notfound');
    list.innerHTML = items.length ? items.map(c => renderComplaintCard(c)).join('') : '';
  } catch (err) {
    list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--critical);font-size:13px;">${escapeHtml(err.message)}</div>`;
  }
}

function setPosition(lat, lng, { keepPlace = false } = {}) {
  state.lat = lat; state.lng = lng;
  if (!keepPlace) state.place = null;
  renderAll();
  if (!state.place) reverseGeocode(lat, lng);
}

async function reverseGeocode(lat, lng) {
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&zoom=16`);
    const j = await res.json();
    const a = j.address || {};
    state.place = a.neighbourhood || a.suburb || a.village || a.town || a.city_district || a.city || a.county || null;
  } catch (_) {
    state.place = null;
  }
  updateSubtitle();
}

/* ── controls ── */
export function setNearMeRadius(km, btn) {
  state.radius = km;
  document.querySelectorAll('#nearme-radius-group .radius-btn').forEach(b => b.classList.toggle('active', b === btn));
  renderAll();
}

export function setNearMeSort(sort, btn) {
  state.sort = sort;
  document.querySelectorAll('#nearme-sort-group .sort-btn').forEach(b => b.classList.toggle('active', b === btn));
  loadList();
}

/* ── rendering ── */
let lastCount = 0;
function updateSubtitle() {
  if (state.lat === null) return;
  document.getElementById('nearme-subtitle').textContent =
    t('nearme.within', { n: lastCount, r: state.radius, place: state.place || t('nearme.here') });
}

function renderAll() {
  // Guards against a sort/radius click racing ahead of geolocation resolving —
  // without this, loadList() below would send lat/lng as the literal string
  // "null" (URLSearchParams stringifies JS null), which the backend then
  // rejects with a float-parsing 422 instead of just doing nothing quietly.
  if (state.lat === null) return;
  ensureMap();
  map.setView([state.lat, state.lng], ZOOM_FOR_RADIUS[state.radius] || 14);
  youMarker.setLatLng([state.lat, state.lng]);
  radiusCircle.setLatLng([state.lat, state.lng]).setRadius(state.radius * 1000);
  loadPins();
  loadList();
}

function ensureMap() {
  if (map || typeof L === 'undefined') { if (map) setTimeout(() => map.invalidateSize(), 60); return; }
  map = L.map('nearme-map', { zoomControl: true, attributionControl: false }).setView([20.59, 78.96], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
  youMarker = L.circleMarker([0, 0], { radius: 9, color: '#F5A623', weight: 3, fillColor: '#0F2042', fillOpacity: 1 }).addTo(map);
  radiusCircle = L.circle([0, 0], { radius: 3000, color: '#2563EB', weight: 1, fillColor: '#2563EB', fillOpacity: 0.06 }).addTo(map);
  pinLayer = L.layerGroup().addTo(map);
  setTimeout(() => map.invalidateSize(), 60);
}

async function loadPins() {
  // Always refetch — a permanent cache here meant a complaint resolved by
  // an official mid-session never disappeared from the map until a full
  // page reload, even with the "you're on the open-only endpoint" default
  // already doing its job server-side.
  try {
    lastPoints = await api('/stats/map?scope=national&limit=2000');
  } catch (err) {
    lastPoints = [];
  }
  const nearby = lastPoints
    .map(p => ({ ...p, d: haversineKm(state.lat, state.lng, p.lat, p.lng) }))
    .filter(p => p.d <= state.radius);

  if (state.heatmap) {
    if (map.hasLayer(pinLayer)) map.removeLayer(pinLayer);
    renderHeatmap(nearby);
    return;
  }
  clearHeatmap();
  if (!map.hasLayer(pinLayer)) pinLayer.addTo(map);

  pinLayer.clearLayers();
  nearby
    .forEach(p => {
      const color = p.score >= 80 ? '#DC2626' : p.score >= 55 ? '#D97706' : '#16A34A';
      const catLabel = CATEGORY_LABELS[p.category] || 'Other';
      const icon = L.divIcon({
        className: 'map-pin',
        html: `<div class="map-pin-dot" style="background:${color}">${CATEGORY_ICON[p.category] || CATEGORY_ICON.other}</div>`,
        iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -13],
      });
      L.marker([p.lat, p.lng], { icon })
        .bindPopup(`<div style="font:13px Inter,sans-serif;max-width:220px">
            <b>${escapeHtml(p.label)}</b><br>
            <span class="map-pin-tag">${CATEGORY_ICON[p.category] || CATEGORY_ICON.other} ${escapeHtml(catLabel)}</span><br>
            <span style="color:${color};font-weight:700">Score ${Math.round(p.score)}</span> · ${fmtKm(p.d)}<br>
            <a href="#" onclick="openComplaint('${p.id}');return false;" style="color:#2563EB">Open →</a></div>`)
        .addTo(pinLayer);
    });
}

// Density view — real complaint locations/scores feed the heat, same data
// as the pins, just a different lens on it ("where is it busy" vs "what's
// each one"). Hand-rolled on a plain <canvas> instead of the leaflet.heat
// plugin: verified via a standalone test that leaflet.heat 0.2.0 against
// Leaflet 1.9.4 adds its layer successfully (hasLayer() true) but paints
// zero visible pixels — a real library incompatibility, not a data issue.
// This draws a soft radial gradient per point, colored the same red/amber/
// green as the pins, so it also still reads as a priority signal.
function ensureHeatCanvas() {
  if (heatCanvas) return;
  heatCanvas = L.DomUtil.create('canvas', 'nearme-heat-canvas');
  heatCanvas.style.pointerEvents = 'none';
  map.getPanes().overlayPane.appendChild(heatCanvas);
  map.on('move zoom resize', drawHeat);
}

function drawHeat() {
  if (!heatCanvas || !map) return;
  const size = map.getSize();
  heatCanvas.width = size.x;
  heatCanvas.height = size.y;
  L.DomUtil.setPosition(heatCanvas, map.containerPointToLayerPoint([0, 0]));
  const ctx = heatCanvas.getContext('2d');
  ctx.clearRect(0, 0, size.x, size.y);
  heatPoints.forEach(p => {
    const pt = map.latLngToContainerPoint([p.lat, p.lng]);
    const radius = 45;
    const color = p.score >= 80 ? '220,38,38' : p.score >= 55 ? '217,119,6' : '22,163,74';
    const intensity = Math.max(0.35, p.score / 100);
    const grad = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, radius);
    grad.addColorStop(0, `rgba(${color},${0.6 * intensity})`);
    grad.addColorStop(1, `rgba(${color},0)`);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, radius, 0, Math.PI * 2);
    ctx.fill();
  });
}

function clearHeatmap() {
  if (!heatCanvas) return;
  const ctx = heatCanvas.getContext('2d');
  ctx.clearRect(0, 0, heatCanvas.width, heatCanvas.height);
}

function renderHeatmap(points) {
  ensureHeatCanvas();
  heatPoints = points;
  if (!points.length) showToast(t('nearme.heatmap.empty'));
  drawHeat();
}

export function toggleHeatmap(btn) {
  state.heatmap = !state.heatmap;
  btn.classList.toggle('active', state.heatmap);
  btn.textContent = state.heatmap ? t('nearme.heatmap.on') : t('nearme.heatmap.off');
  loadPins();
}

async function loadList() {
  if (state.lat === null) return;  // same race as renderAll() — see its comment
  const list = document.getElementById('nearme-feed-list');
  list.innerHTML = loadingPlaceholder();
  try {
    const params = new URLSearchParams({ scope: 'nearby', lat: state.lat, lng: state.lng, radius_km: state.radius, sort: state.sort, per_page: 50 });
    const items = await api('/complaints?' + params.toString());
    lastCount = items.length;
    updateSubtitle();
    if (!items.length) {
      list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--slate);font-size:13px;">${t('nearme.none', { r: state.radius })}</div>`;
      return;
    }
    list.innerHTML = items.map(c => {
      const d = c.distance_km ?? (c.latitude != null ? haversineKm(state.lat, state.lng, c.latitude, c.longitude) : null);
      const badge = d != null ? `<div class="distance-badge">📍 ${t('nearme.away', { d: fmtKm(d) })}</div>` : '';
      return renderComplaintCard(c, { underTitle: badge });
    }).join('');
  } catch (err) {
    list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--critical);font-size:13px;">${escapeHtml(err.message)}</div>`;
    showToast(err.message);
  }
}

/* ── "X fixed this week" widget ──
   Real StatusLog-derived counts (see /stats/resolved-this-week) — genuinely
   shows 0 rather than a made-up number when nothing's been resolved yet. */
async function loadWeeklyResolved() {
  const el = document.getElementById('nearme-weekly-resolved');
  if (!el) return;
  try {
    const data = await api('/stats/resolved-this-week');
    if (!data.total) {
      el.textContent = t('nearme.weekly.none');
      return;
    }
    const top = data.breakdown[0];
    const topLabel = CATEGORY_LABELS[top.category] || 'Other';
    el.textContent = t('nearme.weekly.some', { n: data.total, cat: topLabel });
  } catch (_) {
    el.textContent = '';
  }
}

/* ── "My Neighborhood" email alerts ── */
export async function subscribeNeighborhood() {
  const emailInput = document.getElementById('nearme-sub-email');
  const btn = document.getElementById('nearme-sub-btn');
  const email = (emailInput.value || '').trim();
  if (!email || !email.includes('@')) { showToast(t('nearme.sub.invalidemail')); return; }
  if (state.lat === null) { showToast(t('nearme.sub.needlocation')); return; }

  btn.disabled = true;
  try {
    await api('/subscriptions/neighborhood', {
      method: 'POST',
      body: JSON.stringify({
        email, latitude: state.lat, longitude: state.lng,
        radius_km: state.radius, label: state.place || null,
      }),
    });
    showToast(t('nearme.sub.done'));
    emailInput.value = '';
  } catch (err) {
    showToast(err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ── Guided tutorial overlay — first-time-visitor walkthrough ── */
const TUTORIAL_STEPS = ['pins', 'radius', 'heatmap', 'subscribe'];
let tutorialStep = 0;

export function showNearMeTutorial() {
  tutorialStep = 0;
  document.getElementById('nearme-tutorial-overlay').hidden = false;
  renderTutorialStep();
}

export function closeNearMeTutorial() {
  document.getElementById('nearme-tutorial-overlay').hidden = true;
}

export function nearMeTutorialStep(delta) {
  tutorialStep = Math.min(Math.max(tutorialStep + delta, 0), TUTORIAL_STEPS.length - 1);
  renderTutorialStep();
}

function renderTutorialStep() {
  TUTORIAL_STEPS.forEach((key, i) => {
    const el = document.getElementById('tutorial-step-' + key);
    if (el) el.hidden = i !== tutorialStep;
  });
  document.querySelectorAll('#nearme-tutorial-dots .tutorial-dot').forEach((d, i) => d.classList.toggle('active', i === tutorialStep));
  document.getElementById('tutorial-back-btn').hidden = tutorialStep === 0;
  document.getElementById('tutorial-next-btn').textContent = tutorialStep === TUTORIAL_STEPS.length - 1 ? t('tutorial.done') : t('tutorial.next');
}

export function nearMeTutorialNext() {
  if (tutorialStep === TUTORIAL_STEPS.length - 1) { closeNearMeTutorial(); return; }
  nearMeTutorialStep(1);
}
