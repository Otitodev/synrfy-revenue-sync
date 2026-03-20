from datetime import date as DateType, datetime
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


class SyncRecordOut(BaseModel):
    id: int
    booking_reference: str
    slot_date: DateType
    product_id: int
    status: str
    amount_cents: int
    currency: str
    mews_bill_id: Optional[str] = None
    mews_charge_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
