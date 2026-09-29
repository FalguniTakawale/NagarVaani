# Reality Matrix — what is real, what is demo, what is a stub

Legend: ✅ **Real** (live data / working end to end) · 🟡 **Real but simplified** · 🧪 **Demo / example content** · 🔌 **Provision built — needs data or a key** · ⛔ **Not built**

## 1. Data shown to users
| Area | Status | Notes |
|---|---|---|
| Complaint feeds (Home, Trending, Near me, My complaints, My votes) | ✅ | Live DB queries. Counts, scores, votes are real. |
| Right-panel / dashboard counters, landing stats, nationwide stats | ✅ | Computed from the complaints table (`/stats/*`). |
| Hotspot map points | ✅ | Real geotagged complaints. **🧪 Fallback:** if the DB has no geotagged complaints (or the API is unreachable) `js/govt.js` shows 4–7 hard-coded example pins (Barmer, Pune, Amravati…) so the map isn't blank — clearly a demo fallback. |
| Static feed cards before first load | 🧪 | Placeholder cards replaced by real data once the API answers; voting on them shows "Demo card". |
| Right-panel "My complaints" sample rows (Lane 4, streetlight…) | 🧪 | Static HTML sample shown before/without login. |
| Seed accounts & 5 seeded complaints (`seed_data.py`) | 🧪 | `ramesh@test.com`, `official@test.com`, `voter*@seed.nagarvaani` (~110 fake voters). **Do not run the seed in a real deployment**, or change/remove those accounts. |
| Get-involved page: NGO/CSR partners, events, before/after gallery | 🧪 | Marked with DEMO ribbons + banners. No real partners exist. |
| Our-impact "trees planted", "recycled" blocks | 🧪 | "Coming soon" placeholders (no invented numbers). Resolved/critical counts are ✅ real. |
| Govt schemes / ministries directory | 🟡 | Curated **India-only** static list with real ministry links; not a live scheme API. |
| Complaint text, votes, comments, images, status log | ✅ | Whatever users submit. |

## 2. AI behaviour
| Feature | Status | Notes |
|---|---|---|
| Political/communal filter | ✅ | LLM call; **fails open** (passes the complaint) if the LLM is down. |
| Classification, language detection, translation to English | ✅ | LLM; fails open to category `other`. Romanised Hindi ("Hinglish") is now detected and translated (fixed this revision). |
| On-demand translate (complaint / comment / card) | ✅ | Now returns a clear error (503) instead of silently echoing the same text when the LLM fails. Rate-limited. |
| Priority score (L1–L5 + votes) | ✅ | Deterministic Python, no LLM. L1's *input* (is it a safety risk?) is an LLM judgement. |
| L2 season | 🟡 | Uses the **server's calendar month** at scoring time (India season table); stored, not re-evaluated as seasons change. |
| L4 population | 🟡→🔌 | **Default 10,000 for everyone** unless an admin loads a `population` dataset for the city (`/api/insights/indicators`, `load_indicators.py`). No census data is bundled. Telegram-sourced complaints still use the default. |
| L5 cross-area pattern | ✅ | From the "Same issue in my area" button and NLP place detection in comments. |
| Official brief + recommended action | ✅ | LLM text; fallback template if LLM fails. **No ₹ cost figures** (removed on purpose; none invented). |
| Chatbot (home) | ✅ | Grounded only in a fixed fact sheet + live counts; rate-limited. |
| Speech-to-text | 🔌 | Works with a Hugging Face / Groq / OpenAI key; without one, voice returns an error. HF free tier has cold starts. |

