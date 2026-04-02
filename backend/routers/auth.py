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

# ── Login page HTML (served from here so it's always reachable) ──────────────

_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en" data-bs-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TubeChecker \u2014 Sign in</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" />
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet" />
  <style>
    body {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
  </style>
</head>
<body>
  <div style="width:100%;max-width:400px;padding:1rem">
    <div class="text-center mb-4">
      <span class="fs-4 fw-semibold">
        <i class="bi bi-rss-fill text-danger me-2"></i>TubeChecker
      </span>
    </div>
    <div class="card border-0 shadow-sm">
      <div class="card-body p-4">
        <h5 class="card-title fw-semibold mb-3">Sign in</h5>
        <div id="err" class="alert alert-danger small py-2 d-none" role="alert">
          <i class="bi bi-exclamation-triangle-fill me-1"></i>Invalid username or password.
        </div>
        <form method="POST" action="/auth/login">
          <input type="hidden" name="next" id="nextField" value="/" />
          <div class="mb-3">
            <label class="form-label fw-medium" for="u">Username</label>
            <input class="form-control" id="u" name="username" type="text"
                   required autofocus autocomplete="username" />
          </div>
          <div class="mb-4">
            <label class="form-label fw-medium" for="p">Password</label>
            <input class="form-control" id="p" name="password" type="password"
                   required autocomplete="current-password" />
          </div>
          <button class="btn btn-danger w-100" type="submit">
            <i class="bi bi-box-arrow-in-right me-1"></i>Sign in
          </button>
        </form>
      </div>
    </div>
  </div>
  <script>
    const q = new URLSearchParams(location.search);
    if (q.get('error')) document.getElementById('err').classList.remove('d-none');
    const n = q.get('next');
    if (n) document.getElementById('nextField').value = n;
  </script>
</body>
</html>
"""


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
    return HTMLResponse(_LOGIN_HTML)


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
