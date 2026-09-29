# Privacy & Data Handling

NagarVaani is built as a Digital Public Good — this note is a plain-language
account of what data the platform actually collects and where it goes,
kept in sync with the code rather than written as a generic template.

## What we collect

- **Account holders**: name, email, password (bcrypt-hashed, never stored in
  plain text), and optionally city/ward/state to scope your local feed.
- **Complaints**: the report text (original + AI translation), category,
  location (free text and/or coordinates), and any photos you attach.
  **You can submit a complaint without an account** — no name or email is
  collected for anonymous reports, only a tracking ID.
- **Officials**: a work email is required (personal providers like Gmail are
  rejected) and every official account is reviewed by an admin before it gets
  jurisdiction-level access — see the Ministry/Official Verification flow.
- **Telegram**: only if you explicitly link your account; we store your
  Telegram chat ID to deliver status-update messages, nothing else from your
  Telegram account.

## Where it goes

Complaint text and photos are processed by third-party AI services to
classify, score, and translate reports:

- **Google Gemini** (default) or **Anthropic Claude** — text classification,
  severity scoring, translation, and the home-page chatbot's answers.
- **OpenAI Whisper** (or an equivalent speech-to-text provider) — transcribes
  voice-note reports.
- **Cloudinary** — stores uploaded complaint photos.
- **Brevo (SMTP)** — sends OTP, password-reset, and status-update emails.

We don't sell data, and we don't share it with anyone beyond the providers
above needed to run the feature you used (e.g. a text-only complaint never
touches Cloudinary; a complaint you submit anonymously is never linked to an
email at all).

## Your controls

- Report anonymously any time — the option is on the submit form, not hidden.
- Turn off status-change notifications from your account settings
  (`notify_status_change`); this also stops the status-update emails.
- Dispute a complaint marked "resolved" if it wasn't actually fixed — this is
  a citizen-facing check on official claims, not just a one-way report box.

## What this note is not

This is a hackathon-stage prototype, not a production deployment with a legal
privacy policy, a data retention schedule, or a data-protection officer. If
NagarVaani moves toward real deployment, this file is the starting point for
one, not a substitute for it.
