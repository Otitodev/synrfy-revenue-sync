from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Text,
    UniqueConstraint, func,
)
from app.database import Base


class SyncRecord(Base):
    """
    Tracks every VenueSuite product line that has been (or attempted to be)
    posted to MEWS. The unique constraint on (booking_reference, slot_date,
    product_id) is the sole guard against double-posting — if a record with
    status="posted" already exists, the sync engine skips the transaction.
    """

    __tablename__ = "sync_records"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # VenueSuite identifiers
    booking_reference = Column(String, nullable=False, index=True)
    slot_date = Column(Date, nullable=False, index=True)
    product_id = Column(Integer, nullable=False)
    venuesuite_slot_id = Column(Integer, nullable=False)

    # Outcome
    status = Column(String, nullable=False)          # "posted" | "failed"
    mews_bill_id = Column(String, nullable=True)
    mews_charge_id = Column(String, nullable=True)

    # Financial snapshot (for audit trail)
    amount_cents = Column(Integer, nullable=False)   # ex-VAT, pricing.excluded
    currency = Column(String(8), nullable=False)

    # Error context (populated on failure)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "booking_reference", "slot_date", "product_id",
            name="uq_sync_record_idempotency",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SyncRecord booking={self.booking_reference} "
            f"date={self.slot_date} product={self.product_id} "
            f"status={self.status}>"
        )
