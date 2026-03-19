import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

import feedparser
import httpx
from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger(__name__)

YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")


def resolve_channel_input(raw: str) -> Optional[str]:
    """
    Accept any of these formats and return the canonical UC... channel ID:
      - UC...          direct channel ID
      - @handle        YouTube handle
      - https://www.youtube.com/@handle
      - https://www.youtube.com/channel/UC...
      - https://www.youtube.com/c/name  (legacy custom URL)
      - https://www.youtube.com/user/name  (legacy user URL)

    Returns None if the channel cannot be resolved.
    """
    raw = raw.strip().rstrip("/")

    # Already a bare channel ID
    if _CHANNEL_ID_RE.fullmatch(raw):
        return raw

    # Channel ID embedded in a URL: /channel/UCxxx
    m = re.search(r"youtube\.com/channel/(UC[A-Za-z0-9_-]{22})", raw)
    if m:
        return m.group(1)

    # Decide which page to fetch
    if re.match(r"https?://", raw):
        page_url = raw                        # already a full URL
    elif raw.startswith("@"):
        page_url = f"https://www.youtube.com/{raw}"
    else:
        page_url = f"https://www.youtube.com/@{raw}"  # bare handle without @

    return _scrape_channel_id(page_url)


def _scrape_channel_id(page_url: str) -> Optional[str]:
    """Fetch a YouTube page and extract the channel ID from the embedded JSON."""
    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            # Bypass YouTube's GDPR consent gate
            cookies={"SOCS": "CAI", "CONSENT": "YES+1"},
        ) as client:
            resp = client.get(page_url)
            if resp.status_code != 200:
                logger.warning("Could not fetch %s (HTTP %s)", page_url, resp.status_code)
                return None

        html = resp.text

        # YouTube embeds the channel's own ID in several reliable locations.
        # browseId / externalId appear in the ytInitialData JSON blob;
        # og:url / canonical are in the <head> meta tags.
        for pattern in (
            r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
            r'"browseId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"',
            r'<meta[^>]+property="og:url"[^>]+content="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"',
            r'<link[^>]+rel="canonical"[^>]+href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"',
        ):
            m = re.search(pattern, html)
            if m:
                return m.group(1)

        logger.warning("No channel ID found on page %s", page_url)
        return None
    except Exception as exc:
        logger.error("Error scraping %s: %s", page_url, exc)
        return None


def fetch_channel_info(channel_id: str) -> Optional[dict]:
    """Fetch channel name and verify the channel exists via its RSS feed."""
    url = YOUTUBE_FEED_URL.format(channel_id=channel_id)
    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        return None

    title = feed.feed.get("title", channel_id)
    # Strip " - YouTube" suffix added by YouTube
    if title.endswith(" - YouTube"):
        title = title[:-10].strip()

    return {"name": title, "feed": feed}


def check_channel(db: Session, channel: models.Channel, metube_url: str) -> int:
    """
    Fetch the RSS feed for a channel, find new videos, and send them to MeTube.
    Returns the number of new videos dispatched.
    """
    logger.info("Checking channel: %s (%s)", channel.name, channel.channel_id)

    url = YOUTUBE_FEED_URL.format(channel_id=channel.channel_id)
    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        logger.warning("Failed to fetch RSS for channel %s", channel.channel_id)
        channel.last_checked = datetime.utcnow()
        db.commit()
        return 0

    new_count = 0

    for entry in feed.entries:
        video_id = getattr(entry, "yt_videoid", None)
        if not video_id:
            continue

        # Parse the published timestamp (naive UTC)
        if entry.get("published_parsed"):
            published_at = datetime(*entry.published_parsed[:6])
        else:
            published_at = datetime.utcnow()

        # Respect per-channel start date filter
        if channel.start_date and published_at < channel.start_date:
            continue

        # Skip videos already tracked
        if db.query(models.Video).filter(models.Video.video_id == video_id).first():
            continue

        # Send to MeTube
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        folder = channel.download_dir or channel.name
        success, error_msg = send_to_metube(metube_url, video_url, folder)
        status = "sent" if success else "failed"

        db.add(
            models.Video(
                channel_id=channel.id,
                video_id=video_id,
                title=entry.get("title", video_id),
                published_at=published_at,
                status=status,
                error=error_msg,
            )
        )
        new_count += 1
        logger.info("[%s] %s — %s", status.upper(), channel.name, entry.get("title", video_id))

    channel.last_checked = datetime.utcnow()
    db.commit()

    if new_count:
        logger.info("Channel %s: dispatched %d new video(s)", channel.name, new_count)

    return new_count


def refresh_jellyfin(jellyfin_url: str, api_key: str) -> Tuple[bool, Optional[str]]:
    """POST a library refresh request to Jellyfin.

    Returns ``(True, None)`` on success or ``(False, error_message)`` on failure.
    """
    try:
        url = f"{jellyfin_url.rstrip('/')}/library/refresh"
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, params={"api_key": api_key})
            if resp.status_code in (200, 204):
                return True, None
            body = resp.text[:300].strip() or "(empty response)"
            return False, f"HTTP {resp.status_code}: {body}"
    except Exception as exc:
        logger.error("Jellyfin refresh failed: %s", exc)
        return False, str(exc)


def send_to_metube(metube_url: str, video_url: str, folder: str) -> Tuple[bool, Optional[str]]:
    """POST a download request to the MeTube /add endpoint.

    Returns ``(True, None)`` on success or ``(False, error_message)`` on failure.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{metube_url.rstrip('/')}/add",
                json={
                    "url": video_url,
                    "download_type": "video",
                    "quality": "best",
                    "format": "any",
                    "folder": folder,
                },
            )
            if resp.status_code in (200, 201, 204):
                return True, None
            # Non-2xx — capture status and body for diagnostics
            body = resp.text[:300].strip() or "(empty response)"
            return False, f"HTTP {resp.status_code}: {body}"
    except Exception as exc:
        logger.error("MeTube request failed: %s", exc)
        return False, str(exc)
