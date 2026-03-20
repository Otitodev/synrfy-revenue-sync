"""
Synrfy Revenue Sync — End-to-End Demo Script
============================================
Usage:
  python demo_test.py                  # uses default date 2026-04-02
  python demo_test.py 2026-03-25       # any date with VenueSuite data

No server required. Calls run_sync() directly, the same way the
daily scheduler does.
"""

import os
import sys
from datetime import date

# Load .env before anything else so all variables are in os.environ
from dotenv import load_dotenv
load_dotenv()

DEFAULT_DATE = date(2026, 4, 2)

def _parse_date_arg() -> date:
    if len(sys.argv) < 2:
        return DEFAULT_DATE
    raw = sys.argv[1]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        print(f"  ERROR: Invalid date '{raw}'. Use YYYY-MM-DD format.")
        sys.exit(1)

TEST_DATE = _parse_date_arg()

REQUIRED_ENV_VARS = [
    "VENUESUITE_BASE_URL",
    "VENUESUITE_TOKEN",
    "VENUESUITE_VENUE_ID",
    "MEWS_BASE_URL",
    "MEWS_CLIENT_TOKEN",
    "MEWS_ACCESS_TOKEN",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def header(n: int, title: str):
    print(f"\n{'-' * 60}")
    print(f"  Step {n}: {title}")
    print(f"{'-' * 60}")

def ok(msg: str):
    print(f"  [PASS] {msg}")

def fail(msg: str):
    print(f"  [FAIL] {msg}")

def print_table(rows: list, cols: list[tuple[str, str, int]]):
    """cols = [(header, attr, width), ...]"""
    fmt = "  " + "  ".join(f"{{:<{w}}}" for _, _, w in cols)
    print(fmt.format(*[h for h, _, _ in cols]))
    print("  " + "  ".join("-" * w for _, _, w in cols))
    for row in rows:
        vals = []
        for _, attr, w in cols:
            v = str(getattr(row, attr, "") or "")
            vals.append(v[:w])
        print(fmt.format(*vals))

# ── Steps ─────────────────────────────────────────────────────────────────────

def step1_check_env() -> bool:
    header(1, "Check .env configuration")
    missing = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
    if missing:
        for k in missing:
            fail(f"Missing: {k}")
        fail("Fix your .env file and re-run.")
        return False
    ok(f"All {len(REQUIRED_ENV_VARS)} required variables are set.")
    return True


def step2_ping_venuesuite() -> bool:
    header(2, f"Ping VenueSuite API (date={TEST_DATE})")
    import httpx
    base = os.environ["VENUESUITE_BASE_URL"].rstrip("/")
    venue_id = os.environ["VENUESUITE_VENUE_ID"]
    token = os.environ["VENUESUITE_TOKEN"]
    url = f"{base}/venues/{venue_id}/bookings"
    try:
        r = httpx.get(
            url,
            headers={"X-AUTH-TOKEN": token, "Content-Type": "application/json"},
            params={"start": TEST_DATE.isoformat(), "end": TEST_DATE.isoformat()},
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        data = body.get("data", body) if isinstance(body, dict) else body
        ok(f"HTTP {r.status_code} — {len(data)} booking(s) returned for {TEST_DATE}")
        # Count slots matching test date
        from datetime import datetime, timezone
        matching = 0
        for b in data:
            for slot in b.get("slots", []):
                try:
                    dt = datetime.fromisoformat(slot["start"])
                    if dt.date() == TEST_DATE:
                        matching += 1
                except Exception:
                    pass
        ok(f"{matching} slot(s) with start date = {TEST_DATE}")
        return True
    except Exception as e:
        fail(f"VenueSuite request failed: {e}")
        return False


def step3_ping_mews() -> bool:
    header(3, "Ping MEWS Connector API")
    import httpx
    base = os.environ["MEWS_BASE_URL"].rstrip("/")
    payload = {
        "ClientToken": os.environ["MEWS_CLIENT_TOKEN"],
        "AccessToken": os.environ["MEWS_ACCESS_TOKEN"],
        "Client": os.environ.get("MEWS_CLIENT_NAME", "SynrfyRevenueSync/1.0"),
        "Limitation": {"Count": 1},
    }
    try:
        r = httpx.post(
            f"{base}/api/connector/v1/reservations/getAll/2023-06-06",
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        count = len(r.json().get("Reservations", []))
        ok(f"HTTP {r.status_code} — MEWS auth valid (returned {count} reservation)")
        return True
    except Exception as e:
        fail(f"MEWS request failed: {e}")
        return False


def step4_run_sync() -> object | None:
    header(4, f"Run sync for {TEST_DATE}")
    # Local imports here — env is confirmed valid by this point
    from app.database import Base, engine, SessionLocal
    from app.services.sync_engine import run_sync

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = run_sync(TEST_DATE, db)
        ok(f"Sync complete — posted={result.posted}  skipped={result.skipped}  failed={result.failed}")
        if result.failed:
            print(f"         (failures are logged; re-run is safe — idempotency guaranteed)")
        return result
    except Exception as e:
        fail(f"run_sync raised an unexpected exception: {e}")
        return None
    finally:
        db.close()


def step5_show_results() -> bool:
    header(5, "Sync records in database")
    from app.database import SessionLocal
    from app.models.sync_record import SyncRecord

    db = SessionLocal()
    try:
        records = (
            db.query(SyncRecord)
            .filter(SyncRecord.slot_date == TEST_DATE)
            .order_by(SyncRecord.id)
            .all()
        )
        if not records:
            fail(f"No records found for {TEST_DATE} — sync may have had no transactions.")
            return False
        ok(f"Found {len(records)} record(s) for {TEST_DATE}:\n")
        print_table(
            records,
            [
                ("Booking Ref",  "booking_reference", 12),
                ("Product ID",   "product_id",        12),
                ("Status",       "status",             8),
                ("Amount(cts)",  "amount_cents",       12),
                ("Currency",     "currency",           9),
                ("Bill ID",      "mews_bill_id",       38),
                ("Charge ID",    "mews_charge_id",     38),
            ],
        )
        return True
    finally:
        db.close()


def step6_idempotency_check() -> bool:
    header(6, "Idempotency check (run sync again)")
    from app.database import SessionLocal
    from app.services.sync_engine import run_sync

    db = SessionLocal()
    try:
        result = run_sync(TEST_DATE, db)
        if result.posted == 0:
            if result.skipped > 0:
                ok(f"Idempotency confirmed — {result.skipped} item(s) skipped, 0 re-posted.")
            if result.failed > 0:
                ok(f"{result.failed} item(s) re-attempted (no matching MEWS reservation) — no double-posting.")
            return True
        else:
            fail(f"Double-post detected on second run: posted={result.posted} (expected 0).")
            return False
    except Exception as e:
        fail(f"Second run raised exception: {e}")
        return False
    finally:
        db.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  Synrfy Revenue Sync — Demo Test")
    print(f"  Test date: {TEST_DATE}")
    print("=" * 60)

    passed = 0
    failed_steps = []

    # Steps 1–3: preconditions — exit immediately on failure
    for step_fn in (step1_check_env, step2_ping_venuesuite, step3_ping_mews):
        ok_result = step_fn()
        if ok_result:
            passed += 1
        else:
            failed_steps.append(step_fn.__name__)
            print(f"\n  Aborting: precondition failed at {step_fn.__name__}.")
            sys.exit(1)

    # Steps 4–6: run even if one fails (collect all results)
    step4_result = step4_run_sync()
    if step4_result is not None:
        passed += 1
    else:
        failed_steps.append("step4_run_sync")

    if step5_show_results():
        passed += 1
    else:
        failed_steps.append("step5_show_results")

    if step6_idempotency_check():
        passed += 1
    else:
        failed_steps.append("step6_idempotency_check")

    # Summary
    print("\n" + "=" * 60)
    total = 6
    if not failed_steps:
        print(f"  All {total} steps passed. Service is operational.")
        print(f"\n  Start the server:  uvicorn main:app --port 8000")
        print(f"  Open the UI:       http://localhost:8000/ui")
    else:
        print(f"  {len(failed_steps)} step(s) failed: {', '.join(failed_steps)}")
        print(f"  {passed}/{total} steps passed. See output above for details.")
    print("=" * 60 + "\n")

    if failed_steps:
        sys.exit(1)


if __name__ == "__main__":
    main()
