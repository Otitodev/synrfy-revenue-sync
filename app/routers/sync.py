import time
from datetime import date as date_type
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.sync import SyncRequest, SyncResponse
from app.services.sync_engine import run_sync

router = APIRouter()


@router.post("/run", response_model=SyncResponse)
def trigger_sync(request: SyncRequest, db: Session = Depends(get_db)) -> SyncResponse:
    """
    Manually trigger a revenue sync for a given date.
    Omit the date field to sync today's transactions.
    """
    target_date = request.date or date_type.today()
    start = time.monotonic()
    result = run_sync(target_date, db)
    result.duration_seconds = round(time.monotonic() - start, 2)
    return result
