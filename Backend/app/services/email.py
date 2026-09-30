"""
Outbound email over SMTP (Gmail app-password setup in .env.example).

With no BREVO_API_KEY/SMTP_HOST/USER/PASS configured, every email is printed to the server
log instead — so the OTP flow can be exercised locally without an account,
while a production deploy that forgot SMTP fails loudly in the logs rather
than silently skipping verification.
"""

import asyncio
import html as _html
import smtplib
from email.message import EmailMessage

from app.config import get_settings

settings = get_settings()


def _brevo_configured() -> bool:
    return bool(settings.brevo_api_key and settings.brevo_sender_email)


def is_configured() -> bool:
    return _brevo_configured() or bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


async def _send_brevo(to: str, subject: str, text: str, html: str | None) -> bool:
    """Brevo transactional API — plain HTTPS, so it works where SMTP is blocked."""
    import httpx
    body = {
        "sender": {"name": settings.brevo_sender_name or "NagarVaani", "email": settings.brevo_sender_email},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        body["htmlContent"] = html
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.brevo.com/v3/smtp/email", json=body,
                              headers={"api-key": settings.brevo_api_key, "accept": "application/json"})
    if r.status_code >= 300:
        # Body says why (e.g. "sender not valid", "unauthorized") — never includes our key.
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:300]}")
    return True


def _send_sync(to: str, subject: str, text: str, html: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass)
        server.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Returns True if handed to SMTP, False if it was only logged (dev) or failed."""
    if not is_configured():
        print(f"[DEV EMAIL — SMTP not configured] to={to} subject={subject!r}\n{text}\n")
        return False
    try:
        if _brevo_configured():
            return await _send_brevo(to, subject, text, html)
        await asyncio.to_thread(_send_sync, to, subject, text, html)
        return True
    except Exception as e:
        print(f"[EMAIL FAILED] to={to} subject={subject!r}: {e}")
        return False


async def send_otp_email(to: str, name: str, otp: str) -> bool:
    text = (
        f"Hi {name},\n\n"
        f"Your NagarVaani verification code is: {otp}\n\n"
        "It expires in 15 minutes. If you didn't create an account, ignore this email.\n"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">Verify your email</h2>
      <p>Hi {name}, enter this code in NagarVaani to finish creating your account:</p>
      <div style="font-size:32px;font-weight:700;letter-spacing:8px;background:#F0EFE9;
                  padding:16px 24px;border-radius:8px;text-align:center;color:#0F2042">{otp}</div>
      <p style="color:#64748B;font-size:13px">Expires in 15 minutes. Didn't sign up? Ignore this email.</p>
    </div>"""
    return await send_email(to, "Your NagarVaani verification code", text, html)


