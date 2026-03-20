from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import SessionLocal, get_db
from datetime import datetime, timedelta

from ..feed_checker import check_channel, fetch_channel_info, resolve_channel_input, send_to_metube, RETRY_DELAYS_MINUTES

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _enrich(out: schemas.ChannelOut, db: Session) -> schemas.ChannelOut:
    """Populate computed fields that are not stored on the model."""
    out.video_count = (
        db.query(models.Video).filter(models.Video.channel_id == out.id).count()
    )
    out.latest_video_date = db.query(func.max(models.Video.published_at)).filter(
        models.Video.channel_id == out.id
    ).scalar()
    return out


@router.get("", response_model=List[schemas.ChannelOut])
def list_channels(db: Session = Depends(get_db)):
    channels = db.query(models.Channel).order_by(models.Channel.name).all()
    return [_enrich(schemas.ChannelOut.model_validate(ch), db) for ch in channels]


@router.post("", response_model=schemas.ChannelOut, status_code=201)
def create_channel(payload: schemas.ChannelCreate, db: Session = Depends(get_db)):
    # Resolve handle / URL / bare ID → canonical UC... channel ID
    resolved_id = resolve_channel_input(payload.channel_id)
    if not resolved_id:
        raise HTTPException(
            status_code=400,
            detail="Could not resolve a YouTube channel ID from the input. "
                   "Try pasting the full channel URL or a @handle.",
        )

    # Deduplicate
    if db.query(models.Channel).filter(models.Channel.channel_id == resolved_id).first():
        raise HTTPException(status_code=409, detail="Channel already exists")

    name = payload.name
    if not name:
        info = fetch_channel_info(resolved_id)
        if not info:
            raise HTTPException(
                status_code=400,
                detail="Could not fetch channel info. Verify the channel ID is correct.",
            )
        name = info["name"]

    channel = models.Channel(
        channel_id=resolved_id,
        name=name,
        start_date=payload.start_date,
        download_dir=payload.download_dir,
        quality=payload.quality,
        format=payload.format,
        enabled=payload.enabled,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)

    out = schemas.ChannelOut.model_validate(channel)
    out.video_count = 0
    return out


@router.get("/export")
def export_channels(db: Session = Depends(get_db)):
    """Return all channels as a JSON snapshot suitable for backup / migration."""
    channels = db.query(models.Channel).order_by(models.Channel.name).all()
    return {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "channels": [
            schemas.ChannelExport(
                channel_id=ch.channel_id,
                name=ch.name,
                start_date=ch.start_date,
                download_dir=ch.download_dir,
                quality=ch.quality,
                format=ch.format,
                enabled=ch.enabled,
            )
            for ch in channels
        ],
    }


@router.post("/import", response_model=schemas.ChannelImportResult)
def import_channels(payload: schemas.ChannelImportRequest, db: Session = Depends(get_db)):
    """Add channels from a previous export. Channels that already exist are skipped (idempotent)."""
    added = 0
    skipped = 0
    errors: list[str] = []

    for ch_data in payload.channels:
        existing = (
            db.query(models.Channel)
            .filter(models.Channel.channel_id == ch_data.channel_id)
            .first()
        )
        if existing:
            skipped += 1
            continue

        try:
            channel = models.Channel(
                channel_id=ch_data.channel_id,
                name=ch_data.name,
                start_date=ch_data.start_date,
                download_dir=ch_data.download_dir,
                quality=ch_data.quality,
                format=ch_data.format,
                enabled=ch_data.enabled,
            )
            db.add(channel)
            db.commit()
            added += 1
        except Exception as exc:
            db.rollback()
            errors.append(f"{ch_data.channel_id}: {exc}")

    return schemas.ChannelImportResult(added=added, skipped=skipped, errors=errors)


@router.get("/{channel_id}", response_model=schemas.ChannelOut)
def get_channel(channel_id: int, db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _enrich(schemas.ChannelOut.model_validate(channel), db)


@router.put("/{channel_id}", response_model=schemas.ChannelOut)
def update_channel(
    channel_id: int, payload: schemas.ChannelUpdate, db: Session = Depends(get_db)
):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)

    db.commit()
    db.refresh(channel)

    return _enrich(schemas.ChannelOut.model_validate(channel), db)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(channel)
    db.commit()


@router.post("/{channel_id}/check", status_code=202)
def trigger_channel_check(
    channel_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    setting = db.query(models.Setting).filter(models.Setting.key == "metube_url").first()
    metube_url = setting.value if setting else "http://localhost:8081"
    ch_id = channel_id

    def _run():
        new_db = SessionLocal()
        try:
            ch = new_db.query(models.Channel).filter(models.Channel.id == ch_id).first()
            if ch:
                check_channel(new_db, ch, metube_url)
        finally:
            new_db.close()

    background_tasks.add_task(_run)
    return {"message": f"Check triggered for {channel.name}"}


@router.get("/{channel_id}/videos", response_model=List[schemas.VideoOut])
def get_channel_videos(channel_id: int, db: Session = Depends(get_db)):
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    videos = (
        db.query(models.Video)
        .filter(models.Video.channel_id == channel_id)
        .order_by(models.Video.published_at.desc())
        .limit(100)
        .all()
    )

    result = []
    for v in videos:
        out = schemas.VideoOut.model_validate(v)
        out.channel_name = channel.name
        result.append(out)
    return result


@router.post("/{channel_id}/retry-failed", response_model=List[schemas.VideoOut])
def retry_failed_for_channel(channel_id: int, db: Session = Depends(get_db)):
    """Re-send every failed video for a specific channel to MeTube."""
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    setting = db.query(models.Setting).filter(models.Setting.key == "metube_url").first()
    metube_url = setting.value if setting else "http://localhost:8081"

    failed = (
        db.query(models.Video)
        .filter(models.Video.channel_id == channel_id, models.Video.status == "failed")
        .all()
    )

    results = []
    for video in failed:
        video_url = f"https://www.youtube.com/watch?v={video.video_id}"
        folder = channel.download_dir or channel.name
        success, error_msg = send_to_metube(metube_url, video_url, folder, channel.quality or "best", channel.format or "any")

        video.status = "sent" if success else "failed"
        video.error = error_msg
        video.sent_at = datetime.utcnow()
        if success:
            video.retry_count = 0
            video.next_retry_at = None
        else:
            video.retry_count = 0
            video.next_retry_at = datetime.utcnow() + timedelta(minutes=RETRY_DELAYS_MINUTES[0])

        out = schemas.VideoOut.model_validate(video)
        out.channel_name = channel.name
        results.append(out)

    db.commit()
    return results
