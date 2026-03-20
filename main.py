from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.database import Base, engine
from app.routers import sync as sync_router
from app.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables if they don't exist yet (idempotent)
    Base.metadata.create_all(bind=engine)

    # Start the background scheduler (daily sync before night audit)
    scheduler = start_scheduler()

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Synrfy Revenue Sync",
    description="Syncs daily VenueSuite event transactions into MEWS.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(sync_router.router, prefix="/sync", tags=["sync"])


@app.get("/ui", include_in_schema=False)
def ui_redirect():
    return RedirectResponse(url="/sync/ui")
