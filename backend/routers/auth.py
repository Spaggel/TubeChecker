import os

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from ..auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    check_credentials,
    create_session_token,
    is_auth_enabled,
)

router = APIRouter(tags=["auth"])

# frontend/login.html lives two directories above this file (project root → frontend/)
_LOGIN_HTML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend",
    "login.html",
)


def _safe_next(next_url: str) -> str:
    """Return next_url if it's a safe relative path, otherwise '/'."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/api/auth/status")
def auth_status():
    """Returns whether authentication is enabled. Always public."""
    return {"enabled": is_auth_enabled()}


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page():
    """Serve the login page (always accessible)."""
    with open(_LOGIN_HTML_PATH, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@router.post("/auth/login", include_in_schema=False)
def login(
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
):
    """Process login form submission."""
    if check_credentials(username, password):
        token = create_session_token(username)
        dest = _safe_next(next)
        response = RedirectResponse(url=dest, status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response
    # Bad credentials — back to login with error flag
    safe_next = _safe_next(next)
    return RedirectResponse(url=f"/login?error=1&next={safe_next}", status_code=303)


@router.get("/auth/logout", include_in_schema=False)
def logout():
    """Clear the session cookie and redirect to the login page."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response
