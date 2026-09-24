export function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2800);
}

import { t } from './i18n.js';

export function loadingPlaceholder(text = t('js.loading')) {
  return `<div class="loading-state" style="padding:24px;text-align:center;color:var(--slate-light);font-size:13px;">${text}</div>`;
}

export function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}
