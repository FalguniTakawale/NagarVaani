# NagarVaani — What the App Does

**NagarVaani (नगरवाणी) — "Your Voice, Your City."** A civic-intelligence layer between citizens and government.
Built for *Build with AI: Code for Communities* (Hack2Skill / GDG), Track 1 — AI for Digital Public Infrastructure & Governance (BRICS theme: Innovation).

## The problem
Citizen development requests live in fragmented channels (helplines, WhatsApp groups, paper letters, portals). Officials can't see the whole picture, ranking is by whoever shouts loudest, and small villages are drowned out by large cities.

## The idea in one line
> **Low votes ≠ low importance.** A monsoon drain with 3 votes outranks a dry-season pothole with 104.

## Who uses it
| Person | What they do |
|---|---|
| **Citizen** (signed in or anonymous) | Reports a problem by web form, voice note (mic) or Telegram bot, in Hindi / Marathi / Tamil / English (or Hinglish); adds photos; tracks status; votes; comments; shares; reports abusive posts |
| **Official** (ward / city / state / central; admin-approved) | Sees a queue sorted by real priority, AI briefs, hotspot map, marks in-progress / resolved, flags infrastructure gaps, reviews citizen reports, sees ranked "priority projects" |
| **Admin** | Approves or rejects official accounts; can load external datasets (population, infrastructure index, planned investment) |

## How a complaint travels
1. **Intake** — web form, mic recording (speech-to-text via Whisper), or Telegram text/voice. Any language.
2. **Filter (AI)** — rejects political / communal framing and suggests a neutral rephrasing.
3. **Classify (AI)** — category, language, English translation (Romanised Hindi is translated too), location hint, safety-risk yes/no.
4. **Score (pure math, no LLM)** — the L1–L5 hierarchy → 0–100 priority. See the table below and the in-app page **"How scoring works (L1–L5)"**.
5. **Brief (AI)** — a 2–3 sentence official brief + one recommended action.
6. **Public thread** — like a Q&A thread: comments, "same issue in my area" links (cross-district pattern → L5), place names in comments are auto-detected and linked by NLP.
7. **Action** — officials update status; the citizen is notified (email; Telegram if linked); the citizen can **dispute** a "resolved" status that isn't really fixed.

## Pages
Landing · Home (ward feed) · Trending (nationwide) · Near me (GPS radius + map + email alerts) · My complaints · My votes · Complaint detail (score breakdown, photos, comments, translate, share, flag) · Submit · Track by ID · Report corruption (login-gated, never in public feeds) · Govt schemes directory · **How scoring works (L1–L5)** · About · Our impact · Get involved · For officials · Official portal (Queue, All, Hotspot Map, **Priority Projects**, Investment Flags + Citizen reports, Resolved, Verifications).

## What the L1–L5 levels mean (plain language)
| Level | Meaning | Effect |
|---|---|---|
| **L1** Safety | Could someone be hurt within days? | +40 and a score floor of 90 |
| **L2** Season | Same problem, worse season (monsoon drains, summer water/power) | multiplier ×1.0–×2.0 |
| **L3** Problem type | Water 28 · drainage 26 · electricity 22 · tree 20 · corruption 18 · garbage 16 · road 14 · other 10 | + points |
| **L4** People affected | Log-scaled population (max +15) | + points (default population 10,000 until a dataset is loaded) |
| **L5** Pattern | Same issue reported from other areas | +5 per area, max +20 |
| Votes | Weakest signal | ×(1 + 0.1·log10(votes+1)) |

`score = min(100, (L1+L3+L4+L5) × L2)`, floored at 90 if L1; then × vote nudge.

## What the buttons do (new in this revision)
* **🔗 Share** — real: opens a dialog with the device share sheet (where supported), Copy link, WhatsApp, Telegram, X, Facebook, Email. Link format `…/#complaint/<id>` opens that complaint directly.
* **⚑ Flag** — real: signed-in citizens report a post (spam / misleading / duplicate / abusive / wrong location + note). It is stored in the database and appears in the **official portal → Investment Flags → "Citizen reports"** table for that official's jurisdiction. Nothing is auto-hidden; a human reviews.
* **🚩 Flag for investment** (officials, in the queue) — a different flag: posts an `[OFFICIAL FLAG]` note that lists the complaint under **Investment Flags** as an infrastructure gap for a senior reviewer. Only verified officials can create these.

## Tech
FastAPI + SQLAlchemy (async) · SQLite locally / PostgreSQL on Render · vanilla-JS ES modules front end (Leaflet + OpenStreetMap) · Gemini by default (Claude switchable in one line) · Whisper STT (Hugging Face default, Groq/OpenAI optional) · Cloudinary images · Telegram bot · Gmail SMTP · Google Sign-In (optional).
