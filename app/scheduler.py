import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.services.sync_engine import run_sync
from app.settings import get_settings

logger = logging.getLogger(__name__)


def start_scheduler() -> BackgroundScheduler:
    """
    Register and start the daily revenue sync job.
    Returns the scheduler so the caller (lifespan) can shut it down cleanly.
    """
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        func=_scheduled_sync,
        trigger=CronTrigger(
            hour=settings.sync_hour,
            minute=settings.sync_minute,
            timezone="UTC",
        ),
        id="daily_revenue_sync",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — daily sync at %02d:%02d UTC",
        settings.sync_hour,
        settings.sync_minute,
    )
    return scheduler


def _scheduled_sync() -> None:
    """Wrapper that opens a DB session, runs the sync, and closes cleanly."""
    target_date = date.today()
    logger.info("Scheduled sync triggered for %s", target_date)
    db = SessionLocal()
    try:
        run_sync(target_date, db)
    finally:
        db.close()
