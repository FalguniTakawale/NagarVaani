/* Near Me — a real map of what's around the user, not the ward feed again.
   Pins come from GET /api/stats/map (all geotagged complaints) and are cut to
   the radius client-side; the list comes from GET /api/complaints?scope=nearby
   which does the same cut server-side and returns distance_km per row. */
import { api } from './api.js';
import { showToast, escapeHtml, loadingPlaceholder } from './ui.js';
import { renderComplaintCard } from './feed.js';
import { t } from './i18n.js';

const state = { lat: null, lng: null, radius: 3, sort: 'distance', place: null, denied: false };
let map = null, youMarker = null, radiusCircle = null, pinLayer = null;
let lastPoints = null;

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
  if (state.lat !== null) { renderAll(); return; }
  locate();
}

export function refreshNearMe() {
  state.place = null;
  locate(true);
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
   works; if that fails, fall back to a text filter on the backend. */
export async function nearMeManual() {
  const q = document.getElementById('nearme-manual-input').value.trim();
  if (!q) return;
  const list = document.getElementById('nearme-feed-list');
  list.innerHTML = loadingPlaceholder();
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&countrycodes=in&format=json&limit=1`);
    const hits = await res.json();
    if (hits.length) {
      state.place = hits[0].display_name.split(',').slice(0, 2).join(',');
      setPosition(parseFloat(hits[0].lat), parseFloat(hits[0].lon), { keepPlace: true });
      return;
    }
  } catch (_) { /* fall through to text filter */ }
  // Text filter, no map
  try {
    const items = await api(`/complaints?scope=nearby&near_text=${encodeURIComponent(q)}&sort=priority&per_page=50`);
    document.getElementById('nearme-subtitle').textContent = items.length
      ? `${items.length} · "${q}"` : t('nearme.notfound');
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
  try {
    if (!lastPoints) lastPoints = await api('/stats/map?scope=national&limit=2000');
  } catch (err) {
    lastPoints = [];
  }
  pinLayer.clearLayers();
  lastPoints
    .map(p => ({ ...p, d: haversineKm(state.lat, state.lng, p.lat, p.lng) }))
    .filter(p => p.d <= state.radius)
    .forEach(p => {
      const color = p.score >= 80 ? '#DC2626' : p.score >= 55 ? '#D97706' : '#16A34A';
      L.circleMarker([p.lat, p.lng], { radius: 6 + (p.score / 100) * 10, color: 'white', weight: 2, fillColor: color, fillOpacity: 0.85 })
        .bindPopup(`<div style="font:13px Inter,sans-serif;max-width:220px">
            <b>${escapeHtml(p.label)}</b><br>
            <span style="color:${color};font-weight:700">Score ${Math.round(p.score)}</span> · ${fmtKm(p.d)}<br>
            <a href="#" onclick="openComplaint('${p.id}');return false;" style="color:#2563EB">Open →</a></div>`)
        .addTo(pinLayer);
    });
}

async function loadList() {
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
