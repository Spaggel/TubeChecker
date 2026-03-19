from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, HTTPException
from sqlalchemy.orm import Session
import os

from .. import models, schemas
from ..database import get_db
from .. import scheduler as sched_module

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    "metube_url":       os.getenv("METUBE_URL",       "http://localhost:8081"),
    "check_interval":   os.getenv("CHECK_INTERVAL",   "60"),
    "jellyfin_url":     os.getenv("JELLYFIN_URL",     ""),
    "jellyfin_api_key": os.getenv("JELLYFIN_API_KEY", ""),
}


def _get(db: Session, key: str) -> str:
    row = db.query(models.Setting).filter(models.Setting.key == key).first()
    return row.value if row else DEFAULT_SETTINGS.get(key, "")


def _set(db: Session, key: str, value: str) -> None:
    row = db.query(models.Setting).filter(models.Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.Setting(key=key, value=value))
    db.commit()


@router.get("", response_model=schemas.SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return schemas.SettingsOut(
        metube_url=_get(db, "metube_url"),
        check_interval=int(_get(db, "check_interval")),
        jellyfin_url=_get(db, "jellyfin_url"),
        jellyfin_api_key=_get(db, "jellyfin_api_key"),
    )


@router.put("", response_model=schemas.SettingsOut)
def update_settings(payload: schemas.SettingsUpdate, db: Session = Depends(get_db)):
    if payload.metube_url is not None:
        _set(db, "metube_url", payload.metube_url)
    if payload.check_interval is not None:
        _set(db, "check_interval", str(payload.check_interval))
        sched_module.update_interval(payload.check_interval)
    if payload.jellyfin_url is not None:
        _set(db, "jellyfin_url", payload.jellyfin_url)
    if payload.jellyfin_api_key is not None:
        _set(db, "jellyfin_api_key", payload.jellyfin_api_key)

    return schemas.SettingsOut(
        metube_url=_get(db, "metube_url"),
        check_interval=int(_get(db, "check_interval")),
        jellyfin_url=_get(db, "jellyfin_url"),
        jellyfin_api_key=_get(db, "jellyfin_api_key"),
    )


@router.post("/check-all", status_code=202)
def trigger_check_all(background_tasks: BackgroundTasks):
    background_tasks.add_task(sched_module.trigger_now)
    return {"message": "Full check triggered"}


@router.post("/jellyfin-refresh")
def trigger_jellyfin_refresh(db: Session = Depends(get_db)):
    """Send a library refresh request to the configured Jellyfin instance."""
    from ..feed_checker import refresh_jellyfin

    jellyfin_url = _get(db, "jellyfin_url")
    if not jellyfin_url:
        raise HTTPException(status_code=400, detail="Jellyfin URL is not configured")

    api_key = _get(db, "jellyfin_api_key")
    success, error = refresh_jellyfin(jellyfin_url, api_key)
    if not success:
        raise HTTPException(status_code=502, detail=error or "Jellyfin refresh failed")
    return {"message": "Jellyfin library refresh triggered"}
