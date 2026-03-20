import time
from datetime import date as date_type
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.sync_record import SyncRecord
from app.schemas.sync import SyncRequest, SyncResponse, SyncRecordOut
from app.services.sync_engine import run_sync

router = APIRouter()


@router.post("/run", response_model=SyncResponse)
def trigger_sync(request: SyncRequest, db: Session = Depends(get_db)) -> SyncResponse:
    """
    Manually trigger a revenue sync for a given date.
    Omit the date field to sync today's transactions.
    """
    target_date = request.date or date_type.today()
    start = time.monotonic()
    result = run_sync(target_date, db)
    result.duration_seconds = round(time.monotonic() - start, 2)
    return result


@router.get("/history", response_model=list[SyncRecordOut])
def get_history(db: Session = Depends(get_db)):
    """Return the 50 most recent sync records."""
    return (
        db.query(SyncRecord)
        .order_by(SyncRecord.created_at.desc())
        .limit(50)
        .all()
    )


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synrfy Revenue Sync</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f6fa; color: #2d3436; }
  header { background: #2d3436; color: #fff; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.2rem; font-weight: 600; }
  #status-bar { font-size: 0.8rem; opacity: 0.75; }
  main { max-width: 1100px; margin: 24px auto; padding: 0 16px; display: flex; flex-direction: column; gap: 20px; }
  .panel { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .panel h2 { font-size: 1rem; font-weight: 600; margin-bottom: 14px; color: #2d3436; }
  .row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  label { font-size: 0.875rem; }
  input[type=date] { padding: 7px 10px; border: 1px solid #dfe6e9; border-radius: 5px; font-size: 0.875rem; }
  button { padding: 8px 18px; background: #0984e3; color: #fff; border: none; border-radius: 5px; font-size: 0.875rem; cursor: pointer; transition: background .15s; }
  button:hover:not(:disabled) { background: #0773c5; }
  button:disabled { opacity: 0.55; cursor: not-allowed; }
  #sync-result { margin-top: 14px; padding: 12px 16px; border-radius: 6px; font-size: 0.875rem; display: none; }
  #sync-result.success { background: #d3f9d8; color: #1e6b2e; }
  #sync-result.error { background: #ffe0e0; color: #b00020; }
  .stat { display: inline-block; margin-right: 20px; }
  .stat span { font-weight: 700; font-size: 1.1rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th { text-align: left; padding: 8px 10px; background: #f0f3f8; border-bottom: 2px solid #dfe6e9; font-weight: 600; white-space: nowrap; }
  td { padding: 7px 10px; border-bottom: 1px solid #f0f3f8; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  tr.posted td:nth-child(4) { color: #1e6b2e; font-weight: 600; }
  tr.failed td:nth-child(4) { color: #b00020; font-weight: 600; }
  .trunc { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; cursor: default; }
  .refresh-btn { float: right; padding: 4px 12px; font-size: 0.75rem; background: #636e72; }
  .refresh-btn:hover:not(:disabled) { background: #2d3436; }
  #empty-msg { text-align: center; padding: 24px; color: #636e72; font-size: 0.875rem; }
</style>
</head>
<body>
<header>
  <h1>Synrfy Revenue Sync</h1>
  <div id="status-bar">Next scheduled sync: 22:00 UTC daily &nbsp;|&nbsp; Last run: <span id="last-run">—</span></div>
</header>
<main>
  <div class="panel">
    <h2>Run Sync</h2>
    <div class="row">
      <label>Date: <input type="date" id="sync-date"></label>
      <button id="run-btn" onclick="runSync()">Run Sync</button>
    </div>
    <div id="sync-result"></div>
  </div>
  <div class="panel">
    <h2>Sync History <button class="refresh-btn" onclick="loadHistory()">Refresh</button></h2>
    <div id="history-wrap">
      <div id="empty-msg">Loading...</div>
    </div>
  </div>
</main>
<script>
  function today() {
    return new Date().toISOString().slice(0, 10);
  }

  window.onload = function() {
    document.getElementById('sync-date').value = today();
    loadHistory();
  };

  async function runSync() {
    const dateVal = document.getElementById('sync-date').value;
    const btn = document.getElementById('run-btn');
    const resultDiv = document.getElementById('sync-result');
    btn.disabled = true;
    resultDiv.style.display = 'none';
    try {
      const res = await fetch('/sync/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({date: dateVal})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      resultDiv.className = 'success';
      resultDiv.innerHTML =
        '<div class="stat">Posted <span>' + data.posted + '</span></div>' +
        '<div class="stat">Skipped <span>' + data.skipped + '</span></div>' +
        '<div class="stat">Failed <span>' + data.failed + '</span></div>' +
        '<div class="stat">Duration <span>' + data.duration_seconds + 's</span></div>';
      resultDiv.style.display = 'block';
      loadHistory();
    } catch(e) {
      resultDiv.className = 'error';
      resultDiv.textContent = 'Error: ' + e.message;
      resultDiv.style.display = 'block';
    } finally {
      btn.disabled = false;
    }
  }

  async function loadHistory() {
    try {
      const res = await fetch('/sync/history');
      const rows = await res.json();
      const wrap = document.getElementById('history-wrap');
      if (!rows.length) {
        wrap.innerHTML = '<div id="empty-msg">No sync records yet.</div>';
        return;
      }
      // Update status bar last-run
      document.getElementById('last-run').textContent = new Date(rows[0].created_at + 'Z').toLocaleString();

      let html = '<table><thead><tr>' +
        '<th>Booking Ref</th><th>Slot Date</th><th>Product ID</th><th>Status</th>' +
        '<th>Amount</th><th>Currency</th><th>Bill ID</th><th>Charge ID</th><th>Error</th>' +
        '</tr></thead><tbody>';
      for (const r of rows) {
        const amt = (r.amount_cents / 100).toFixed(2);
        const billShort = r.mews_bill_id ? r.mews_bill_id.slice(0, 8) + '…' : '—';
        const chargeShort = r.mews_charge_id ? r.mews_charge_id.slice(0, 8) + '…' : '—';
        const errShort = r.error_message ? r.error_message.slice(0, 45) + (r.error_message.length > 45 ? '…' : '') : '—';
        html += '<tr class="' + r.status + '">' +
          '<td>' + esc(r.booking_reference) + '</td>' +
          '<td>' + esc(r.slot_date) + '</td>' +
          '<td>' + r.product_id + '</td>' +
          '<td>' + r.status + '</td>' +
          '<td>' + amt + '</td>' +
          '<td>' + esc(r.currency) + '</td>' +
          '<td><span class="trunc" title="' + esc(r.mews_bill_id || '') + '">' + esc(billShort) + '</span></td>' +
          '<td><span class="trunc" title="' + esc(r.mews_charge_id || '') + '">' + esc(chargeShort) + '</span></td>' +
          '<td><span class="trunc" title="' + esc(r.error_message || '') + '">' + esc(errShort) + '</span></td>' +
          '</tr>';
      }
      html += '</tbody></table>';
      wrap.innerHTML = html;
    } catch(e) {
      document.getElementById('history-wrap').innerHTML =
        '<div id="empty-msg">Failed to load history: ' + e.message + '</div>';
    }
  }

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
</script>
</body>
</html>"""


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return HTMLResponse(content=_DASHBOARD_HTML)
