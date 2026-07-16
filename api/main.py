from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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


class SPAStaticFiles(StaticFiles):
    """정적 파일이 없으면 index.html을 돌려주는 SPA 폴백.

    클린 URL(예: /wards/xxx/app)로 직접 들어오거나 새로고침해도
    프론트엔드가 클라이언트 라우팅으로 화면을 그릴 수 있게 한다.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # /api/* 오요청은 그대로 404로 두고, 그 외 경로만 앱 셸로 폴백한다.
            if exc.status_code == 404 and not path.startswith("api"):
                return await super().get_response("index.html", scope)
            raise

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
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
