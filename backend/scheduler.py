import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .database import SessionLocal
from . import models
from .feed_checker import auto_retry_failed, check_channel
from . import health as health_module

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC")


def _run_health_check() -> None:
    """Check MeTube reachability, update in-memory state, then auto-retry failed videos."""
    db = SessionLocal()
    try:
        setting = db.query(models.Setting).filter(models.Setting.key == "metube_url").first()
        metube_url = setting.value if setting else "http://localhost:8081"
        # Run the live health check first so the state is fresh when auto_retry_failed reads it
        health_module.run_health_check(metube_url)
        count = auto_retry_failed(db, metube_url)
        if count:
            logger.info("Auto-retry: processed %d video(s)", count)
    finally:
        db.close()


def _run_all_checks() -> None:
    """Check every enabled channel and dispatch new videos to MeTube."""
    db = SessionLocal()
    try:
        setting = db.query(models.Setting).filter(models.Setting.key == "metube_url").first()
        metube_url = setting.value if setting else "http://localhost:8081"

        channels = db.query(models.Channel).filter(models.Channel.enabled.is_(True)).all()
        total = 0
        for channel in channels:
            try:
                total += check_channel(db, channel, metube_url)
            except Exception as exc:
                logger.error("Error checking channel %s: %s", channel.name, exc)

        logger.info("Scheduled check complete — %d new video(s) dispatched", total)
    finally:
        db.close()


def start_scheduler(interval_minutes: int = 60) -> None:
    _scheduler.add_job(
        _run_all_checks,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="check_channels",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_health_check,
        trigger=IntervalTrigger(seconds=60),
        id="health_check",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
    )
    if not _scheduler.running:
        _scheduler.start()
    logger.info("Scheduler started (interval: %d min)", interval_minutes)


def update_interval(interval_minutes: int) -> None:
    _scheduler.reschedule_job(
        "check_channels",
        trigger=IntervalTrigger(minutes=interval_minutes),
    )
    logger.info("Scheduler interval updated to %d min", interval_minutes)


def trigger_now() -> None:
    """Immediately run a full check outside the normal schedule."""
    _run_all_checks()


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
