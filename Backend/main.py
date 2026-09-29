from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import get_settings
from app.database import create_tables
from app.routers import admin, auth, chatbot, complaints, insights, media, stats, subscriptions, telegram, translate

settings = get_settings()
IS_DEV = settings.environment.lower() == "development"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not IS_DEV and settings.jwt_secret == "dev-secret-change-me":
        raise RuntimeError(
            "Refusing to start: JWT_SECRET is still the default 'dev-secret-change-me' "
            f"while ENVIRONMENT='{settings.environment}'. Anyone could forge login tokens. "
            "Set JWT_SECRET in .env to a long random string "
            "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`), "
            "or set ENVIRONMENT=development for local work."
        )
    # Create all tables on startup
    await create_tables()
    yield


app = FastAPI(
    title="NagarVaani API",
    description="Civic complaint platform — AI-powered priority scoring",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — wide open in development, locked to the deployed frontend otherwise.
# (Browsers reject allow_credentials=True together with "*", so credentials are
# only enabled when we have a concrete origin list.)
if IS_DEV:
    allowed_origins = ["*"]
else:
    allowed_origins = [o.strip().rstrip("/") for o in settings.frontend_url.split(",") if o.strip()]
    if not allowed_origins:
        raise RuntimeError(
            "FRONTEND_URL is empty but ENVIRONMENT is not 'development' — "
            "set FRONTEND_URL to your Render URL (e.g. https://nagarvaani.onrender.com)."
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=not IS_DEV,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers. No CSP yet: the frontend still uses inline
    onclick handlers, so a strict CSP would break it (documented in SECURITY.md)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(self), microphone=(self)")
    if not IS_DEV:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(complaints.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(telegram.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(translate.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(chatbot.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(insights.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "NagarVaani API", "version": "1.0.0"}


@app.get("/api")
async def root():
    return {
        "service": "NagarVaani",
        "docs": "/docs",
        "health": "/api/health",
        "endpoints": {
            "auth": "/api/auth/register, /api/auth/login",
            "complaints": "/api/complaints",
            "stats": "/api/stats/ward, /api/stats/nationwide, /api/stats/map",
            "telegram": "/api/telegram/webhook",
            "media": "/api/stt, /api/media/upload",
            "translate": "/api/translate",
        }
    }


# ── Frontend ──────────────────────────────────────────────────────────────────
# One Render web service serves both the API and the static frontend, so the
# browser talks to /api on the same origin (see API_BASE in js/api.js).
FRONTEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_HTML = FRONTEND_DIR / "nagarvaani-full.html"

if FRONTEND_HTML.exists():
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")

    @app.get("/", include_in_schema=False)
    async def frontend():
        return FileResponse(FRONTEND_HTML)
