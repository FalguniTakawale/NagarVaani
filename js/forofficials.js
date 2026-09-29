/* Public marketing/info page for government officials — reached from the
   landing footer's "For officials" link. This is NOT the official dashboard
   (that needs login + admin approval); it's the equivalent of a "for
   developers" page: what the platform offers, real live numbers, and a way
   to start the signup flow. No fabricated news or policy content — the
   "live" stats and "what's new" items below are both genuinely real. */
import { api } from './api.js';

export async function loadForOfficials() {
  try {
    const stats = await api('/stats/nationwide');
    document.getElementById('fo-stat-total').textContent = stats.total.toLocaleString();
    document.getElementById('fo-stat-resolved').textContent = stats.resolved.toLocaleString();
    document.getElementById('fo-stat-critical').textContent = stats.critical.toLocaleString();
    document.getElementById('fo-stat-states').textContent = stats.states_with_patterns.toLocaleString();
  } catch (err) {
    // Info page shouldn't block on this — just leave the placeholders.
  }
}
