from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..feed_checker import send_to_metube
from ..routers.settings import DEFAULT_SETTINGS

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _get_metube_url(db: Session) -> str:
    row = db.query(models.Setting).filter(models.Setting.key == "metube_url").first()
    return row.value if row else DEFAULT_SETTINGS["metube_url"]


@router.get("", response_model=List[schemas.VideoOut])
def get_recent_videos(limit: int = 200, db: Session = Depends(get_db)):
    videos = (
        db.query(models.Video)
        .order_by(models.Video.sent_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for v in videos:
        out = schemas.VideoOut.model_validate(v)
        out.channel_name = v.channel.name if v.channel else None
        result.append(out)
    return result


@router.post("/retry-failed", response_model=List[schemas.VideoOut])
def retry_all_failed(db: Session = Depends(get_db)):
    """Re-send every video currently marked as failed to MeTube."""
    failed = db.query(models.Video).filter(models.Video.status == "failed").all()
    if not failed:
        return []

    metube_url = _get_metube_url(db)
    results = []

    for video in failed:
        channel = video.channel
        if not channel:
            continue

        video_url = f"https://www.youtube.com/watch?v={video.video_id}"
        folder = channel.download_dir or channel.name
        success, error_msg = send_to_metube(metube_url, video_url, folder)

        video.status = "sent" if success else "failed"
        video.error = error_msg
        video.sent_at = datetime.utcnow()

        out = schemas.VideoOut.model_validate(video)
        out.channel_name = channel.name
        results.append(out)

    db.commit()
    return results


@router.post("/{video_id}/retry", response_model=schemas.VideoOut)
def retry_video(video_id: int, db: Session = Depends(get_db)):
    """Re-send a video to MeTube regardless of its current status."""
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    channel = video.channel
    if not channel:
        raise HTTPException(status_code=404, detail="Parent channel not found")

    metube_url = _get_metube_url(db)

    video_url = f"https://www.youtube.com/watch?v={video.video_id}"
    folder = channel.download_dir or channel.name
    success, error_msg = send_to_metube(metube_url, video_url, folder)

    video.status = "sent" if success else "failed"
    video.error = error_msg
    video.sent_at = datetime.utcnow()
    db.commit()
    db.refresh(video)

    out = schemas.VideoOut.model_validate(video)
    out.channel_name = channel.name
    return out
