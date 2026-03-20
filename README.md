# Synrfy Revenue Sync

A Python service that runs daily and posts VenueSuite event transactions into MEWS before the night audit.

**Data flow:**
```
VenueSuite (bookings + slots + products)
    → filter by slot date
    → look up MEWS reservation by booking reference
    → get or create a billing account
    → post each product line as a charge
```

Revenue is posted **per event, per day** — never aggregated across events or days.

---

## Requirements

- Python 3.10+
- A VenueSuite staging API token (provided by Synrfy)
- MEWS demo credentials (public — already included in `.env.example`)

---

## Setup

**1. Clone the repo and create a virtual environment**

```bash
git clone <repo-url>
cd synrfy-revenue-sync
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure credentials**

```bash
cp .env.example .env
```

Open `.env` and fill in your VenueSuite token. The MEWS demo credentials are already populated — no action needed for MEWS.

```env
VENUESUITE_TOKEN=your_token_here
```

**4. Configure category mapping**

Open `config/category_mapping.yaml`. Each entry maps a VenueSuite product component to a MEWS service ID.

To find valid MEWS service IDs for your property:

```bash
curl -X POST https://api.mews-demo.com/api/connector/v1/services/getAll \
  -H "Content-Type: application/json" \
  -d '{
    "ClientToken": "E0D439EE522F44368DC78E1BFB03710C-D24FB11DBE31D4621C4817E028D9E1D",
    "AccessToken": "C66EF7B239D24632943D115EDE9CB810-EA00F8FD8294692C940F6B5A8F9453D",
    "Client": "SynrfyRevenueSync/1.0"
  }'
```

Copy the `Id` values for the relevant services into the YAML file.

**5. Run the demo script (optional but recommended)**

```bash
python demo_test.py
```

Runs 6 checks without starting a server: verifies credentials, pings both APIs, runs a live sync, prints results, and confirms idempotency. Pass a date to test a specific day:

```bash
python demo_test.py 2026-04-02
```

**6. Start the server**

```bash
uvicorn main:app --reload
```

The server starts at `http://localhost:8000`.

| URL | Purpose |
|---|---|
| `http://localhost:8000/ui` | Web dashboard (trigger syncs, view history) |
| `http://localhost:8000/docs` | Interactive API docs |

---

## Web Dashboard

Open `http://localhost:8000/ui` in a browser after starting the server.

- **Run Sync panel** — pick a date and click "Run Sync". Results (posted / skipped / failed / duration) appear inline.
- **History table** — last 50 sync records, colour-coded by status, with bill and charge IDs.
- **Status bar** — shows the last run timestamp and next scheduled sync time.

---

## Triggering a Sync

### Manual (via HTTP)

Sync a specific date:

```bash
curl -X POST http://localhost:8000/sync/run \
  -H "Content-Type: application/json" \
  -d '{"date": "2025-08-11"}'
```

Sync today (omit the date field):

```bash
curl -X POST http://localhost:8000/sync/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

Or run the included script: `bash curl.sh`

### Sync history (via HTTP)

```bash
curl http://localhost:8000/sync/history
```

Returns the 50 most recent sync records as JSON.

**Response:**

```json
{
  "date": "2025-08-11",
  "posted": 8,
  "skipped": 0,
  "failed": 1,
  "duration_seconds": 4.2
}
```

- `posted` — charges successfully written to MEWS
- `skipped` — already posted in a previous run (idempotency)
- `failed` — errors logged, sync continued

### Automatic (daily schedule)

The sync runs automatically every day at `SYNC_HOUR:SYNC_MINUTE` UTC (default: 22:00). This is configured in `.env`:

```env
SYNC_HOUR=22
SYNC_MINUTE=0
```

The scheduler starts and stops with the server — no separate process needed.

---

## How Idempotency Works

Every successfully posted transaction is recorded in the local database (`sync_records` table) with a unique key on `(booking_reference, slot_date, product_id)`. If you re-run the sync for the same date, already-posted transactions are detected and skipped.

```bash
# First run
curl -X POST http://localhost:8000/sync/run -d '{"date": "2025-08-11"}'
# → { "posted": 8, "skipped": 0, "failed": 0 }

