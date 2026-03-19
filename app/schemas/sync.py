from datetime import date as DateType
from typing import Optional
from pydantic import BaseModel


class SyncRequest(BaseModel):
    date: Optional[DateType] = None


class SyncResponse(BaseModel):
    date: DateType
    posted: int
    skipped: int
    failed: int
    duration_seconds: float
