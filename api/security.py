"""JWT issue/validation helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12
_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"


def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", _DEFAULT_SECRET)


def create_access_token(ward_id: str, name: str, is_admin: bool) -> str:
    payload = {
        "ward_id": ward_id,
        "name": name,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Return token payload or raise jwt.PyJWTError."""
    return jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
