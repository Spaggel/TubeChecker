"""
In-memory MeTube reachability state and check logic.

State is updated by the scheduler every 60 s and read by the
/api/health/metube endpoint.
"""

import logging
import threading

import httpx

logger = logging.getLogger(__name__)

# ── In-memory state ───────────────────────────────────────────
_lock = threading.Lock()
_state: dict = {
    "ok": None,          # None = never checked | True = up | False = down
    "checked_at": None,  # ISO-8601 UTC string, or None
}


def get_status() -> dict:
    """Return a copy of the current health state."""
    with _lock:
        return dict(_state)


# ── Check logic ───────────────────────────────────────────────

def _is_reachable(url: str) -> bool:
    """Send a HEAD request to *url*; return True if the server responds."""
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            r = client.head(url)
            return r.status_code < 500
    except Exception as exc:
        logger.debug("MeTube HEAD check failed: %s", exc)
        return False


def run_health_check(metube_url: str) -> None:
    """Check MeTube reachability and persist result to in-memory state."""
    from datetime import datetime

    ok = _is_reachable(metube_url)
    # Use a naive UTC string (no '+00:00' suffix) so the frontend's _toUTC
    # helper — which appends 'Z' when no timezone marker is present — parses
    # it correctly, consistent with all other backend timestamps.
    checked_at = datetime.utcnow().isoformat()

    with _lock:
        _state["ok"] = ok
        _state["checked_at"] = checked_at

    logger.debug("MeTube health: %s", "up" if ok else "down")
