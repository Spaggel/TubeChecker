from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import health as health_module
from ..database import get_db
from .. import models

router = APIRouter(prefix="/api/health", tags=["health"])


def _get_metube_url(db: Session) -> str:
    row = db.query(models.Setting).filter(models.Setting.key == "metube_url").first()
    return row.value if row else "http://localhost:8081"


@router.get("/metube")
def metube_health(db: Session = Depends(get_db)):
    """Return the last-known MeTube reachability state."""
    return health_module.get_status()
