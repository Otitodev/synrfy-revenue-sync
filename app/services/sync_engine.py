"""
Sync engine: orchestrates the three-step VenueSuite → MEWS revenue sync.

Each transaction is processed independently — a failure on one never aborts
the rest. Idempotency is enforced by checking the sync_records table before
any network call; a transaction with status="posted" is skipped silently.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sync_record import SyncRecord
from app.services.category_mapper import get_category_mapper
from app.services.mews import MewsClient, MewsApiError
from app.services.venuesuite import VenueSuiteClient, VenueTransaction, VenueSuiteError

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    date: date
    posted: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0


def run_sync(target_date: date, db: Session) -> SyncResult:
    """
    Run the full VenueSuite → MEWS sync for target_date.
    Returns a SyncResult summary. Never raises — all errors are caught,
    logged, and reflected in result.failed.
    """
    logger.info("=== Sync started for %s ===", target_date)
    result = SyncResult(date=target_date)

    # ── Step 1: Fetch transactions from VenueSuite ─────────────────────────────
    try:
        vs_client = VenueSuiteClient()
        transactions = vs_client.fetch_bookings_for_date(target_date)
    except VenueSuiteError as exc:
        logger.error("Failed to fetch VenueSuite bookings: %s", exc)
        # Cannot proceed without source data — log and return empty result
        return result

    if not transactions:
        logger.info("No VenueSuite transactions found for %s", target_date)
        return result

    logger.info("%d transaction(s) to process for %s", len(transactions), target_date)

    mews_client = MewsClient()
    mapper = get_category_mapper()

    # Cache reservation + bill lookups within a single sync run to avoid
    # redundant API calls when multiple products share the same booking.
    reservation_cache: dict = {}   # booking_reference → MewsReservation | Exception
    bill_cache: dict = {}          # account_id → bill_id

    # ── Steps 2+3: Per-transaction processing (fully isolated) ─────────────────
    for tx in transactions:

        # Idempotency gate — check before any network call
        existing = (
            db.query(SyncRecord)
            .filter_by(
                booking_reference=tx.booking_reference,
                slot_date=tx.slot_date,
                product_id=tx.product_id,
            )
            .first()
        )
        if existing and existing.status == "posted":
            logger.debug(
                "Skipping already-posted product %d for booking %s on %s",
                tx.product_id,
                tx.booking_reference,
                tx.slot_date,
            )
            result.skipped += 1
            continue

        try:
            bill_id, charge_id = _process_transaction(
                tx, mews_client, mapper, reservation_cache, bill_cache
            )
            _upsert_record(
                db, tx,
                status="posted",
                mews_bill_id=bill_id,
                mews_charge_id=charge_id,
            )
            result.posted += 1
            logger.info(
                "Posted: booking=%s product=%d -> bill=%s charge=%s",
                tx.booking_reference,
                tx.product_id,
                bill_id,
                charge_id,
            )

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            logger.error(
                "Failed: booking=%s product=%d — %s",
                tx.booking_reference,
                tx.product_id,
                error_msg,
                exc_info=True,
            )
            _upsert_record(db, tx, status="failed", error_message=error_msg)
            result.failed += 1
            # Never abort — continue with remaining transactions

    logger.info(
        "=== Sync complete for %s: posted=%d skipped=%d failed=%d ===",
        target_date,
        result.posted,
        result.skipped,
        result.failed,
    )
    return result


def _process_transaction(
    tx: VenueTransaction,
    mews_client,
    mapper,
    reservation_cache: dict,
    bill_cache: dict,
) -> tuple[str, str]:
    """
    Steps 2a, 2b, 3a, 3b for a single transaction.
    Returns (bill_id, charge_id) on success. Raises on any error.
    Uses reservation_cache and bill_cache to avoid repeat API calls within a run.
    """
    # 2a: Find the MEWS reservation (cached per booking_reference).
    # Failures are also cached so subsequent products for the same booking
    # don't generate redundant API calls.
    if tx.booking_reference not in reservation_cache:
        try:
            reservation_cache[tx.booking_reference] = mews_client.find_reservation(
                tx.booking_reference
            )
        except Exception as exc:
            reservation_cache[tx.booking_reference] = exc

    cached = reservation_cache[tx.booking_reference]
    if isinstance(cached, Exception):
        raise cached
    reservation = cached

    # 2b: Get or create a bill (cached per account_id)
    if reservation.account_id not in bill_cache:
        bill_cache[reservation.account_id] = mews_client.get_or_create_bill(
            reservation.account_id
        )
    bill_id = bill_cache[reservation.account_id]

    # 3a: Map VenueSuite category to MEWS service
    mapping = mapper.resolve(tx.component, tx.category)

    # 3b: Post the charge (convert cents → decimal, apply quantity)
    net_amount = (tx.amount_cents * tx.quantity) / 100.0
    notes = (
        f"{tx.title} | VenueSuite booking {tx.booking_reference} "
        f"| slot {tx.slot_date} | product {tx.product_id}"
    )
    charge_id = mews_client.post_charge(
        account_id=reservation.account_id,
        reservation_id=reservation.id,
        bill_id=bill_id,
        service_id=mapping.mews_service_id,
        net_amount=net_amount,
        currency=tx.currency,
        notes=notes,
        accounting_category_id=mapping.mews_accounting_category_id,
    )

    return bill_id, charge_id


def _upsert_record(
    db: Session,
    tx: VenueTransaction,
    status: str,
    mews_bill_id: str = None,
    mews_charge_id: str = None,
    error_message: str = None,
) -> None:
    """
    Insert or update the sync record. Uses a try/except on IntegrityError
    to handle the rare race condition where two concurrent runs attempt to
    insert the same idempotency key simultaneously.
    """
    existing = (
        db.query(SyncRecord)
        .filter_by(
            booking_reference=tx.booking_reference,
            slot_date=tx.slot_date,
            product_id=tx.product_id,
        )
        .first()
    )

    if existing:
        existing.status = status
        existing.mews_bill_id = mews_bill_id
        existing.mews_charge_id = mews_charge_id
        existing.error_message = error_message
        db.commit()
        return

    record = SyncRecord(
        booking_reference=tx.booking_reference,
        slot_date=tx.slot_date,
        product_id=tx.product_id,
        venuesuite_slot_id=tx.slot_id,
        status=status,
        mews_bill_id=mews_bill_id,
        mews_charge_id=mews_charge_id,
        amount_cents=tx.amount_cents,
        currency=tx.currency,
        error_message=error_message,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning(
            "Race condition: sync record for product %d already exists — skipping insert",
            tx.product_id,
        )
