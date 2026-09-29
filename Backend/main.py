import hashlib
import os
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import get_settings
from app.database import create_tables
from app.routers import admin, auth, chatbot, complaints, media, stats, subscriptions, telegram, translate

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
    frontend_url = settings.frontend_url
    if not frontend_url:
        # Render injects its own service URL into every deploy — a real,
        # correct value, not a guess. Using it as a fallback means a first
        # deploy with FRONTEND_URL left blank still boots (so you can see
        # the assigned URL and log in), instead of crashing before you ever
        # get to that point. Only falls back on Render specifically:
        # RENDER_EXTERNAL_URL isn't set on other hosts, so this stays a
        # hard requirement everywhere else, as originally intended.
        frontend_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    allowed_origins = [o.strip().rstrip("/") for o in frontend_url.split(",") if o.strip()]
    if not allowed_origins:
        raise RuntimeError(
            "FRONTEND_URL is empty but ENVIRONMENT is not 'development' — "
            "set FRONTEND_URL to your deployment's real URL (e.g. https://nagarvaani.onrender.com)."
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=not IS_DEV,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=(self)")
    if not IS_DEV:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # This app ships as one HTML file + a handful of small JS/CSS files that
    # change constantly during development/demo prep — a stale cached copy
    # of one but not the other (e.g. new HTML with an i18n key the browser's
    # still-cached js/i18n.js doesn't have yet) produces confusing bugs that
    # look like a real code issue but are actually just the browser serving
    # an old file. Not worth the bandwidth savings for files this small.
    if request.url.path.startswith("/js/") or request.url.path.startswith("/css/") or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


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

    def _asset_version() -> str:
        """A hash of every js/css file's mtime — changes automatically
        whenever a file changes (every --reload, every deploy), and gets
        appended to each asset URL below as ?v=<hash>. This is the actual
        fix for "I edited the code but the browser still shows the old
        thing": Cache-Control headers are a *request* to the browser, which
        some setups still ignore; a different URL isn't a request, the
        browser has no old response to serve for a URL it's never seen."""
        parts = []
        for sub in ("js", "css"):
            d = FRONTEND_DIR / sub
            if d.exists():
                for f in sorted(d.glob("*")):
                    parts.append(f"{f.name}:{f.stat().st_mtime_ns}")
        return hashlib.md5("|".join(parts).encode()).hexdigest()[:10]

    _ASSET_VERSION = _asset_version()

    @app.get("/", include_in_schema=False)
    async def frontend():
        html = FRONTEND_HTML.read_text(encoding="utf-8")
        html = re.sub(
            r'((?:src|href)=")(js|css)/([^"?]+)(")',
            rf'\1\2/\3?v={_ASSET_VERSION}\4',
            html,
        )
        return HTMLResponse(html)
