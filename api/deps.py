from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, ward_id: str, name: str, is_admin: bool):
        self.ward_id = ward_id
        self.name = name
        self.is_admin = is_admin


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "인증이 필요합니다.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "토큰이 유효하지 않거나 만료되었습니다.")
    return CurrentUser(payload["ward_id"], payload["name"], payload["is_admin"])


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "관리자만 가능한 작업입니다.")
    return user
