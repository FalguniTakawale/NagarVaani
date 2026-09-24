# NagarVaani — Project Document
**Version 1.0** · Last updated: Sep 11, 2026
**Hackathon:** Build with AI: Code for Communities (H2S / hack2skill)
**Track:** Track 1 — AI for Digital Public Infrastructure & Governance (BRICS Theme: Innovation)
**Deadline:** 30 September 2026, 11:59 PM IST

---

## 1. Core Idea & North Star

> Low votes ≠ low importance. A village with 2 internet users shouldn't have its crisis ignored.

NagarVaani is a civic intelligence layer between citizens and government. Citizens post complaints. AI scores them intelligently — not by vote count, but by severity, seasonal context, population density, and cross-area patterns. Government sees synthesized, actionable briefs. Both sides see each other's actions publicly.

---

## 2. What Makes Us Different

| Our addition | Why it's beyond existing platforms |
|---|---|
| Priority scoring (6-level hierarchy) | Not raw votes — severity × season × density |
| Seasonal urgency multiplier | Garbage in monsoon scores higher than in December |
| Low-vote surfacing for villages | 1 vote from a village can score 91 |
| Political/communal filter | Pre-moderation by AI before post goes live |
| Stack Overflow thread model | "Same issue in my area" links complaints across districts |
| Citizen dispute button | Can reopen a resolved complaint if it isn't actually fixed |
| Raw vs synthesized view | Citizens post raw; officials see AI brief |
| NLP comment detection | Mention a place in a comment → auto-linked to complaint |
| Infrastructure investment recommendations | Not just fix complaints — recommend ₹Cr-level projects |
| Corruption reporting section | Separate from infrastructure complaints |

---

## 3. Pages & What Goes in Each

### Home
- Scope: **user's ward only** (set at onboarding)
- Feed: priority-sorted complaint cards
- Can upvote complaints in your ward
- Right panel: ward stats + personal complaint tracker + govt updates
- Sort options: by priority (default) / by votes / recent

### Trending
- Scope: **nationwide** — all wards, all areas
- Same complaint card format
- Anyone can vote for any complaint here (solidarity voting)
- Shows cross-district patterns surfaced by AI
- Purpose: people from cities can support village complaints they'd never see on home

### Near me
- Scope: **GPS/location radius** — complaints within X km of user's current location
- Useful for people who travel or work in a different area than they live
- Same card format

### My complaints
- List of complaints the logged-in user has submitted
- Status: open / in progress / resolved
- Dispute button on resolved complaints (if not actually fixed)
- Email notification status shown

### Complaint detail (Stack Overflow thread)
- Full complaint with score breakdown (shows exactly why it scored what it did)
- Photo strip with **captions** on each image
- Linked areas list (auto-updated when NLP detects place mentions in comments)
- Comment thread — anyone can add evidence or context
- "Same issue in my area" button — links your location to this complaint
- Translation button on complaint text and comments

### Submit complaint
- Text area — any language accepted
- Category picker (drainage, road, garbage, electricity, tree hazard, water supply)
- Location / area / ward field
- Photo + 360° image upload with caption field per image
- AI moderation notice
- Rejection message if AI flags communal/political framing — suggests rephrasing

### Government dashboard (role-gated, JWT)
- Top strip: official's ward + login identity
- 4 stat cards: critical / moderate / resolved / cross-district patterns
- Left: AI-synthesized briefs sorted by score (not votes)
  - Each brief: title, score, AI summary, translated citizen quote, action buttons
  - Action buttons: mark in progress / flag for investment / view photos
- Right: demand hotspot map + infrastructure investment recommendations with cost estimates
- Officials can post status updates (visible to citizens in transparency feed)

### Corruption report (separate section)
- Separate from infrastructure complaints
- Anonymous submission option
- Not mixed into the main feed

### Login / Signup
- Citizen tab: optional login (can browse without, must log in to post/vote)
- Official tab: mandatory JWT login
- On signup: must enter area + ward (app defaults home feed to this)

---

## 4. Priority Scoring Hierarchy

**Level 1 — Immediate safety risk** (overrides all, score floor 90+)
Physical harm possible in 24–72 hours: fallen tree on road, exposed wire, sewage near water source.

**Level 2 — Seasonal amplifier** (multiplier on base score)
- Drainage × monsoon = ×2.0
- Electricity × heatwave = ×1.8
- Road damage × post-rain = ×1.5

**Level 3 — Problem type base weight**
Drainage > water supply > electricity > road > garbage > streetlight > pothole

