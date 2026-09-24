import { API_BASE } from './api.js';
import { showToast } from './ui.js';
import { t } from './i18n.js';

/* ── VOICE INPUT (real mic capture, real transcription via /api/stt) ── */
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

export async function toggleRecording() {
  const btn = document.getElementById('mic-btn');
  const label = document.getElementById('mic-btn-label');
  const status = document.getElementById('voice-status');

  if (!isRecording) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        status.textContent = 'Transcribing…';
        const blob = new Blob(audioChunks, { type: 'audio/webm' });
        const form = new FormData();
        form.append('audio', blob, 'voice.webm');
        try {
          const res = await fetch(API_BASE + '/stt', { method: 'POST', body: form });
          const result = await res.json();
          if (result.text) {
            const box = document.getElementById('complaint-text');
            box.value = (box.value.trim() ? box.value + ' ' : '') + result.text;
            status.textContent = '✓ Transcribed — edit if needed, then submit';
            showToast('Voice note transcribed via Whisper');
          } else {
            status.textContent = result.error || 'Transcription unavailable';
            showToast(result.error || 'STT not configured on the server — type the complaint instead');
          }
        } catch (err) {
          status.textContent = 'Could not reach the server';
          showToast(t('js.unreachable'));
        }
      };
      mediaRecorder.start();
      isRecording = true;
      btn.classList.add('recording');
      label.textContent = '⏺ Recording — tap to stop';
      status.textContent = '';
    } catch (err) {
      showToast('Microphone access denied or unavailable');
    }
  } else {
    mediaRecorder.stop();
    isRecording = false;
    btn.classList.remove('recording');
    label.textContent = t('submit.mic');
  }
}
