from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles

from api.routers import (
    accounts,
    auth,
    exports,
    nurses,
    requests,
    requirements,
    schedule,
    settings,
    wards,
)
from core.persistence import storage_backend, validate_storage_backend

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_storage_backend()
    yield


app = FastAPI(title="Duty Maker API", lifespan=lifespan)

app.include_router(wards.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(nurses.router)
app.include_router(requirements.router)
app.include_router(settings.router)
app.include_router(requests.router)
app.include_router(schedule.router)
app.include_router(exports.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready() -> dict[str, str]:
    try:
        validate_storage_backend()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage backend is not ready",
        ) from exc
    return {"status": "ready", "storage": storage_backend()}

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
