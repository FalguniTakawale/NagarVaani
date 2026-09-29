# Challenge alignment — is the prototype enough?

**Challenge (Build with AI: Code for Communities, Track 1, BRICS "Innovation")** — build a scalable, multilingual AI platform, designed as a Digital Public Good, that aggregates citizen development requests (voice, text, messaging apps) across linguistic regions, analyses them together with national demographic data, infrastructure indices and public investment plans, surfaces demand hotspots, and recommends high-priority development projects to policymakers across BRICS nations.

> Note: the challenge text used here is the statement supplied by the team. The GDG/H2S event page itself could not be consulted while writing this — check it for judging criteria and submission format.

## Honest verdict
**Strong for the "citizen intake → intelligent prioritisation → official action" half. Partial on the "national data + policy recommendation + BRICS" half.** It is a credible prototype if presented as such; the gaps below should be named on stage rather than discovered by judges.

| Requirement | Verdict |
|---|---|
| Voice + text + messaging intake, multilingual | ✅ Web, mic, Telegram; Hinglish now handled. ⛔ WhatsApp |
| AI analysis beyond votes | ✅ Transparent L1–L5 scoring; explainable per complaint |
| Hotspots | ✅ Live map + ranked Priority Projects |
| Combine with demographic / infra / investment data | 🔌 Ingestion pipeline + table built and wired into L4 and hotspot reports; **no real datasets loaded** |
| Recommend projects to policymakers | 🟡 Rule-based suggestions with evidence links; no costs, no optimisation |
| Impact measurement | 🟡 Status log, disputes, resolved counts |
| BRICS | ⛔ India only (schema is country-ready) |
| Digital Public Good | 🟡 MIT, provider-agnostic, privacy doc |

## What was added in this revision to close gaps
1. **Dataset ingestion** (`region_indicators`, `POST /api/insights/indicators[/csv]`, `python load_indicators.py`) — country/state/city/indicator/value/year/**source** (provenance mandatory).
2. **Population feeds L4** when a dataset covers the city (was a hard-coded 10,000).
3. **Priority Projects** view + `GET /api/insights/priority-projects` — city × category hotspots ranked by severity-weighted demand, per-100k rates when population is known, suggested project type, evidence complaint IDs, and an explicit list of missing datasets. Costs intentionally `null`.
4. Real **Share**, real **citizen Flag → moderation queue**, an **L1–L5 explainer page**, Hinglish translation fix, security hardening.

## Highest-value next steps (if there were more time)
1. Load a real census extract + one infrastructure index for 2–3 cities; show the before/after effect on L4 and hotspots.
2. WhatsApp Cloud API webhook cloned from `routers/telegram.py`.
3. A second country pack (e.g. Brazil, Portuguese) — `country` field, locale strings, scheme list — to demonstrate BRICS portability.
4. Investment-gap score: `demand_index ÷ planned_investment` per city × category once a plan dataset exists.
5. Impact metrics: median time-to-resolve, dispute rate, per-ward trends.
6. Human-review queue for filter fail-open cases; CSP; Redis rate limiting.
7. Public open-data export (aggregated, anonymised) to strengthen the Digital-Public-Good claim.

## Suggested demo script (3 minutes)
1. Submit a Hinglish complaint by mic → show filter, translation, L1–L5 breakdown → open *How scoring works*.
2. Vote on a rival pothole complaint → show it still ranks lower (votes are the weakest signal).
3. Share the link; open it in a private window.
4. Flag it as a citizen → switch to official portal → *Investment Flags → Citizen reports*.
5. *Priority Projects*: show ranked hotspots, then the "missing datasets" note — and say plainly what would be loaded next.
