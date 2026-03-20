# Agent Guidelines

This file tells AI coding assistants how to work in this repository.

## Project Overview

Synrfy Revenue Sync is a Python microservice that posts daily VenueSuite event transactions into MEWS before the night audit. The core flow:

```
VenueSuite bookings API
  → filter slots by target date
  → look up MEWS reservation by booking reference
  → get or create open bill on customer account
  → post each product line as a charge via orders/add
```

## Key Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, lifespan hook, router wiring, `/ui` redirect |
| `app/services/sync_engine.py` | Core orchestration — the only place business logic lives |
| `app/services/mews.py` | MEWS Connector API client (all POST, exponential backoff on 429) |
| `app/services/venuesuite.py` | VenueSuite API client (GET, `X-AUTH-TOKEN` header) |
| `app/services/category_mapper.py` | YAML loader + compound-key resolver |
| `app/models/sync_record.py` | Idempotency table — the unique constraint is the entire guard |
| `config/category_mapping.yaml` | VenueSuite component → MEWS service UUID mapping |
| `demo_test.py` | Standalone 6-step demo script (no server needed) |

## Rules for AI Agents

### Never touch
- The unique constraint on `sync_records (booking_reference, slot_date, product_id)` — this is the idempotency guarantee. Do not add, remove, or alter it.
- `.env` — credentials are not committed. Never write secrets to any tracked file.
- `config/category_mapping.yaml` comments — GitGuardian scans this file. Do not add token values or credentials to comments.

### Always preserve
- **Per-transaction error isolation** — the `for tx in transactions` loop in `sync_engine.py` must never raise. Failures are caught, logged, and recorded as `status="failed"` so the run continues.
- **Reservation + bill caching** — within a single sync run, `reservation_cache` and `bill_cache` avoid redundant MEWS API calls. Cache both successes and failures (store the exception object itself so it can be re-raised cheaply).
- **`run_sync()` never raises** — callers (the router, the scheduler, `demo_test.py`) all expect a `SyncResult` back, not an exception.

### MEWS API specifics
- All MEWS requests are `POST` with auth in the JSON body (`ClientToken`, `AccessToken`, `Client`).
- Charge posting uses `POST /api/connector/v1/orders/add` with `GrossValue` (gross pricing environment).
- Bill lookup uses `bills/getAll` with `CustomerIds` filter — `ReservationIds` is not a valid filter and returns 400. Filter open bills client-side (`State == "Open"`).
- Reservation lookup tries `Numbers` first, then `ChannelNumbers` — VenueSuite booking refs may be stored as either.
- Rate limit is 200 requests per 30 seconds. Backoff: 5 retries, waits of 1 / 2 / 4 / 8 / 16s + jitter.

### VenueSuite API specifics
- All requests are `GET` with `X-AUTH-TOKEN` header.
- `start` / `end` params filter by **booking period**, not slot date. Always filter locally by `slot.start` date after fetching.
- Response is wrapped: `{"data": [...], "meta": {...}}` — always read from `body.get("data", body)`.

### Testing
- Run `python demo_test.py` to verify end-to-end connectivity and idempotency without starting the server.
- Pass a date argument to test a specific date: `python demo_test.py 2026-04-02`
- The idempotency check expects `posted=0` on the second run. Failed transactions (no matching MEWS reservation) will re-attempt — this is correct behaviour, not a bug.

### Adding new VenueSuite components
1. Add the component key to `config/category_mapping.yaml` with a valid MEWS service UUID.
2. No code changes needed — `category_mapper.py` reads the YAML at startup.
3. If no mapping exists, the fallback entry is used and a `WARNING` is logged. The sync does not fail.

### Changing the charge payload
- Amount source: `pricing.excluded * quantity / 100` (VenueSuite sends cents, MEWS expects decimal).
- Use `GrossValue` (not `NetValue`) — the MEWS demo is configured as a gross pricing environment.
- `TaxCodes` should reflect the property's tax jurisdiction (e.g. `UK-S` for UK standard 20% VAT). Currently empty — confirm with the property before populating.

### Schema changes
- Any new API response field should be added to `app/schemas/sync.py`.
- Use `from_attributes = True` (Pydantic v2) on models that wrap SQLAlchemy ORM objects.
- Do not name Pydantic fields the same as their type annotation (e.g. field named `date` with type `date` causes a `PydanticSchemaGenerationError` — use `from datetime import date as DateType`).

## Running Locally

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your VenueSuite token

# Demo (no server)
python demo_test.py

# Server
uvicorn main:app --reload
# UI: http://localhost:8000/ui
# API docs: http://localhost:8000/docs
```
