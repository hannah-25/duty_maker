from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
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

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Duty Maker API")

app.include_router(wards.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(nurses.router)
app.include_router(requirements.router)
app.include_router(settings.router)
app.include_router(requests.router)
app.include_router(schedule.router)
app.include_router(exports.router)

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
