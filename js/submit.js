import { micLanguage } from './voice.js';
import { api, authUser } from './api.js';
import { showToast, escapeHtml } from './ui.js';
import { nav } from './nav.js';
import { t } from './i18n.js';

/* ── LOCATION CAPTURE ──
   Complaint.latitude/longitude are what feed the hotspot map (GET /api/stats/map) —
   without them a complaint never shows up as a map point, only in the list feeds. */
let capturedLat = null;
let capturedLng = null;

// A signed-in account's saved city/state used to fully replace the manual
// fields with no way back — fine for the common case, but there was no way
// to file a complaint about a *different* place than your registered one
// without editing your profile first. This flag lets "Change it" reveal the
// real dropdowns and have them actually win at submit time.
let cityStateOverride = false;

export function captureLocation() {
  const label = document.getElementById('loc-btn-label');
  const status = document.getElementById('loc-status');

  if (!navigator.geolocation) {
    status.textContent = 'Geolocation not supported by this browser';
    return;
  }

  label.textContent = 'Locating…';
  status.textContent = '';

  navigator.geolocation.getCurrentPosition(
    async pos => {
      capturedLat = pos.coords.latitude;
      capturedLng = pos.coords.longitude;
      label.textContent = '📍 Location captured';
      status.textContent = `✓ ${capturedLat.toFixed(4)}, ${capturedLng.toFixed(4)} — looking up the area name…`;
      const place = await lookupPlace(capturedLat, capturedLng);
      if (place) {
        applyPlace(place);
        status.textContent = `✓ ${place.summary} — coordinates will be attached to this complaint`;
        showToast(`Location: ${place.summary}`);
      } else {
        status.textContent = `✓ ${capturedLat.toFixed(4)}, ${capturedLng.toFixed(4)} attached — couldn't look up the area name, please type it above`;
        showToast('Location captured — please type the area name');
      }
    },
    err => {
      label.textContent = t('submit.uselocation');
      status.textContent = err.code === err.PERMISSION_DENIED
        ? 'Location permission denied — you can still type an area/landmark above'
        : 'Could not get your location — try again or type an area/landmark above';
    },
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

/* Coordinates alone aren't useful to a reader (or to ward/city-scoped views), so turn
   them into a real place name with OpenStreetMap's Nominatim reverse geocoder — the same
   free service Near Me already uses, no key. Returns null on any failure so the user
   just types the area instead. */
async function lookupPlace(lat, lng) {
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&addressdetails=1&zoom=18&accept-language=en&lat=${lat}&lon=${lng}`);
    if (!res.ok) return null;
    const a = (await res.json()).address;
    if (!a) return null;
    const area = a.neighbourhood || a.suburb || a.quarter || a.city_district || a.residential || a.hamlet || a.village || '';
    const city = a.city || a.town || a.municipality || a.county || a.state_district || '';
    const parts = [a.road, area, city].filter((p, i, arr) => p && arr.indexOf(p) === i);
    if (!parts.length) return null;
    return { text: parts.join(', '), summary: parts.slice(-2).join(', '), city, state: a.state || '' };
  } catch (_) { return null; }
}

/* Fill the Location box (unless the user has typed their own text) and, where the
   form asks for it, the city/state — switching a signed-in user to "report for a
   different city" if GPS says they're somewhere other than their registered city. */
function applyPlace(place) {
  const box = document.getElementById('complaint-location');
  if (box && (!box.value.trim() || box.dataset.auto === '1')) {
    box.value = place.text;
    box.dataset.auto = '1';
    if (!box.dataset.watch) { box.dataset.watch = '1'; box.addEventListener('input', () => { box.dataset.auto = ''; }); }
  }
  if (!place.city) return;
  const same = (x, y) => x && y && (x.toLowerCase().includes(y.toLowerCase()) || y.toLowerCase().includes(x.toLowerCase()));
  const known = authUser && authUser.city;
  let switched = false;
  if (known && !cityStateOverride && !same(known, place.city)) { overrideSubmitCityState(); switched = true; }
  const cityInput = document.getElementById('submit-city');
  const stateSel = document.getElementById('submit-state');
  const visible = document.getElementById('submit-citystate-group').style.display !== 'none';
  if (visible && cityInput && stateSel) {
    if (place.state) {
      const opt = [...stateSel.options].find(o => same(o.value, place.state));
      if (opt) { stateSel.value = opt.value; window.onSubmitStateChange(opt.value); }
    }
    if (switched || !cityInput.value.trim() || cityInput.dataset.auto === '1') { cityInput.value = place.city; cityInput.dataset.auto = '1'; }
  }
}

function resetLocationCapture() {
  capturedLat = null;
  capturedLng = null;
  document.getElementById('loc-btn-label').textContent = t('submit.uselocation');
  document.getElementById('loc-status').textContent = '';
}

/* ── PHOTO / 360° UPLOAD ──
   Each selected file uploads to Cloudinary via POST /api/media/upload the
   moment it's picked; only files that finish uploading (uploadedUrl set)
   are attached to the complaint on submit. Captions and the 360° flag are
   edited locally and sent along in ComplaintCreate.images. */
let photos = []; // { id, file, previewUrl, uploadedUrl, caption, is360, uploading, error }
let photoIdSeq = 0;

export function handlePhotoSelect(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = ''; // allow re-selecting the same file later

  files.forEach(file => {
    const entry = {
      id: ++photoIdSeq,
      file,
      previewUrl: URL.createObjectURL(file),
      uploadedUrl: null,
      caption: '',
      is360: false,
      uploading: true,
      error: null,
    };
    photos.push(entry);
    uploadPhoto(entry);
  });
  renderPhotoPreviews();
}

async function uploadPhoto(entry) {
  try {
    const form = new FormData();
    form.append('file', entry.file);
    const result = await api('/media/upload', { method: 'POST', body: form });
    if (result.url) {
      entry.uploadedUrl = result.url;
    } else {
      entry.error = result.error || 'Upload failed';
    }
  } catch (err) {
    entry.error = err.message;
  }
  entry.uploading = false;
  renderPhotoPreviews();
}

export function setPhotoCaption(id, value) {
  const entry = photos.find(p => p.id === id);
  if (entry) entry.caption = value;
}

export function togglePhoto360(id) {
  const entry = photos.find(p => p.id === id);
  if (entry) entry.is360 = !entry.is360;
  renderPhotoPreviews();
}

export function removePhoto(id) {
  photos = photos.filter(p => p.id !== id);
  renderPhotoPreviews();
}

function renderPhotoPreviews() {
  const container = document.getElementById('photo-previews');
  const zoneLabel = document.getElementById('upload-zone-label');
  zoneLabel.textContent = photos.length
    ? `Tap to add more (${photos.length} attached)`
    : t('submit.tapadd');

  container.innerHTML = photos.map(p => `
    <div style="display:flex;gap:10px;align-items:flex-start;border:1px solid var(--border);border-radius:var(--radius);padding:10px;background:var(--surface2);">
      <div style="width:64px;height:64px;flex:none;border-radius:6px;overflow:hidden;background:var(--bg);position:relative;">
        <img src="${p.previewUrl}" style="width:100%;height:100%;object-fit:cover;" />
        ${p.uploading ? `<div style="position:absolute;inset:0;background:rgba(0,0,0,0.4);color:white;display:flex;align-items:center;justify-content:center;font-size:10px;">Uploading…</div>` : ''}
      </div>
      <div style="flex:1;min-width:0;">
        <input class="form-input" style="font-size:12px;padding:6px 8px;" placeholder="Caption — what are we looking at?"
          value="${escapeHtml(p.caption)}" oninput="setPhotoCaption(${p.id}, this.value)" />
        <div style="display:flex;align-items:center;gap:12px;margin-top:6px;font-size:11px;color:var(--slate);">
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;">
            <input type="checkbox" ${p.is360 ? 'checked' : ''} onchange="togglePhoto360(${p.id})" /> 360° image
          </label>
          ${p.error ? `<span style="color:var(--critical);">${escapeHtml(p.error)}</span>` : p.uploading ? '' : '<span style="color:var(--success);">✓ Uploaded</span>'}
          <span style="margin-left:auto;color:var(--critical);cursor:pointer;" onclick="removePhoto(${p.id})">Remove</span>
        </div>
      </div>
    </div>`).join('');
}

function resetPhotos() {
  photos.forEach(p => URL.revokeObjectURL(p.previewUrl));
  photos = [];
  renderPhotoPreviews();
}

/* ── SUBMIT ── */
export async function submitComplaint() {
  const text = document.getElementById('complaint-text').value;
  if (!text.trim()) { showToast(t('js.describefirst')); return; }
  const location_text = document.getElementById('complaint-location').value;
  if (!location_text.trim()) { showToast(t('js.locationfirst')); return; }

  // Use the account's known city/state if it has one; otherwise this
  // complaint has nowhere else to get it from, so the explicit fields are
  // required (updateSubmitAuthNotice() shows/hides them accordingly).
  const knownCity = !cityStateOverride && authUser && authUser.city;
  const knownState = !cityStateOverride && authUser && authUser.state;
  const city = knownCity || document.getElementById('submit-city').value.trim();
  const state = knownState || document.getElementById('submit-state').value.trim();
  if (!knownCity && (!city || !state)) { showToast(t('js.citystatefirst')); return; }

  if (photos.some(p => p.uploading)) {
    showToast('Still uploading photos — hang on a moment');
    return;
  }

  const images = photos
    .filter(p => p.uploadedUrl)
    .map(p => ({ url: p.uploadedUrl, caption: p.caption, is_360: p.is360 }));

  const btn = document.getElementById('submit-btn');
  if (btn.disabled) return; // pipeline already running — ignore the double-click
  btn.disabled = true;
  btn.style.opacity = '0.6';
  btn.textContent = t('js.reviewing');

  showToast(t('js.reviewing'));
  try {
    const payload = {
      text,
      location_text,
      ward: authUser ? authUser.ward : null,
      city,
      state,
      latitude: capturedLat,
      longitude: capturedLng,
      images,
    };
    const result = await api('/complaints', { method: 'POST', body: JSON.stringify(payload) });
    document.getElementById('complaint-text').value = '';
    document.getElementById('complaint-location').value = '';
    if (!knownCity) document.getElementById('submit-city').value = '';
    resetLocationCapture();
    resetPhotos();
    showSubmitSuccess(result);
  } catch (err) {
    if (err.status === 422 && err.data && err.data.detail && err.data.detail.rejected) {
      const d = err.data.detail;
      showToast(`Rejected: ${d.reason}${d.suggested_rephrasing ? ' — try: "' + d.suggested_rephrasing + '"' : ''}`);
    } else if (err.status === 429) {
      showToast('Too many submissions from your connection — try again in a while');
    } else {
      showToast(err.message);
    }
  } finally {
    btn.disabled = false;
    btn.style.opacity = '';
    btn.textContent = t('submit.button');
  }
}

/* ── SUCCESS CONFIRMATION ──
   A toast disappears in under 3 seconds — nowhere near long enough to note
   down a complaint ID, and an anonymous submitter (not signed in) has no
   "My complaints" list to find it in afterward. This stays until dismissed. */
let lastSubmitId = null;

function showSubmitSuccess(result) {
  lastSubmitId = result.id;
  document.getElementById('submit-success-score').textContent =
    t('submit.successscore', { score: Math.round(result.priority_score), category: result.category });
  document.getElementById('submit-success-id').textContent = result.id;
  document.getElementById('submit-success-idlabel').textContent = t('submit.idlabel');
  document.getElementById('submit-success-note').textContent = authUser
    ? t('submit.notesignedin')
    : t('submit.noteanonymous');
  document.getElementById('submit-success-overlay').hidden = false;
}

export function copySubmitId() {
  if (!lastSubmitId) return;
  navigator.clipboard.writeText(lastSubmitId).then(
    () => showToast(t('submit.copied')),
    () => showToast(lastSubmitId), // clipboard blocked (e.g. insecure context) — show it so they can note it manually
  );
}

export function dismissSubmitSuccess() {
  document.getElementById('submit-success-overlay').hidden = true;
  nav('home');
}

/* ── AUTH-STATE NOTICE ──
   Explains, before submitting, what "anonymous" actually means here and why
   signing in is the alternative — not just what happens after the fact. */
export function updateSubmitAuthNotice() {
  micLanguage();  // sync the voice-language picker to the app language
  cityStateOverride = false; // fresh visit to the page — start from the default again
  const anonNotice = document.getElementById('submit-anon-notice');
  const signedInNotice = document.getElementById('submit-signedin-notice');
  if (authUser) {
    anonNotice.style.display = 'none';
    signedInNotice.style.display = 'flex';
    document.getElementById('submit-signedin-notice-text').textContent =
      t('submit.signedinnotice', { name: authUser.name });
  } else {
    signedInNotice.style.display = 'none';
    anonNotice.style.display = 'flex';
    document.getElementById('submit-anon-notice-text').textContent = t('submit.anonnotice');
    document.getElementById('submit-anon-notice-link').textContent = t('submit.anonnoticelink');
  }

  // City & State: an anonymous complaint (or a signed-in account with no
  // city/state on file) has nowhere else to get this from — "Location" alone
  // is just a free-text hint, it doesn't populate ward/city/state-scoped
  // views, hotspot maps, or state-level dashboards. Ask for it explicitly
  // rather than silently submitting a complaint with no real geography.
  const knownCity = authUser && authUser.city;
  const knownState = authUser && authUser.state;
  const citystateGroup = document.getElementById('submit-citystate-group');
  const citystateKnown = document.getElementById('submit-citystate-known');
  if (knownCity && knownState) {
    citystateGroup.style.display = 'none';
    citystateKnown.style.display = 'block';
    document.getElementById('submit-citystate-known-text').textContent =
      t('submit.citystateknown', { city: knownCity, state: knownState });
  } else {
    citystateGroup.style.display = 'block';
    citystateKnown.style.display = 'none';
  }
}

// "Not reporting for your registered location? Change it" — reveals the
// real State/City fields for a signed-in user and marks the override so
// submitComplaint() actually uses them instead of silently falling back to
// the account's saved city/state.
export function overrideSubmitCityState() {
  cityStateOverride = true;
  document.getElementById('submit-citystate-known').style.display = 'none';
  document.getElementById('submit-citystate-group').style.display = 'block';
  // window.populateStateSelect/onSubmitStateChange are the plain globals
  // defined in nagarvaani-full.html's inline script (shared with signup and
  // Near Me's manual form) — start from the account's own state/city as a
  // sensible default rather than blank/Maharashtra.
  const state = (authUser && authUser.state) || 'Maharashtra';
  document.getElementById('submit-state').value = state;
  window.onSubmitStateChange(state);
  if (authUser && authUser.city) document.getElementById('submit-city').value = authUser.city;
  document.getElementById('submit-city').focus();
}
