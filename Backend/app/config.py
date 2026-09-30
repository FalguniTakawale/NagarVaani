from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"  # "development" | "production"
    frontend_url: str = ""            # Render deploy URL — the only allowed CORS origin outside development

    anthropic_api_key: str = ""
    gemini_api_key: str = ""  # ai_engine.py uses this by default (free tier) — set anthropic_api_key too to switch back
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 30  # "stay signed in" — a month before a re-login is needed
    database_url: str = "sqlite+aiosqlite:///./nagarvaani.db"

    # Google Sign-In (Google Identity Services) — a real OAuth Client ID from
    # console.cloud.google.com, "OAuth client ID" → "Web application". Public
    # by design (it's embedded in the frontend), unlike every other key here.
    google_client_id: str = ""

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""  # sent by Telegram as X-Telegram-Bot-Api-Secret-Token
    openai_api_key: str = ""       # STT fallback option — see stt.py _PROVIDER
    groq_api_key: str = ""         # STT fallback option — free-hosted Whisper, OpenAI-SDK-compatible
    huggingface_api_key: str = ""  # STT default — free serverless Inference API

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # Gmail SMTP for signup OTP + welcome mail. All blank = emails are printed
    # to the server log instead of sent (local dev).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""  # defaults to smtp_user

    # Brevo transactional email over HTTPS (api.brevo.com) — preferred on hosts
    # that block outbound SMTP ports (Render free tier). The sender address must
    # be verified in Brevo (Senders, Domains & Dedicated IPs → Senders).
    brevo_api_key: str = ""          # "xkeysib-…" from SMTP & API → API Keys (NOT the SMTP key)
    brevo_sender_email: str = ""
    brevo_sender_name: str = "NagarVaani"

    # Demo/prototype escape hatch: set REQUIRE_EMAIL_VERIFICATION=false when the
    # host can't send email (e.g. Render free tier blocks SMTP). New citizen
    # accounts are then verified immediately and stuck unverified ones are
    # verified on next login. Default true = normal OTP flow. Do not disable this
    # on a real deployment; official accounts still need admin approval either way.
    require_email_verification: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
