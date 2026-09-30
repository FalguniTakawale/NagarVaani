# NagarVaani — Your Voice, Your City · नगरवाणी

**Live prototype:** https://nagarvaani-2i2l.onrender.com  
**Built for:** GDG India / Hack2Skill — *Build with AI: Code for Communities*, Track 1 (AI for Digital Public Infrastructure & Governance, BRICS theme: Innovation)

NagarVaani is a civic-intelligence layer between citizens and government. People report
infrastructure problems in their own language — by web form, **voice note** or **Telegram** — and
every report is ranked on **how dangerous and urgent the problem really is** (safety risk, season,
people affected, cross-area pattern), **not on vote count**. Officials get a jurisdiction-scoped
queue, AI-written briefs, a live hotspot map and a data-driven list of where demand is highest.
Votes and comments do a different job: **accountability and transparency**.

> **Low votes ≠ low importance.** In our demo data a village handpump with **1 vote** scores
> **98.7**; a pothole-ridden road with **104 votes** scores **40.6**.

## Documentation

| Read | What's in it |
|---|---|
| [`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md) · [PDF](docs/NagarVaani_Project_Report.pdf) | The full project document: problem, insight, solution, scoring, what's real vs stub vs demo, testing & security, challenge fit, expansion, roadmap |
| [`docs/NagarVaani_Pitch_Deck.pdf`](docs/NagarVaani_Pitch_Deck.pdf) | The same story as a slide deck |
| [`PRIVACY.md`](PRIVACY.md) | What data is collected and where it goes |
| In the app: **How scoring works (L1–L5)** | The scoring explained in plain language for citizens |

## What it does

**Citizens** — report by text, mic (Hindi / Marathi / Tamil / English, Hinglish understood) or Telegram, with photos and GPS (the area name is looked up automatically) · anonymous or signed in · track by ID · feeds: Home, Trending (nationwide, paginated), Near Me (radius, heatmap, email alerts), My complaints, My votes · vote, comment, "same issue in my area" · see similar issues across the whole city and "see also across the country", with resolved/unresolved counts · translate any complaint or comment · 🔊 read-aloud · share · ⚑ flag abuse · dispute a false "resolved" · separate login-gated corruption channel.

**Officials** — admin-approved accounts (work e-mail only) at ward / city / state / central level · severity-ranked queue · hotspot map · mark in-progress / resolved (only inside their own jurisdiction) · investment flags · **project priorities** (unresolved demand by state and problem type, joined with Census-2011 population and mapped to the real central scheme that would fund it) with CSV download · admin verification queue.

**Platform** — e-mail OTP sign-up and password reset · optional Google sign-in · rate limits and security headers · Telegram webhook that registers itself on deploy · e-mail through Brevo (HTTPS) with SMTP fallback · optional features switch on when their key is present and otherwise fail with a clear message.

## Tech stack

Python · FastAPI · SQLAlchemy (async) · PostgreSQL (Neon) / SQLite · vanilla JavaScript ES modules · Leaflet + OpenStreetMap · Google Gemini (Claude switchable in one line) · Whisper speech-to-text (Hugging Face / Groq / OpenAI) · Web Speech API (read-aloud) · Cloudinary · Telegram Bot API · Brevo · Render.

## Real vs stub vs demo (short version)

- **Real, end to end:** intake, AI pipeline, L1–L5 scoring, votes/comments/links, status workflow with jurisdiction enforcement, notifications, auth and official approval, hotspot map and statistics, priorities + CSV, translation, read-aloud.
- **Stub / partial (by design):** the population factor is a default of 10,000 (the per-area table isn't wired in); **no infrastructure-index or investment-plan data**; **no project costs** (none are invented); no moderation *screen* for flags (API only); volunteer forms just send e-mail; "Our Impact" trees/recycling tiles say "Coming soon".
- **Demo content (labelled):** `seed_data.py` users and complaints, "Supporters" cards on Get Involved, example cards before live data loads.
- **Not built:** WhatsApp / SMS intake, countries other than India, installable/offline mode.

Full detail and the reasoning are in [`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md).

## Expansion path

Real district-level population + one infrastructure dataset → "investment gap" view · a `country` field and a data pack per BRICS nation · WhatsApp/SMS channels · costed recommendations · impact dashboard (time-to-resolve, dispute rate, neglect index) · moderation UI and duplicate merging · open-data export for Digital-Public-Good status.

Licensed under [MIT](LICENSE).

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

