/* Home-page help chatbot — a real backend call (Gemini/Claude, grounded
   strictly in NagarVaani's actual features, see ai_engine.py's
   _CHATBOT_GROUNDING) in whichever of the 4 languages is selected. Not a
   canned FAQ — a genuine LLM answer, but scoped so it can't invent features. */
import { api } from './api.js';
import { escapeHtml } from './ui.js';
import { t, currentLang } from './i18n.js';

let opened = false;

// A handful of real starting points — same "no invented capabilities" rule
// the grounding prompt itself follows. "What are the statistics" is
// answered with live DB counts, not a guess (see chatbot.py's live_stats).
const SUGGESTED_KEYS = [
  'chatbot.sugg.report', 'chatbot.sugg.priority', 'chatbot.sugg.stats',
  'chatbot.sugg.corruption', 'chatbot.sugg.contact',
];

function renderSuggestions() {
  const box = document.getElementById('chatbot-suggestions');
  if (!box) return;
  box.hidden = false;
  box.innerHTML = SUGGESTED_KEYS.map(key =>
    `<button type="button" class="chatbot-chip" onclick="askChatbotSuggestion(this)">${escapeHtml(t(key))}</button>`
  ).join('');
}

export function askChatbotSuggestion(btn) {
  const input = document.getElementById('chatbot-input');
  input.value = btn.textContent;
  sendChatbotMessage();
}

export function toggleChatbotPanel() {
  const panel = document.getElementById('chatbot-panel');
  panel.hidden = !panel.hidden;
  if (!panel.hidden && !opened) {
    opened = true;
    addMessage('bot', t('chatbot.greeting'));
    renderSuggestions();
  }
}

export function showChatbotWidget(show) {
  const widget = document.getElementById('chatbot-widget');
  if (widget) widget.hidden = !show;
}

function addMessage(role, text) {
  const list = document.getElementById('chatbot-messages');
  const div = document.createElement('div');
  div.className = 'chatbot-msg chatbot-msg-' + role;
  div.textContent = text;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
  return div;
}

export async function sendChatbotMessage() {
  const input = document.getElementById('chatbot-input');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  addMessage('user', message);
  const suggestions = document.getElementById('chatbot-suggestions');
  if (suggestions) suggestions.hidden = true;

  const typingEl = addMessage('bot', t('chatbot.typing'));
  typingEl.classList.add('chatbot-typing');

  try {
    const result = await api('/chatbot', {
      method: 'POST', body: JSON.stringify({ message, language: currentLang() }),
    });
    typingEl.remove();
    addMessage('bot', result.reply);
  } catch (err) {
    typingEl.remove();
    addMessage('bot', err.message || t('chatbot.error'));
  }
}
