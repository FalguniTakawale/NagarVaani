# NagarVaani — Your Voice, Your City

A civic-intelligence layer between citizens and government. Citizens report
infrastructure problems in any language — by web form, voice note, or Telegram.
An LLM (Gemini by default, Claude optional) scores every complaint on **severity, season, population density and
cross-district patterns — not vote count** — so a village of fifty gets heard on
merit. Officials get AI-synthesised briefs, a live hotspot map, and a queue
sorted by what actually matters.

> Low votes ≠ low importance. A monsoon drain with 3 votes outranks a
> dry-season pothole with 104.

Built for **Build with AI: Code for Communities** (H2S) — Track 1, AI for Digital
Public Infrastructure & Governance.

**Read next:** [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md) (also as
[PDF](docs/NagarVaani_Project_Report.pdf)) — what the app does, what the ⚑ Flag
does, what L1–L5 mean, an honest real-vs-demo-vs-stub audit, GDG challenge fit,
and the security review.

Licensed under [MIT](LICENSE) — see [PRIVACY.md](PRIVACY.md) for what data the
platform actually collects and where it goes.

---

## Known limitations & future work

This is a hackathon-stage prototype for **India specifically**, not the full
BRICS-wide platform the challenge statement describes. Being direct about the
gap rather than quietly building only the easy 80%:

- **Country scope**: every government scheme, ministry link, state/district
  list, and language is India-only. There's no country concept anywhere in
  the data model. Extending to another BRICS nation means adding its own
  schemes/ministries/languages, not re-architecting the platform — the
  scoring engine, translation pipeline, and dashboards are already
  country-agnostic — but that data layer doesn't exist yet for anyone but India.
- **No external dataset ingestion**: the priority scorer's population factor
  is `population=10000`, hardcoded at the call site (see `complaints.py`) —
  there's no real census/demographic dataset behind it. Infrastructure-index
  data and public investment-plan data aren't ingested at all. The platform
  surfaces real complaint-density hotspots (that part is genuine), but it
  doesn't yet combine that with external government planning data the way
  the challenge asks.
- **No automated project recommendations**: officials can flag a complaint
  as an infrastructure gap, but there's no model generating a specific
  "build X here, costing Y" recommendation from data. An earlier version of
  this prototype showed a fabricated ₹-cost figure for this; it was removed
  on purpose rather than replaced with another invented number, and hasn't
  been replaced with a real one yet.

What's already real and working: multilingual voice/text/Telegram intake,
AI severity scoring (not vote-based), cross-district pattern detection,
two-way translation between any complaint's language and the viewer's
selected language, jurisdiction-scoped official dashboards with admin-gated
account verification, and a real (if scoped-down) government-scheme/ministry
directory for India.

---

## Quick Start

```bash
git clone <repo>
cd Backend
cp .env.example .env
# Fill in GEMINI_API_KEY (default provider) or ANTHROPIC_API_KEY, others optional for local dev
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup_db.py
python seed_data.py     # makes ~20 Claude API calls, takes ~30 seconds
uvicorn main:app --reload --port 8000
# Open nagarvaani-full.html in browser
```

With the backend running you can also open <http://127.0.0.1:8000/> — FastAPI
serves the frontend too, which is how the Render deployment works.

Seeded logins:

| Role | Email | Password |
|---|---|---|
| Citizen | `ramesh@test.com` | `Test@1234` |
| Official (ward officer, Ward 12 Pune) | `official@test.com` | `Official@1234` |

**Testing the official portal / admin:** run `python create_test_officials.py` (add `--allow-production` on a deployed DB, from the Render Shell). It creates three pre-approved accounts — `admin.test@nagarvaani.gov.in` (central + admin), `ward.test@…` (Ward 12, Pune) and `state.test@…` (Maharashtra) — with **random passwords printed once** (nothing hardcoded). Remove them with `--remove` when done; never leave test admins on a public site.

---

## Testing the Telegram bot

NagarVaani's Telegram channel runs through the exact same filter → classify
→ score pipeline as the web form, as either text or a voice note.

