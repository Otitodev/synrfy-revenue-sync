# Synrfy Revenue Sync

Syncs daily VenueSuite event transactions into MEWS before the night audit.

**Data flow:** VenueSuite bookings → filter by slot date → resolve MEWS reservation → get/create bill → post charges per product line.

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env — add VenueSuite token; MEWS demo credentials are already public

# 4. Populate MEWS service UUIDs in config/category_mapping.yaml
#    (see the comment block at the top of that file)

# 5. Start the server
uvicorn main:app --reload
```

The server starts at `http://localhost:8000`. Swagger UI is available at `/docs`.

---

## Trigger a Manual Sync

```bash
# Sync a specific date
curl -X POST http://localhost:8000/sync/run \
  -H "Content-Type: application/json" \
  -d '{"date": "2025-08-11"}'

# Sync today (omit date)
curl -X POST http://localhost:8000/sync/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

Or run the included script: `bash curl.sh`

Response:
```json
{
  "date": "2025-08-11",
  "posted": 8,
  "skipped": 0,
  "failed": 1,
  "duration_seconds": 4.2
}
```

---

## Scheduled Sync

The service registers a daily background job (APScheduler) that runs at the time configured by `SYNC_HOUR` and `SYNC_MINUTE` in `.env` (default: 22:00 UTC). The job starts automatically when the server starts and stops when it stops — no separate process needed.

Change the schedule without restarting: edit `.env` and restart the server.

---

## Framework & Scheduler Choice

**FastAPI** was chosen over Django REST Framework because this is a focused microservice with no need for Django's admin, ORM migrations, or templating. FastAPI's async-native design and minimal overhead fit the use case well.

**APScheduler** (BackgroundScheduler) was chosen over Celery Beat because it runs inside the same process as FastAPI with no external broker dependency (no Redis, no separate worker). This satisfies the single-startup-command requirement without additional infrastructure.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VENUESUITE_BASE_URL` | — | VenueSuite staging API base URL |
| `VENUESUITE_TOKEN` | — | Bearer token for VenueSuite |
| `VENUESUITE_VENUE_ID` | — | Property ID (venue_id) |
| `MEWS_BASE_URL` | — | MEWS Connector API URL |
| `MEWS_CLIENT_TOKEN` | — | MEWS ClientToken |
| `MEWS_ACCESS_TOKEN` | — | MEWS AccessToken |
| `MEWS_CLIENT_NAME` | `SynrfyRevenueSync/1.0` | Application identifier sent to MEWS |
| `SYNC_HOUR` | `22` | Hour (UTC) to run daily sync |
| `SYNC_MINUTE` | `0` | Minute to run daily sync |
| `DATABASE_URL` | `sqlite:///./synrfy.db` | SQLAlchemy database URL |
| `CATEGORY_MAPPING_PATH` | `config/category_mapping.yaml` | Path to category mapping file |
| `FALLBACK_CATEGORY` | `GeneralRevenue` | Label used in logs for unmapped categories |

---

## Category Mapping

Edit `config/category_mapping.yaml` to map VenueSuite product components to MEWS services.

**Lookup order:**
1. Compound key `"component:category"` — e.g. `"extra:av"`
2. Component key alone — e.g. `"extra"`
3. `fallback` — always present; emits a WARNING in logs when used

To find valid MEWS service IDs for your property:
```bash
curl -X POST https://api.mews-demo.com/api/connector/v1/services/getAll \
  -H "Content-Type: application/json" \
  -d '{
    "ClientToken": "<your_client_token>",
    "AccessToken": "<your_access_token>",
    "Client": "SynrfyRevenueSync/1.0"
  }'
```

Copy the `Id` values into the YAML file.

---

## Idempotency

Each posted transaction is recorded in the local SQLite database (`sync_records` table) with a unique key on `(booking_reference, slot_date, product_id)`. Re-running the sync for the same date will skip all already-posted records and report them as `skipped`.

```bash
# Verify idempotency
curl -X POST http://localhost:8000/sync/run -d '{"date": "2025-08-11"}'
# → { "posted": 8, "skipped": 0, ... }

curl -X POST http://localhost:8000/sync/run -d '{"date": "2025-08-11"}'
# → { "posted": 0, "skipped": 8, ... }
```

Inspect the database:
```bash
sqlite3 synrfy.db "SELECT booking_reference, slot_date, product_id, status, mews_charge_id FROM sync_records ORDER BY created_at DESC LIMIT 20;"
```

---

## Error Handling

- **Per-transaction isolation:** if one charge fails, the sync logs the error and continues. Partial runs are safe to re-run.
- **Category fallback:** unmapped categories use the fallback entry and emit a WARNING — they never cause a failure.
- **MEWS 429:** retried up to 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s + random jitter).
- **VenueSuite timeout:** raises immediately; sync result reflects 0 transactions processed.
- **Reservation not found:** logged as a per-transaction failure; remaining transactions continue.

---

## Known Limitations

- **VenueSuite date filtering:** The `bookings` endpoint may not support server-side date filtering. All bookings are fetched and filtered locally by `slot.start` date. For large properties with many historical bookings this could be slow. If VenueSuite adds a date-range query parameter it should be adopted.
- **MEWS service UUIDs:** The `mews_service_id` values in `category_mapping.yaml` are environment-specific. The placeholder values in the default config must be replaced before the first run.
- **SQLite concurrency:** SQLite is not safe for concurrent multi-process deployments. If horizontal scaling is needed, change `DATABASE_URL` to a PostgreSQL connection string — the SQLAlchemy abstraction requires no code changes.
- **MEWS charge endpoint:** The primary charge endpoint (`orderItems/add`) is probed at runtime on the first charge. If it returns 404 the client falls back to `products/charge`. The working endpoint is logged at INFO level on startup.
