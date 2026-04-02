"""
Simple session-based authentication.

Enable by setting both AUTH_USERNAME and AUTH_PASSWORD environment variables.
If neither is set the middleware is a no-op and the app is fully open (default).

AUTH_SECRET   – HMAC signing key.  Auto-generated per-process if omitted
                (sessions are lost on restart when not set).
AUTH_SESSION_MAX_AGE – Session lifetime in seconds. Default: 7 days.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

SESSION_COOKIE = "tc_session"
SESSION_MAX_AGE = int(os.getenv("AUTH_SESSION_MAX_AGE", str(7 * 24 * 3600)))

AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD: str = os.getenv("AUTH_PASSWORD", "")
_AUTH_SECRET: str = os.getenv("AUTH_SECRET", "")

if not _AUTH_SECRET:
    _AUTH_SECRET = secrets.token_hex(32)
    if AUTH_USERNAME and AUTH_PASSWORD:
        logger.warning(
            "AUTH_SECRET is not set — generated a random signing secret. "
            "Sessions will be invalidated on restart. "
            "Set AUTH_SECRET in your environment for persistent sessions."
        )


def is_auth_enabled() -> bool:
    """Return True only when both username and password are configured."""
    return bool(AUTH_USERNAME and AUTH_PASSWORD)


def _sign(payload: str) -> str:
    return hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_token(username: str) -> str:
    """Return a signed session token: ``<username>:<expires_ts>:<hmac>``."""
    expires = int(time.time()) + SESSION_MAX_AGE
    payload = f"{username}:{expires}"
    return f"{payload}:{_sign(payload)}"


def verify_session_token(token: str) -> str | None:
    """Return the username if the token is valid and not expired, else None."""
    try:
        # Split into at most 3 parts so a colon in the username still works.
        parts = token.split(":", 2)
        if len(parts) != 3:
            return None
        username, expires_str, sig = parts
        payload = f"{username}:{expires_str}"
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if int(expires_str) < int(time.time()):
            return None
        return username
    except Exception:
        return None


def check_credentials(username: str, password: str) -> bool:
    """Constant-time credential comparison to resist timing attacks."""
    if not is_auth_enabled():
        return False
    ok_user = hmac.compare_digest(username, AUTH_USERNAME)
    ok_pass = hmac.compare_digest(password, AUTH_PASSWORD)
    return ok_user and ok_pass