**If a bot token is already set** (see `TELEGRAM_BOT_TOKEN` below) and the
service is deployed with a public URL, just open Telegram and message
**[@NagarvaaniHackBot](https://t.me/NagarvaaniHackBot)** — no setup needed
on your end:

1. Send a civic complaint as plain text, in any supported language (e.g.
   *"Naali bhar gayi hai Shivaji Nagar mein"*), or record a voice note
2. If the bot doesn't already know your area, it asks for one, then
   whether you'd like to attach a photo
3. It replies with a priority score, category, and a complaint ID
4. From the website, sign in → **Link Telegram** in the right panel to
   connect your account — linked complaints then also show up under
   "My complaints", and you get status-update messages here when an
   official changes something

**Why this doesn't work against a plain `localhost` dev server:** Telegram
delivers messages by calling your server's webhook URL directly, which
means that URL has to be a real public HTTPS address — it can't reach
`http://127.0.0.1:8000`. Two ways around that for local development:

- **Deploy it** (see the Render section below) — the assigned
  `https://<name>.onrender.com` URL works as-is.
- **Tunnel it** — run `ngrok http 8000` (or a similar tool) and register
  the tunnel's HTTPS URL as the webhook (one-time, from your own machine):
  ```bash
  curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
    -d url=https://<your-ngrok-subdomain>.ngrok-free.app/api/telegram/webhook \
    -d secret_token=<TELEGRAM_WEBHOOK_SECRET>
  ```

**To test with your own bot instead** of the one already configured:
create one via [@BotFather](https://t.me/BotFather) (`/newbot`, no approval
wait — unlike WhatsApp's Cloud API), then set `TELEGRAM_BOT_TOKEN` and a
random `TELEGRAM_WEBHOOK_SECRET` in `.env`/your Render environment, and
register the webhook with the `curl` command in step 7 of the Render
section below.

---

## Environment variables

All read from `Backend/.env` (see `.env.example`).

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Claude — filter, classify, brief, NLP, translation. Without it every AI call fails open (complaint accepted, category `other`). |
| `DATABASE_URL` | Yes | `sqlite+aiosqlite:///./nagarvaani.db` for local, or a Postgres URL. `postgres://` / `postgresql://` are rewritten to the asyncpg driver automatically. |
| `JWT_SECRET` | Yes in prod | Signs login tokens. The default `dev-secret-change-me` is refused unless `ENVIRONMENT=development`. |
| `ENVIRONMENT` | No (`development`) | `development` = open CORS, default JWT allowed, unsecured Telegram webhook allowed. Anything else = locked down. |
| `FRONTEND_URL` | Yes in prod | The only CORS origin allowed outside development. Comma-separate for several. |
| `OPENAI_API_KEY` | No | Whisper speech-to-text for voice notes (web mic + Telegram). Claude has no audio input. |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | No | Complaint photo / 360° uploads. Without them uploads return a clear error and the complaint submits without images. |
| `TELEGRAM_BOT_TOKEN` | No | From @BotFather. Enables the `/api/telegram/webhook` channel. |
| `TELEGRAM_WEBHOOK_SECRET` | Prod if bot used | Random string; pass the same value as `secret_token` to `setWebhook`. Requests without it get a bare 403. |
| `BREVO_API_KEY` / `BREVO_SENDER_EMAIL` | No (recommended on Render) | Brevo transactional email over HTTPS for OTP + notifications (API key `xkeysib-…`, sender verified in Brevo). Takes precedence over SMTP. |
| `REQUIRE_EMAIL_VERIFICATION` | No (`true`) | Set `false` only for a demo host that cannot send email: new citizen accounts are verified immediately. Never on a real deployment. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | No | Gmail SMTP for signup OTP + welcome email. Without them the OTP is printed to the server log instead. |
| `GOOGLE_CLIENT_ID` | No | "Continue with Google" sign-in. Without it, the button is hidden and password sign-in works as before. |

---

## Architecture

```
  Citizens                              Officials
  ────────                              ─────────
  Web form ─┐                           Official portal (queue · map · flags)
  Mic note ─┤  text / audio / photos            ▲
  Telegram ─┘                                   │ AI briefs, stats, map points
      │                                         │
      ▼                                         │
 ┌────────────────────────── FastAPI (Backend/) ─┴───────────────────────────┐
 │  routers/   auth · complaints · stats · media · telegram                  │
 │                                                                           │
 │  services/ai_engine.py   ── Claude ──►  0 Whisper STT (only if audio)     │
 │     per submission:                     1 Filter   reject political/     │
 │                                                    communal framing       │
 │                                         2 Classify category · severity · │
 │                                                    language · location    │
 │                                         3 Score    6-level hierarchy      │
 │                                                    (pure math, no LLM)    │
 │                                         + Official brief for the dashboard│
 │     ongoing:  NLP place-scan on comments → auto-link areas · translation  │
 │                                                                           │
 │  services/   auth (JWT+bcrypt) · rate_limit · stt · media_storage · tg    │
 └──────────┬───────────────────────┬──────────────────────┬─────────────────┘
            │ SQLAlchemy async      │                      │
            ▼                       ▼                      ▼
   PostgreSQL (Render)        Cloudinary            OpenAI Whisper
   SQLite (local)           images / 360°           voice → text

   Frontend: nagarvaani-full.html + css/ + js/ (10 ES modules, no framework),
   served by the same FastAPI process at / — Leaflet + OpenStreetMap for maps.
```

**Priority score** (`score_complaint`, `ai_engine.py`):
`(L1 safety + L3 category weight + L4 log-population + L5 linked-area bonus) × L2 seasonal multiplier`,
floored at 90 for safety risks, then `× (1 + 0.1·log10(votes+1))`. Votes are the
weakest signal by construction — they can reorder two similar issues but never
lift a non-critical one above a critical one.

---

## Near Me: Distance vs Priority sort, and manual location

The Near Me page (`js/nearme.js`) shows complaints within a radius of a point,
sourced from `GET /api/complaints?scope=nearby` (list) and `GET /api/stats/map`
(pins). The two sort buttons re-order that same list, nothing else:

- **Distance** — nearest first. Computed client-side with the haversine
  formula against your current point; shown on each card as "📍 X m/km away".
- **Priority** — highest AI priority score first (severity/season/population/
  cross-district pattern — see above), same score used everywhere else in
  the app, never vote count.

With only one or two complaints inside the current radius, switching sort
order can look like nothing happened — there's nothing left to reorder. That's
expected, not a bug (verified directly: a controlled two-complaint test, one
far-but-severe and one near-but-minor, sorts correctly and differently under
each mode). Widen the radius or pick a busier area to see it visibly reorder.

**Getting a specific location** (not just GPS): most laptops/desktops resolve
*some* location via GPS/IP even without a precise fix, which is meaningless
for testing an India-focused app from outside India. Two ways to search a
specific state/city/area instead of your device's real location:

- **Near Me** — the **"🔍 Enter a location"** button (always visible, not
  just when GPS fails) reveals a State dropdown + City combo + free-text
  area/road field. Submitting geocodes that combination via Nominatim's
  *structured* query fields (not one ambiguous free-text string) — this is
  what correctly resolves an ambiguous name like "S.B. Road" (which exists
  in more than one Indian city) to the city you actually specified, not
  whichever one a plain-text search ranks highest globally.
- **Report an issue** — if you're signed in with a city/state already on
  your account, the form defaults to that (shown as "📍 Using your
  registered location: ...") instead of asking again. Click **"✏️ Report
  for a different city/state"** next to it to override — the fields it
  reveals are pre-filled from your account as a starting point but fully
  editable, and whatever you submit with wins over the account default.

---

## API endpoints

All under `/api`. Interactive docs at `/docs` when the server is running.

| Method | Path | Auth | What |
|---|---|---|---|
| `POST` | `/auth/register` | — | Create account (citizen or official) |
| `POST` | `/auth/login` | — | Get JWT. 403 with `requires_verification` until the email OTP is confirmed. |
| `POST` | `/auth/verify-email` | — | `{user_id, otp}` → JWT. `/auth/resend-otp` re-sends (3/hour/email). |
| `POST` | `/auth/google` | — | `{credential}` (Google ID token) → JWT. Creates a citizen account on first sign-in; official accounts still require the work-email + admin-approval flow. Hidden client-side if `GOOGLE_CLIENT_ID` isn't set. |
| `POST` | `/complaints` | optional | Submit → filter → classify → score → brief. **5 per IP per hour.** 422 with `suggested_rephrasing` if the filter rejects it. |
| `GET` | `/complaints` | optional | List. `scope=ward\|trending\|nearby\|mine\|jurisdiction\|corruption`, `sort=priority\|votes\|recent\|distance`, `lat`/`lng`/`radius_km` or `near_text` for nearby, `category`, `status_filter`, `page`, `per_page`. Corruption never appears in public feeds. |
| `GET` | `/complaints/{id}` | — | Full detail: breakdown, images, comments, linked areas, status log |
| `GET` | `/complaints/{id}/related` | — | Similar-in-area + cross-pattern complaints |
| `POST` | `/complaints/{id}/vote` | citizen | Vote once; solidarity if from another ward. Re-scores. |
| `POST` | `/complaints/{id}/comments` | optional | Comment; Claude scans for place names and auto-links them |
| `POST` | `/complaints/{id}/link-area` | optional | "Same issue in my area" — feeds the L5 bonus, re-scores |
| `PATCH` | `/complaints/{id}/status` | official | `open \| in_progress \| resolved \| rejected`, logged |
| `POST` | `/complaints/{id}/dispute` | author | Reopen a *resolved* complaint as `disputed` |
| `POST` | `/complaints/{id}/translate` | — | Translate complaint text to `target_language` |
| `POST` | `/translate` | — | Translate any text (comments) — `{text, target_language}` |
| `GET` | `/complaints/flagged` | official | Complaints carrying an `[OFFICIAL FLAG]` comment — the Investment Flags list |
| `GET` | `/stats/ward?ward=` | — | open / critical / in-progress / resolved counts |
| `GET` | `/stats/jurisdiction` | official | Tiles + badge counts scoped to the official's own ward / city / state |
| `POST` | `/complaints/{id}/report` | optional | ⚑ Flag — queue a complaint for moderator review (never auto-hides) |
| `GET` | `/admin/reports` | admin | Moderation queue of flagged complaints |
| `GET` | `/stats/priorities` | official | Ranked (state × problem) demand with Census-2011 population + suggested central scheme |
| `GET` | `/stats/nationwide` | — | Totals + per-state hotspot rollup |
| `GET` | `/stats/map` | — | `{lat,lng,score,category,label}` points for Leaflet. `scope=national\|ward\|city\|state` |
| `POST` | `/stt` | — | multipart `audio` → Whisper transcript |
| `POST` | `/media/upload` | — | multipart `file` → Cloudinary URL |
| `POST` | `/telegram/webhook` | secret header | Telegram update (text or voice) → same pipeline, replies in chat |
| `GET` | `/health` | — | `{"status": "ok"}` |

---

## Deploy to Render

The repo ships a `render.yaml` Blueprint: one Python web service (API +
frontend), no separate database resource — it uses SQLite on the service's
own disk. This is a deliberate tradeoff: provisioning a Render database
(even the free plan) requires a payment method on file for anti-abuse
verification, a plain web service doesn't. The cost is that Render's free
web service filesystem is ephemeral — data doesn't reliably survive a
redeploy or crash restart (ordinary idle spin-down/wake is fine). Good
enough for a demo/judging session; re-seed if it resets. Swap
`DATABASE_URL` for a real Postgres URL (Render's own paid plan, or any
other provider) whenever you want a deployment that keeps its data.

1. Push the repo to GitHub (`.gitignore` already excludes `.env`, `.venv`, `*.db`).
2. Render dashboard → **New → Blueprint** → select the repo. Render reads
   `render.yaml` and creates the `nagarvaani` web service — no card needed
   for this step, since there's no database to provision.
3. When prompted, paste the secrets marked `sync: false`:
   `GEMINI_API_KEY` (required — the app's active default AI provider), and
   optionally `ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_ID`, and the Cloudinary/
   OpenAI/Telegram values. `JWT_SECRET` and `TELEGRAM_WEBHOOK_SECRET` are
   generated for you.
4. Edit `FRONTEND_URL` in the service's environment to the URL Render assigned
   (e.g. `https://nagarvaani-xyz.onrender.com`) — the app refuses to start in
   production with a wrong/empty value, on purpose.
5. Deploy. The start command runs `python setup_db.py` (creates tables) and then
   uvicorn. Check `/api/health`, then open the root URL.
6. Seed the demo data once, from the Render **Shell** tab:
   `cd Backend && python seed_data.py`
7. Telegram (optional): register the webhook with your bot token —
   ```
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d url=https://<your-service>.onrender.com/api/telegram/webhook \
     -d secret_token=<TELEGRAM_WEBHOOK_SECRET from the Render env>
   ```

Doing it by hand instead of a Blueprint: New → Web Service, root directory
`Backend`, build `pip install -r requirements.txt`, start
`python setup_db.py && uvicorn main:app --host 0.0.0.0 --port $PORT`, then add
the environment variables from the table above with `ENVIRONMENT=production`.

---

## Project layout

```
nagarvaani-full.html   all pages (citizen app + official portal)
css/styles.css
js/                    api · nav · feed · detail · submit · nearme · corruption · official · govt · auth · voice · i18n · ui · main
Backend/
  main.py              app, CORS, startup guard, serves the frontend
  setup_db.py          create tables (SQLite or Postgres)
  seed_data.py         demo users + 5 AI-scored complaints
  app/
    config.py          settings from .env
    database.py        async engine / session
    models/models.py   User · District · Complaint · Vote · Comment · LinkedArea · StatusLog
    schemas/           pydantic request/response shapes
    routers/           auth · complaints · stats · media · telegram · translate
    services/          ai_engine · auth · email · jurisdiction · rate_limit · stt · media_storage · telegram_client
render.yaml            Render Blueprint
```
