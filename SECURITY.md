# Security notes

Audit performed on the final prototype (backend `Backend/`, frontend `js/`). This is a code review + smoke tests, **not** a penetration test.

## Fixed in this revision
| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | **Critical** | `POST /auth/verify-email` returned a login token for any *already-verified* `user_id` without an OTP, and the public complaint endpoint exposed the author's `author_id` → anyone could take over a complainant's account. | Endpoint now refuses already-verified accounts; complaint API no longer returns `author_id` (returns `is_author` boolean instead). |
| 2 | High | No brute-force protection: 6-digit signup/reset OTP (1M values) and passwords could be guessed. | Rate limits: 10 logins/15 min per email, 30/IP; 5 OTP attempts/15 min per account; same for reset; sign-up 10/h per IP. |
| 3 | High | Any approved official could change the status of **any** complaint nationwide. | `PATCH /complaints/{id}/status` now enforces the official's jurisdiction (ward/city/state; central = nationwide). |
| 4 | Medium | Anyone could forge an "Investment Flag" by typing `[OFFICIAL FLAG]` in a comment, and post under any name (incl. an official's). | Prefix reserved for officials; signed-in users always post under their own account name. |
| 5 | Medium | Stored XSS path: image URL interpolated into an inline `onclick` (entity-escaping does not protect JS-in-attribute). | Inline JS removed (anchor with `rel=noopener`), https-only URLs enforced in schema **and** client; `escapeHtml` now also escapes quotes. |
| 6 | Medium | Unauthenticated LLM-cost endpoints (translate, comments, link-area) without limits. | Per-IP rate limits added. |
| 7 | Low | No input length limits (text, comments, notes, images); passwords >72 bytes crash bcrypt. | Pydantic length limits; password max 72. |
| 8 | Low | No security headers. | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS (prod). |
| 9 | Deploy | `render.yaml` didn't declare `GEMINI_API_KEY` / `HUGGINGFACE_API_KEY` (the actual default providers) → AI silently failed open in production. | Added to the blueprint. |

Verified by automated smoke tests (see the session log): anonymous/duplicate/invalid flag → 401/409/422; forged official flag → 403; out-of-jurisdiction status change → 404; `javascript:` image URL → 422; login brute force → 429 after 10; OTP brute force → 429 after 5; already-verified verify-email → 400.

## Remaining risks / recommendations
* **Seed accounts** (`ramesh@test.com / Test@1234`, `official@test.com / Official@1234`) are published in the README. Never seed a public deployment; or delete/rotate them. The seeded official is pre-approved.
* **`X-Forwarded-For` is trusted** by the rate limiter (`services/rate_limit.py`); behind Render this is normally fine, but a client that can reach the app directly can spoof it. Use a trusted-proxy setting or Redis-backed limits on multi-instance deployments.
* **No CSP**: the frontend relies on inline `onclick` handlers. Moving to `addEventListener` would allow a strict Content-Security-Policy.
* JWTs last 30 days and are not revocable (no logout-everywhere). Consider shorter expiry + refresh.
* AI filter **fails open** by design (availability over strictness). For a production civic system, queue the complaint for human review instead.
* Telegram in-memory state and link codes reset on restart; in `development` the webhook secret is optional — always set `ENVIRONMENT=production` + `TELEGRAM_WEBHOOK_SECRET` when deployed.
* `/docs` (Swagger) is exposed in production; disable if not wanted.
* Anonymous complaints/comments are accepted (by design, per-IP limited). Determined abuse would need CAPTCHA.
* Dependencies were not pinned or scanned; run `pip-audit` before release.
* Secrets: none are committed (`.env` is git-ignored). `google_client_id` is public by design.
