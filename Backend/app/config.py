from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"  # "development" | "production"
    frontend_url: str = ""            # Render deploy URL — the only allowed CORS origin outside development

    anthropic_api_key: str = ""
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    database_url: str = "sqlite+aiosqlite:///./nagarvaani.db"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""  # sent by Telegram as X-Telegram-Bot-Api-Secret-Token
    openai_api_key: str = ""  # STT only — Claude has no audio input

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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