async def send_password_reset_email(to: str, name: str, otp: str) -> bool:
    text = (
        f"Hi {name},\n\n"
        f"Your NagarVaani password reset code is: {otp}\n\n"
        "It expires in 15 minutes. If you didn't request this, ignore this email — your password is unchanged.\n"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">Reset your password</h2>
      <p>Hi {name}, enter this code in NagarVaani to set a new password:</p>
      <div style="font-size:32px;font-weight:700;letter-spacing:8px;background:#F0EFE9;
                  padding:16px 24px;border-radius:8px;text-align:center;color:#0F2042">{otp}</div>
      <p style="color:#64748B;font-size:13px">Expires in 15 minutes. Didn't request this? Ignore this email — your password stays the same.</p>
    </div>"""
    return await send_email(to, "Reset your NagarVaani password", text, html)


async def send_official_approved_email(to: str, name: str, new_email: str, password: str) -> bool:
    text = (
        f"Hi {name},\n\n"
        "Your official account on NagarVaani has been verified and approved by an admin.\n\n"
        f"Login email: {new_email}\n"
        f"Temporary password: {password}\n\n"
        "Please sign in and change this password from your account settings.\n"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">Your official account is approved</h2>
      <p>Hi {name}, an admin has verified and approved your official account on NagarVaani.</p>
      <div style="background:#F0EFE9;padding:16px 20px;border-radius:8px;margin:16px 0">
        <p style="margin:0 0 6px"><strong>Login email:</strong> {new_email}</p>
        <p style="margin:0"><strong>Temporary password:</strong> {password}</p>
      </div>
      <p style="color:#64748B;font-size:13px">Please sign in and change this password from your account settings as soon as you can.</p>
    </div>"""
    return await send_email(to, "Your NagarVaani official account is approved", text, html)


async def send_official_rejected_email(to: str, name: str, reason: str | None) -> bool:
    reason_line = f"\nReason: {reason}\n" if reason else ""
    text = (
        f"Hi {name},\n\n"
        "Your application for an official account on NagarVaani could not be verified and was not approved."
        f"{reason_line}\n"
        "If you believe this is a mistake, reply to this email.\n"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">Official account application not approved</h2>
      <p>Hi {name}, your application for an official account on NagarVaani could not be verified.</p>
      {f'<p style="color:#44474D">Reason: {reason}</p>' if reason else ''}
      <p style="color:#64748B;font-size:13px">If you believe this is a mistake, reply to this email.</p>
    </div>"""
    return await send_email(to, "Your NagarVaani official account application", text, html)


STATUS_LABELS = {
    "open": "Open", "in_progress": "In progress",
    "resolved": "Resolved ✓", "disputed": "Disputed", "rejected": "Rejected",
}


async def send_status_update_email(
    to: str, name: str, complaint_id: str, complaint_title: str,
    new_status: str, note: str | None, official_name: str,
) -> bool:
    label = STATUS_LABELS.get(new_status, new_status)
    short_id = complaint_id[:8]
    note_line = f"\nNote from {official_name}: {note}\n" if note else ""
    dispute_line = (
        '\nNot actually fixed? Sign in and dispute this from "My complaints" on NagarVaani.\n'
        if new_status == "resolved" else ""
    )
    text = (
        f"Hi {name},\n\n"
        f"Your complaint \"{complaint_title}\" (ID {short_id}) is now: {label}\n"
        f"{note_line}{dispute_line}"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">Your complaint status changed</h2>
      <p style="color:#44474D;margin-bottom:4px">"{complaint_title}"</p>
      <p style="color:#94A3B8;font-size:12px;margin-bottom:16px">ID {short_id}</p>
      <div style="background:#F0EFE9;padding:14px 18px;border-radius:8px;margin-bottom:16px">
        <strong style="color:#0F2042;font-size:16px">{label}</strong>
        {f'<p style="margin:8px 0 0;color:#44474D;font-size:13px">Note from {official_name}: {note}</p>' if note else ''}
      </div>
      {'<p style="color:#64748B;font-size:13px">Not actually fixed? Sign in and dispute this from "My complaints" on NagarVaani.</p>' if new_status == "resolved" else ''}
    </div>"""
    return await send_email(to, f'Your complaint is now "{label}" — NagarVaani', text, html)


async def send_welcome_email(to: str, name: str) -> bool:
    text = (
        f"Welcome to NagarVaani, {name}!\n\n"
        "Your email is verified. Report civic issues in any language, vote on what matters,\n"
        "and watch your ward's problems get scored on severity — not crowd size.\n"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042">Welcome to NagarVaani 🇮🇳</h2>
      <p>Hi {name}, your email is verified and your account is live.</p>
      <ul style="color:#44474D;line-height:1.7">
        <li>Report issues by text, voice note, or Telegram — any language</li>
        <li>Vote on your ward's complaints, or in solidarity anywhere in India</li>
        <li>Every complaint is scored on severity, season and pattern — not votes</li>
      </ul>
      <p style="color:#64748B;font-size:13px">Your voice, your city.</p>
    </div>"""
    return await send_email(to, "Welcome to NagarVaani 🇮🇳", text, html)


async def send_neighborhood_confirm_email(to: str, label: str, radius_km: float, unsubscribe_url: str) -> bool:
    safe_label = _html.escape(label or "your area")
    text = (
        f"You're subscribed to NagarVaani alerts for {label or 'your area'} "
        f"(within {radius_km:g} km).\n\n"
        "You'll get an email whenever a new civic issue is reported nearby, and again when one near "
        f"you gets marked resolved.\n\nDidn't request this? Unsubscribe any time: {unsubscribe_url}\n"
    )
    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">You're subscribed</h2>
      <p>You'll get an email whenever a new civic issue is reported within <b>{radius_km:g} km</b> of
      <b>{safe_label}</b>, and again when one near you gets marked resolved.</p>
      <p style="color:#64748B;font-size:13px">Didn't request this? <a href="{unsubscribe_url}">Unsubscribe</a> any time — no account needed.</p>
    </div>"""
    return await send_email(to, "You're subscribed to NagarVaani neighborhood alerts", text, html_body)


async def send_neighborhood_alert_email(
    to: str, label: str, event: str, category_label: str, complaint_title: str,
    distance_km: float, complaint_id: str, unsubscribe_url: str,
) -> bool:
    """event: 'reported' | 'resolved'."""
    safe_title = _html.escape((complaint_title or "")[:140])
    safe_label = _html.escape(label or "your area")
    verb = "A new issue was reported" if event == "reported" else "An issue near you was marked resolved"
    text = (
        f"{verb} near {label or 'your area'} ({distance_km:.1f} km away):\n"
        f'"{complaint_title[:140]}" — {category_label}\n\n'
        f"Complaint ID: {complaint_id[:8]}\n\n"
        f"Unsubscribe from these alerts: {unsubscribe_url}\n"
    )
    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;color:#1C1C1E">
      <h2 style="color:#0F2042;margin-bottom:4px">{'🆕 New issue nearby' if event == 'reported' else '✓ Issue near you resolved'}</h2>
      <p style="color:#44474D">{verb} near <b>{safe_label}</b> ({distance_km:.1f} km away):</p>
      <div style="background:#F0EFE9;padding:14px 18px;border-radius:8px;margin:12px 0">
        <p style="margin:0 0 4px"><strong>{category_label}</strong></p>
        <p style="margin:0;color:#44474D">{safe_title}</p>
      </div>
      <p style="color:#94A3B8;font-size:12px">ID {complaint_id[:8]}</p>
      <p style="color:#64748B;font-size:13px"><a href="{unsubscribe_url}">Unsubscribe</a> from these alerts any time.</p>
    </div>"""
    subject = "New issue near you — NagarVaani" if event == "reported" else "An issue near you was resolved — NagarVaani"
    return await send_email(to, subject, text, html_body)
