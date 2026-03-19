"""
VenueSuite API client.

VenueSuite does not expose a dedicated transactions endpoint — transactions
live as products inside booking slots. This client fetches all bookings for
the property and filters to those whose slots fall on the target date.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class VenueTransaction:
    booking_reference: str
    slot_id: int
    slot_date: date
    product_id: int
    component: str    # "space" | "package" | "extra" | ...
    category: str     # product-level category string from API
    title: str
    amount_cents: int  # ex-VAT (pricing.excluded)
    quantity: int
    currency: str


class VenueSuiteClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.venuesuite_base_url.rstrip("/")
        self._venue_id = settings.venuesuite_venue_id
        self._headers = {
            "X-AUTH-TOKEN": settings.venuesuite_token,
            "Content-Type": "application/json",
        }

    def fetch_bookings_for_date(self, target_date: date) -> list[VenueTransaction]:
        """
        Fetch all bookings from VenueSuite and return product lines whose
        slot start date matches target_date.

        VenueSuite prices are in cents; we use pricing.excluded (ex-VAT)
        to match the MEWS net-amount convention.
        """
        url = f"{self._base_url}/venues/{self._venue_id}/bookings"

        # Pass the target date as filter params if the API supports it.
        # The staging API response will reveal whether these are honoured;
        # if not, all bookings are fetched and filtered locally (see below).
        params = {
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        }

        logger.info("Fetching VenueSuite bookings for %s", target_date)

        try:
            response = httpx.post(
                url,
                headers=self._headers,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise VenueSuiteError(f"VenueSuite request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise VenueSuiteError(
                f"VenueSuite returned {exc.response.status_code}: {exc.response.text}"
            ) from exc

        raw: list[dict[str, Any]] = response.json()
        if not isinstance(raw, list):
            # Some API versions wrap in a key
            raw = raw.get("bookings", raw.get("data", []))

        transactions = _extract_transactions(raw, target_date)
        logger.info(
            "Found %d product lines on %s across %d booking(s)",
            len(transactions),
            target_date,
            len({t.booking_reference for t in transactions}),
        )
        return transactions


def _extract_transactions(
    bookings: list[dict[str, Any]],
    target_date: date,
) -> list[VenueTransaction]:
    """
    Walk bookings → slots → products and return a flat list of
    VenueTransaction for slots whose start date matches target_date.
    """
    transactions: list[VenueTransaction] = []

    for booking in bookings:
        booking_reference = str(booking.get("reference", ""))
        currency = booking.get("currency", "EUR")

        for slot in booking.get("slots", []):
            slot_start_raw = slot.get("start", "")
            try:
                slot_dt = datetime.fromisoformat(slot_start_raw)
                # Normalise to date in UTC
                if slot_dt.tzinfo is not None:
                    slot_dt = slot_dt.astimezone(timezone.utc)
                slot_date = slot_dt.date()
            except (ValueError, TypeError):
                logger.warning(
                    "Could not parse slot start '%s' for booking %s — skipping slot",
                    slot_start_raw,
                    booking_reference,
                )
                continue

            if slot_date != target_date:
                continue

            for product in slot.get("products", []):
                pricing = product.get("pricing", {})
                amount_cents = pricing.get("excluded", 0)  # ex-VAT
                quantity = product.get("quantity", 1)

                transactions.append(
                    VenueTransaction(
                        booking_reference=booking_reference,
                        slot_id=slot["id"],
                        slot_date=slot_date,
                        product_id=product["id"],
                        component=product.get("component", ""),
                        category=product.get("category", ""),
                        title=product.get("title", ""),
                        amount_cents=amount_cents,
                        quantity=quantity,
                        currency=currency,
                    )
                )

    return transactions


class VenueSuiteError(Exception):
    pass
