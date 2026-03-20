"""
MEWS Connector API client.

All requests are HTTP POST with a JSON body that includes authentication tokens.
Rate limit: 200 requests per 30 seconds. 429 responses are retried with
exponential backoff + jitter (up to _MAX_RETRIES attempts).

Charge posting uses POST /api/connector/v1/orders/add with GrossValue
(pricing.included from VenueSuite) + TaxCodes for the property's tax environment.
The bill lookup/create step ensures the charge lands on the correct open bill.
"""

import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.settings import get_settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5


@dataclass
class MewsReservation:
    id: str
    number: str
    account_id: str  # customer AccountId from the reservation


class MewsClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.mews_base_url.rstrip("/")
        self._auth = {
            "ClientToken": settings.mews_client_token,
            "AccessToken": settings.mews_access_token,
            "Client": settings.mews_client_name,
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def find_reservation(self, booking_reference: str) -> MewsReservation:
        """
        Look up a MEWS reservation by its confirmation number (= VenueSuite
        booking reference). Raises ReservationNotFoundError if not found.
        """
        # Try by Numbers (MEWS internal number) first, then by ChannelNumber
        # (external booking reference stored when creating the reservation via API).
        for filter_key in ("Numbers", "ChannelNumbers"):
            payload = {
                **self._auth,
                filter_key: [booking_reference],
                "Limitation": {"Count": 1},
            }
            data = self._post(
                "/api/connector/v1/reservations/getAll/2023-06-06", payload
            )
            reservations = data.get("Reservations", [])
            if reservations:
                break

        if not reservations:
            raise ReservationNotFoundError(
                f"No MEWS reservation found for booking reference '{booking_reference}'"
            )
        r = reservations[0]
        return MewsReservation(
            id=r["Id"],
            number=r.get("Number", booking_reference),
            account_id=r["AccountId"],
        )

    def get_or_create_bill(self, account_id: str) -> str:
        """
        Return the ID of an open bill for the customer account, creating one if
        none exists. account_id is the reservation's AccountId (customer/company).
        """
        bill_id = self._find_open_bill(account_id)
        if bill_id:
            logger.debug("Found existing bill %s for account %s", bill_id, account_id)
            return bill_id

        logger.info("No open bill found for account %s — creating one", account_id)
        return self._create_bill(account_id)

    def post_charge(
        self,
        account_id: str,
        reservation_id: str,
        bill_id: str,
        service_id: str,
        gross_amount: float,
        currency: str,
        notes: str,
        accounting_category_id: Optional[str] = None,
        tax_codes: Optional[list[str]] = None,
    ) -> str:
        """
        Post a revenue charge to MEWS via orders/add. Returns the ChargeId.

        gross_amount must be the tax-inclusive amount (pricing.included / 100).
        tax_codes should match the property's tax environment (e.g. ["NL-S"] for
        Netherlands 21% BTW). MEWS uses GrossValue + TaxCodes to calculate the
        tax breakdown in a gross pricing environment.
        """
        item: dict[str, Any] = {
            "Name": notes,
            "UnitCount": 1,
            "UnitAmount": {
                "Currency": currency,
                "GrossValue": round(gross_amount, 2),
                "TaxCodes": tax_codes or [],
            },
        }
        if accounting_category_id:
            item["AccountingCategoryId"] = accounting_category_id

        payload: dict[str, Any] = {
            **self._auth,
            "ServiceId": service_id,
            "AccountId": account_id,
            "LinkedReservationId": reservation_id,
            "BillId": bill_id,
            "Items": [item],
        }

        data = self._post("/api/connector/v1/orders/add", payload)
        charge_id = data.get("ChargeId") or data.get("OrderId")
        if not charge_id:
            raise MewsApiError(f"orders/add returned no ChargeId: {data}")
        return charge_id

    # ── Private helpers ────────────────────────────────────────────────────────

    def _find_open_bill(self, account_id: str) -> Optional[str]:
        # bills/getAll requires a customer/date filter — CustomerIds is correct here.
        payload = {
            **self._auth,
            "CustomerIds": [account_id],
            "States": ["Open"],
            "Limitation": {"Count": 500},
        }
        data = self._post("/api/connector/v1/bills/getAll", payload)
        bills = [b for b in data.get("Bills", []) if b.get("State") == "Open"]
        if bills:
            return bills[0]["Id"]
        return None

    def _create_bill(self, account_id: str) -> str:
        payload = {
            **self._auth,
            "Bills": [
                {
                    "AccountId": account_id,
                    "AccountType": "Customer",
                    "Name": None,
                    "Notes": None,
                }
            ],
        }
        data = self._post("/api/connector/v1/bills/create", payload)
        bills = data.get("Bills", [])
        if not bills:
            raise MewsApiError("bills/create returned no Bill objects")
        return bills[0]["Id"]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        HTTP POST with exponential backoff on 429. Raises MewsApiError on
        non-retryable errors, RateLimitError after exhausting retries.
        """
        url = f"{self._base_url}{path}"

        for attempt in range(_MAX_RETRIES):
            try:
                response = httpx.post(url, json=payload, timeout=30.0)
            except httpx.TimeoutException as exc:
                raise MewsApiError(f"MEWS request timed out for {path}: {exc}") from exc

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                wait = 2 ** attempt + random.uniform(0, 1)
                logger.warning(
                    "MEWS rate limited (429) on %s — retry %d/%d in %.1fs",
                    path,
                    attempt + 1,
                    _MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                continue

            raise MewsApiError(
                f"MEWS {path} returned {response.status_code}: {response.text}"
            )

        raise RateLimitError(
            f"MEWS rate limit exceeded after {_MAX_RETRIES} retries on {path}"
        )


class MewsApiError(Exception):
    pass


class ReservationNotFoundError(MewsApiError):
    pass


class RateLimitError(MewsApiError):
    pass
