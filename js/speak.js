/* READ ALOUD — lets someone who can't (or finds it hard to) read hear the official's
   brief, recommended action or a comment, in their own language.

   Self-contained and additive: any element with data-speak is a button —
     data-speak="#some-selector"   reads that element's text
     data-speak="comment"          reads the text of the comment the button is inside
   One delegated click listener does everything, so pages just add the attribute.

   How it works: uses the browser's built-in speech (Web Speech API) — no API key, no
   server, no cost, nothing sent anywhere for the speaking itself. If the app language
   is Hindi / Marathi / Tamil, the text is first translated with the existing
   /translate endpoint so it is read in that language; if translation is unavailable
   it falls back to reading the original. Availability of voices depends on the device
   (Android/Chrome usually has Hindi and Tamil; Marathi is patchier) — when a language
   has no installed voice we say so and use the closest available one. */
import { api } from './api.js';
import { showToast } from './ui.js';
import { t, currentLang } from './i18n.js';

const BCP47 = { en: 'en-IN', hi: 'hi-IN', mr: 'mr-IN', ta: 'ta-IN' };
// Closest fallback voices when the exact language isn't installed (Marathi shares
// Devanagari script with Hindi, so a Hindi voice is the best approximation).
const FALLBACK = { mr: ['hi', 'en'], hi: ['en'], ta: ['en'], en: [] };

let activeBtn = null;

const synth = () => (typeof window !== 'undefined' && window.speechSynthesis ? window.speechSynthesis : null);

export function speechSupported() {
  return !!synth() && typeof window.SpeechSynthesisUtterance === 'function';
}

function voicesReady() {
  const s = synth();
  return new Promise(resolve => {
    const have = s.getVoices();
    if (have && have.length) return resolve(have);
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(s.getVoices() || []); } };
    s.addEventListener && s.addEventListener('voiceschanged', finish, { once: true });
    setTimeout(finish, 800); // some browsers never fire the event
  });
}

/* Pick the best installed voice for a language code; report which one we really got. */
export function pickVoice(voices, lang) {
  for (const code of [lang, ...(FALLBACK[lang] || [])]) {
    const v = voices.find(x => (x.lang || '').toLowerCase().replace('_', '-').startsWith(code));
    if (v) return { voice: v, got: code };
  }
  return { voice: null, got: null };
}

/* Browsers drop long utterances (Chrome silently stops ~15s in), so speak in short chunks. */
export function chunkText(text, max = 180) {
  const clean = (text || '').replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  const sentences = clean.match(/[^.!?।॥]+[.!?।॥]*/g) || [clean];
  const out = [];
  let cur = '';
  for (const s of sentences) {
    if ((cur + s).length > max && cur) { out.push(cur.trim()); cur = ''; }
    if (s.length > max) { // one very long sentence: split on spaces
      for (let i = 0; i < s.length; i += max) out.push(s.slice(i, i + max).trim());
    } else cur += s;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

export function stopSpeaking() {
  const s = synth();
  if (s) s.cancel();
  if (activeBtn) { activeBtn.classList.remove('speaking'); activeBtn.textContent = activeBtn.dataset.label || '🔊'; activeBtn = null; }
}

async function toSpokenText(raw, lang) {
  if (lang === 'en') return { text: raw, lang: 'en' };
  try { // reuse the existing translation endpoint; never block speaking if it fails
    const r = await api('/translate', { method: 'POST', body: JSON.stringify({ text: raw.slice(0, 4000), target_language: lang }) });
    if (r && r.translated) return { text: r.translated, lang };
  } catch (_) { /* fall through */ }
  return { text: raw, lang: 'en' };
}

function textFor(btn) {
  const spec = btn.dataset.speak;
  if (spec === 'comment') {
    const el = btn.closest('.comment');
    const node = el && el.querySelector('.comment-text');
    return node ? node.textContent : '';
  }
  const node = document.querySelector(spec);
  return node ? node.textContent : '';
}

export async function speakFromButton(btn) {
  if (!speechSupported()) { showToast(t('speak.unsupported')); return; }
  if (activeBtn === btn) { stopSpeaking(); return; }   // second tap = stop
  stopSpeaking();
  const raw = (textFor(btn) || '').trim();
  if (!raw) return;

  btn.dataset.label = btn.dataset.label || btn.textContent;
  activeBtn = btn; btn.classList.add('speaking'); btn.textContent = '⏹';

  const { text, lang } = await toSpokenText(raw, currentLang());
  if (activeBtn !== btn) return; // user tapped stop / navigated while translating
  const { voice, got } = pickVoice(await voicesReady(), lang);
  if (!voice) { showToast(t('speak.novoice')); stopSpeaking(); return; }
  if (got !== lang) showToast(t('speak.fallback', { asked: lang.toUpperCase(), got: got.toUpperCase() }));

  // An English voice can't pronounce Devanagari/Tamil script — if that's all the device
  // has, read the original text instead of the translation.
  const parts = chunkText(got === 'en' && lang !== 'en' ? raw : text);
  parts.forEach((part, i) => {
    const u = new SpeechSynthesisUtterance(part);
    u.voice = voice; u.lang = voice.lang || BCP47[got] || 'en-IN'; u.rate = 0.92;
    if (i === parts.length - 1) { u.onend = u.onerror = () => { if (activeBtn === btn) stopSpeaking(); }; }
    synth().speak(u);
  });
}

document.addEventListener('click', e => {
  const btn = e.target.closest && e.target.closest('[data-speak]');
  if (btn) { e.preventDefault(); e.stopPropagation(); speakFromButton(btn); }
});
window.addEventListener('pagehide', stopSpeaking);
