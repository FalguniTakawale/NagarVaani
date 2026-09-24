"""
Outbound email over SMTP (Gmail app-password setup in .env.example).

With no SMTP_HOST/USER/PASS configured, every email is printed to the server
log instead — so the OTP flow can be exercised locally without an account,
while a production deploy that forgot SMTP fails loudly in the logs rather
than silently skipping verification.
"""

import asyncio
import smtplib
from email.message import EmailMessage

from app.config import get_settings

settings = get_settings()


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


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