**Level 4 — Population density adjustment**
Same problem affecting 5,000 people scores higher than affecting 50. But village with 50 people and contaminated sole water source still triggers L1.

**Level 5 — Cross-district pattern bonus** (flat addition)
Same issue in 2+ other districts → systemic flag + score bonus. Also triggered by NLP detecting place names in comments.

**Level 6 — Raw vote count** (weakest, tiebreaker only)
Last input. Does not dominate. A complaint with 1 vote can score 91.

---

## 5. AI Logic (3 Claude API calls per submission)

**Call 1 — Filter**
Detect political/communal framing. If flagged: reject + suggest rephrasing. If clean: pass to Call 2.

**Call 2 — Classify + Extract**
- Problem type (drainage, road, etc.)
- Location extraction from text
- Severity classification (immediate safety / moderate / low)
- Language detection

**Call 3 — Score**
Apply 6-level hierarchy. Return: score (0–100), score breakdown by factor, seasonal multiplier applied, linked district check.

**Ongoing — NLP on comments**
When a comment is posted, scan for place name mentions. If detected: auto-link that place to complaint's linked-areas list. Increment linked count.

---

## 6. Data Model (4 tables)

**complaints** — id, text, translated_text, category, location, ward, score, score_breakdown (JSON), status, created_at, user_id, image_urls (JSON)

**votes** — id, complaint_id, user_id, area, is_solidarity_vote, created_at

**districts** — id, name, population, ward_number, seasonal_data (JSON)

**status_log** — id, complaint_id, old_status, new_status, updated_by (official_id), note, created_at

---

## 7. Architecture

```
Frontend (HTML + JS, static)
        ↓ REST API
Backend (FastAPI, Python) — Render
    ├── API routes (complaints, votes, stats, auth)
    ├── AI engine (Claude API — 3 calls per submission)
    ├── Translation layer (Claude API)
    ├── NLP comment scanner (Claude API)
    ├── Context service (date → season weight)
    ├── Image handler (Cloudinary)
    └── Auth (JWT for officials, optional for citizens)
        ↓ SQLAlchemy ORM
Database (PostgreSQL, Render free tier)

External: Claude API · Cloudinary · Render · GitHub
```

---

## 8. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | HTML + vanilla JS | Fast to build, easy deploy, no framework overhead |
| Backend | FastAPI (Python) | Falguni knows it, async, clean |
| Database | PostgreSQL | 4 tables, Render free tier |
| AI | Claude API (claude-sonnet-4-6) | Filter + classify + score |
| Images | Cloudinary | No filesystem headaches on Render |
| Hosting | Render | Free tier, easy deploy from GitHub |
| Auth | JWT | Simple, stateless, role-based |

---

## 9. What's IN the Prototype vs. Pitch Deck

**Build (prototype):**
- Complaint submission → AI filter + score → live on feed
- Home feed (ward-scoped)
- Trending feed (nationwide)
- Complaint detail with score breakdown + thread + linked areas
- Government dashboard with AI briefs + hotspot map + investment recs
- Status updates (official → citizen)
- NLP comment scanning → auto-link areas
- Image upload with captions
- Multilingual: post in any language, translate button on display

**Pitch deck only (future scope):**
- Voice input
- Volunteer registration
- Donation for disasters
- Urban vs rural filter
- SMS/WhatsApp integration for low-internet reach
- Full 22-language UI shell (prototype: 6 languages)

---

## 10. Project Plan

| Phase | Dates | Focus |
|---|---|---|
| Phase 1 | Sep 9–13 | Repo setup, DB schema, complaint API, AI filter + scoring engine |
| Phase 2 | Sep 14–19 | All frontend pages, govt dashboard, NLP comment scanner |
| Phase 3 | Sep 20–23 | Translation layer, seed data, mobile polish, deploy to production |
| Phase 4 | Sep 24–30 | Pitch deck PDF, demo video, buffer, submit |

**Hard rule:** Priority scoring engine complete before any frontend. Never cut it if behind schedule.

---

## 11. Demo Moment (the 30-second story)

Citizen submits drain complaint. 3 votes. Monsoon season. 7 linked districts.
→ AI scores it 94.

Pothole has 104 votes. Dry season. No links.
→ AI scores it 61.

Government dashboard shows drain above pothole.

**That's the product. Everything else is context for that moment.**

---

## 12. Submission Checklist

- [ ] GitHub repo (public) with README
- [ ] Live prototype URL (Render)
- [ ] Demo video — YouTube or Google Drive, public access
- [ ] PDF pitch deck (8–10 slides)
- [ ] Brief description of solution
- [ ] Challenge selected: Track 1