## 3. Buttons — which clicks are real
| Click | Status |
|---|---|
| Vote (▲), Same issue in my area, Comment, Dispute, Translate, Track by ID | ✅ real API calls |
| **Share** | ✅ real (Web Share API + copy + WhatsApp/Telegram/X/Facebook/Email intents; deep link opens the complaint). *Was a fake "Link copied" toast before.* |
| **Flag** (citizen) | ✅ real — POST `/complaints/{id}/flag`, stored, shown to officials. *Was a fake toast before.* |
| Flag for investment (official) | ✅ real — creates an `[OFFICIAL FLAG]` comment; lists under Investment Flags. |
| Mark in progress / Resolve (official) | ✅ real, now limited to the official's own jurisdiction; notifies the citizen by email/Telegram. |
| Submit complaint (text, mic, photos) | ✅ real (photos need Cloudinary keys; mic needs an STT key). |
| Neighbourhood email alerts | ✅ real (needs SMTP; otherwise printed to server log). |
| Sign-in with Google | 🔌 shown only when `GOOGLE_CLIENT_ID` is set. |
| Volunteer / org-partner forms | 🟡 `mailto:` style CTAs — open the visitor's mail app; nothing is stored server-side. |
| Get-involved "shout-out" / gallery / event cards | 🧪 example layout only. |
| Gallery thumbnails with emoji in the static detail template | 🧪 replaced by real images when a complaint has any. |
| Help & FAQ modal, Chatbot | ✅ |

## 4. Channels
| Channel | Status |
|---|---|
| Web form | ✅ |
| Mic voice note | 🔌 (STT key) |
| Telegram bot (text + voice, account linking, status replies) | 🔌 (bot token + webhook secret). Conversation state is in memory — lost on restart. |
| WhatsApp | ⛔ **Not built.** The DB column `source_channel` allows `whatsapp`, but no integration exists (needs WhatsApp Cloud API + business approval). Telegram is the built messaging channel. |
| SMS / IVR | ⛔ |

## 5. Challenge coverage & where to expand
| Challenge element | Status | Where it plugs in |
|---|---|---|
| Aggregate citizen requests via voice, text, messaging apps | ✅ web / mic / Telegram · ⛔ WhatsApp | `routers/telegram.py` is the template for a WhatsApp Cloud API webhook |
| Multilingual | 🟡 UI: EN/HI/MR/TA. AI understands many more languages; UI chrome for new pages ("How scoring works", share/flag/priority-projects) is English-only | add keys to `js/i18n.js`; add languages to `LANGUAGES` |
| Scalable AI platform | 🟡 Stateless FastAPI + Postgres; in-memory rate limiter & Telegram state need Redis for multi-instance | swap `services/rate_limit.py` |
| Digital Public Good | 🟡 MIT licence, no proprietary lock-in, LLM/STT provider switchable, privacy doc | add DPG-Standard docs, open data export |
| Combine feedback with **national demographic data** | 🔌 `region_indicators` table + `population` feeds L4 and per-100k rates | load real census extracts |
| …with **infrastructure indices** and **public investment plans** | 🔌 same table accepts `infra_index`, `planned_investment`; Priority Projects lists which are missing per hotspot. **No dataset is bundled and no formula uses them yet.** | extend `routers/insights.py` scoring |
| Surface demand hotspots | ✅ real-time map + ranked Priority Projects (city × category) | |
| Recommend high-priority projects to policymakers | 🟡 rule-based ranking (severity-weighted demand) + generic project type per category. **No cost estimates, no forecasting model.** | add cost dataset / optimisation |
| Measure impact of DPI initiatives | 🟡 resolution counts, dispute reopen, status log exist; no before/after outcome metrics yet | |
| **BRICS-wide** | ⛔ India-only data layer (states, schemes, languages). `region_indicators.country` is BRICS-ready; nothing else is | add Brazil/Russia/China/South Africa locale + scheme data |

## 6. Known simplifications (be upfront in the demo)
* AI filters/classifiers **fail open** — if the LLM key is missing or quota is exhausted, complaints are still accepted (category `other`).
* Score weights are transparent editorial choices, not a statistically validated model.
* "Population" is a default until data is loaded.
* Rate limiting is per-process memory and keys off `X-Forwarded-For`.
* The moderation queue does not yet let an official "dismiss" a citizen report (it is view-only).