# Second run — nothing is posted again
curl -X POST http://localhost:8000/sync/run -d '{"date": "2025-08-11"}'
# → { "posted": 0, "skipped": 8, "failed": 0 }
```

To inspect the database directly:

```bash
sqlite3 synrfy.db "SELECT booking_reference, slot_date, product_id, status, mews_charge_id FROM sync_records ORDER BY created_at DESC LIMIT 20;"
```

---

## Category Mapping

`config/category_mapping.yaml` controls how VenueSuite product components map to MEWS services. Edit this file to point each component type at the correct MEWS service ID for your property.

**Lookup order (most to least specific):**

1. `"component:category"` compound key — e.g. `"extra:av"`
2. `"component"` key alone — e.g. `"extra"`
3. `"fallback"` — always present; a `WARNING` is logged whenever it is used

Components currently mapped: `space` (room hire), `package` (F&B packages), `equipment` (AV/presentation), `catering` (food & beverage), `hotelroom`, `room`.

If an unmapped component comes through, the fallback is used and a warning is logged — the sync never fails because of a missing mapping.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Unmapped category | Uses fallback, logs WARNING, continues |
| MEWS 429 rate limit | Retries up to 5 times with exponential backoff (1s → 16s + jitter) |
| VenueSuite timeout | Sync aborts for that run, logs ERROR, returns 0 results |
| MEWS reservation not found | Logs ERROR for that transaction, continues with the rest |
| Any other error per transaction | Logs ERROR, marks as failed in DB, continues |

Partial runs are always safe to re-run — only failed transactions will be retried.

---

## Framework & Scheduler Choice

**FastAPI** was chosen over Django REST Framework because this is a single-purpose microservice. Django's admin, ORM migrations, and templating are unnecessary here. FastAPI is lighter, async-native, and starts with one command.

**APScheduler** (BackgroundScheduler) was chosen over Celery Beat because it runs inside the same process as FastAPI — no Redis, no separate worker process. The result is a single `uvicorn main:app --reload` command that handles both the API and the scheduler.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `VENUESUITE_BASE_URL` | `https://api-vms.qa.venuesuite.com` | VenueSuite API base URL |
| `VENUESUITE_TOKEN` | — | VenueSuite API token (sent as `X-AUTH-TOKEN` header) |
| `VENUESUITE_VENUE_ID` | `1751` | VenueSuite property ID |
| `MEWS_BASE_URL` | `https://api.mews-demo.com` | MEWS Connector API URL |
| `MEWS_CLIENT_TOKEN` | *(see .env.example)* | MEWS ClientToken |
| `MEWS_ACCESS_TOKEN` | *(see .env.example)* | MEWS AccessToken |
| `MEWS_CLIENT_NAME` | `SynrfyRevenueSync/1.0` | Application identifier sent to MEWS |
| `SYNC_HOUR` | `22` | Hour (UTC) for daily scheduled sync |
| `SYNC_MINUTE` | `0` | Minute for daily scheduled sync |
| `DATABASE_URL` | `sqlite:///./synrfy.db` | SQLAlchemy database URL |
| `CATEGORY_MAPPING_PATH` | `config/category_mapping.yaml` | Path to the category mapping file |

---

## Known Limitations

- **VenueSuite date filtering is local.** The `start`/`end` query params on the bookings endpoint filter by booking period, not slot date. All bookings are fetched and then filtered locally by `slot.start` date. This is correct but may be slow for properties with large booking histories.

- **MEWS service UUIDs are property-specific.** The demo UUIDs in `category_mapping.yaml` work against the public MEWS demo environment. For a production property, replace them with UUIDs from that property's MEWS instance using `services/getAll`.

- **Staging environments are not linked.** In the staging setup, VenueSuite booking references do not correspond to reservation numbers in the MEWS demo — they are independent test systems. The full end-to-end flow (post confirmed, charge visible in MEWS) can only be verified once both systems are pointed at the same production or pre-production environment.

- **SQLite is single-process only.** Fine for this use case. If the service ever needs to run as multiple parallel instances, change `DATABASE_URL` to a PostgreSQL connection string — no code changes required.
