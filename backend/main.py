import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from .auth import SESSION_COOKIE, is_auth_enabled, verify_session_token
from .database import init_db, SessionLocal
from . import models
from .routers import channels, settings as settings_router, videos, health as health_router
from .routers import auth as auth_router
from . import scheduler as sched_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

DEFAULT_SETTINGS = {
    "metube_url":       os.getenv("METUBE_URL",       "http://localhost:8081"),
    "check_interval":   os.getenv("CHECK_INTERVAL",   "60"),
    "jellyfin_url":     os.getenv("JELLYFIN_URL",     ""),
    "jellyfin_api_key": os.getenv("JELLYFIN_API_KEY", ""),
}


def _init_db() -> None:
    init_db()
    db = SessionLocal()
    try:
        for key, value in DEFAULT_SETTINGS.items():
            if not db.query(models.Setting).filter(models.Setting.key == key).first():
                db.add(models.Setting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _get_setting(key: str) -> str:
    db = SessionLocal()
    try:
        row = db.query(models.Setting).filter(models.Setting.key == key).first()
        return row.value if row else DEFAULT_SETTINGS.get(key, "")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    interval = int(_get_setting("check_interval"))
    sched_module.start_scheduler(interval)
    logger.info("TubeChecker started")
    yield
    sched_module.shutdown_scheduler()
    logger.info("TubeChecker stopped")


app = FastAPI(
    title="TubeChecker",
    description="Watches YouTube channels via RSS and sends new videos to MeTube",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Auth middleware ────────────────────────────────────────────────────────────
# Paths that are always public (login UI + auth endpoints + status check).
_AUTH_BYPASS = {"/login", "/auth/login", "/auth/logout", "/api/auth/status"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_auth_enabled():
            return await call_next(request)

        if request.url.path in _AUTH_BYPASS:
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        if token and verify_session_token(token):
            return await call_next(request)

        # Unauthenticated — API gets 401, browser pages get a redirect.
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        next_path = request.url.path
        if request.url.query:
            next_path = f"{next_path}?{request.url.query}"
        return RedirectResponse(url=f"/login?next={next_path}", status_code=302)


app.add_middleware(AuthMiddleware)

# --- API routers (registered before the static file mount) ---
app.include_router(auth_router.router)
app.include_router(channels.router)
app.include_router(settings_router.router)
app.include_router(videos.router)
app.include_router(health_router.router)

# --- Frontend static files ---
# Mounted last so API routes take precedence
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