**Testing the official portal / admin:** run `python create_test_officials.py` (add `--allow-production` on a deployed DB, from the Render Shell). It creates three pre-approved accounts — `admin.test@nagarvaani.gov.in` (central + admin), `ward.test@…` (Ward 12, Pune) and `state.test@…` (Maharashtra) — with **random passwords printed once** (nothing hardcoded). No shell (Render free)? Set `BOOTSTRAP_ADMIN_EMAIL` + `BOOTSTRAP_ADMIN_PASSWORD` in the service environment instead and redeploy — startup creates one approved admin; remove the variables afterwards. Remove script-made accounts with `--remove` when done; never leave test admins on a public site.

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
| `GEMINI_API_KEY` | **Yes** for AI | Default language model (Gemini, free tier) — filter, classify, brief, place detection, translation, chatbot. Without it every AI step fails open: the complaint is still accepted (category `other`) and translation returns a clear error. |
| `ANTHROPIC_API_KEY` | No | Only if you switch `_PROVIDER` to `"anthropic"` in `ai_engine.py` to use Claude instead. |
| `DATABASE_URL` | Yes | `sqlite+aiosqlite:///./nagarvaani.db` locally, or a Postgres URL (Neon etc.). `postgres://` / `postgresql://` are rewritten to the asyncpg driver; `sslmode` / `channel_binding` query parameters are handled. |
| `JWT_SECRET` | Yes in prod | Signs login tokens. The default `dev-secret-change-me` is refused unless `ENVIRONMENT=development`. |
| `ENVIRONMENT` | No (`development`) | `development` = open CORS, default JWT allowed, unsecured Telegram webhook allowed, no webhook auto-registration. Anything else = locked down. |
| `FRONTEND_URL` | Yes in prod | The only CORS origin allowed outside development (falls back to Render's `RENDER_EXTERNAL_URL`). |
| `HUGGINGFACE_API_KEY` · `GROQ_API_KEY` · `OPENAI_API_KEY` | For voice notes | Whisper speech-to-text. The first key found is used (Groq → Hugging Face → OpenAI); `STT_PROVIDER` can force one. The mic has a language picker (Hindi / Marathi / Tamil / English / auto) that is passed to the model as a hint. |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | No | Complaint photo / 360° uploads. Without them uploads return a clear error and the complaint submits without images. |
| `TELEGRAM_BOT_TOKEN` | No | From @BotFather. Enables the Telegram channel. |
| `TELEGRAM_WEBHOOK_SECRET` | Prod if bot used | Any string of letters, numbers, `_` and `-`. The app registers the webhook with Telegram itself at startup (production only) and rejects requests without this secret. |
| `BREVO_API_KEY` / `BREVO_SENDER_EMAIL` | No (recommended on Render) | Brevo transactional e-mail over HTTPS for OTP + notifications. The key is the `xkeysib-…` **API key** (not the SMTP key) and the sender must be verified in Brevo. Takes precedence over SMTP. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | No | SMTP fallback (Render's free tier blocks the usual SMTP ports). With no e-mail provider at all, the OTP is printed to the server log. |
| `REQUIRE_EMAIL_VERIFICATION` | No (`true`) | Set `false` only on a demo host that cannot send e-mail: new citizen accounts are verified immediately. Never on a real deployment. |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | No | Creates/resets one approved admin at startup (hosts with no shell). Remove both after testing. |
| `GOOGLE_CLIENT_ID` | No | "Continue with Google". Public by design; without it the button is hidden. |


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
 │  services/ai_engine.py   ── LLM ─────►  0 Whisper STT (only if audio)     │
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

   Frontend: nagarvaani-full.html + css/ + js/ (18 ES modules, no framework),
   served by the same FastAPI process at / — Leaflet + OpenStreetMap for maps.
```

**Priority score** (`score_complaint`, `ai_engine.py`):
`severity = L1 safety (+40) + L3 category weight + L4 log-population + L5 linked-area bonus`,
then `score = min(100, severity × L2 seasonal multiplier)` (the season is fixed when first scored).
Safety risks instead score in a **90–99 band ordered by severity**, with votes adding at most +1;
everything else gets a gentle `× (1 + 0.1·log10(votes+1))` nudge. Votes are the weakest signal by
construction — they can reorder similar issues but never lift a non-critical one above a critical one.

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
| `POST` | `/complaints/{id}/comments` | optional | Comment; the AI scans for place names and auto-links them |
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
7. Telegram (optional): **the webhook is registered automatically at startup** when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` (letters, numbers, `_`, `-` only) are set — check the deploy log for `[telegram] webhook registered`. To do it by hand instead —
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
js/                    api · nav · feed · detail · submit · nearme · corruption · official · govt · auth · voice · speak · chatbot · getinvolved · forofficials · i18n · ui · main
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
