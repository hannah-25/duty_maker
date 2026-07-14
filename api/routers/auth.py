from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.schemas import LoginRequest, RegisterRequest, TokenOut
from api.security import create_access_token
from core.auth import check_login, create_account, valid_pin_format
from core.persistence import load_state, load_users, save_users

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _roster_names(ward_id: str) -> set[str]:
    payload = load_state(ward_id) or {}
    nurses = {d["name"] for d in payload.get("nurses", [])}
    assistants = {d["name"] for d in payload.get("assistants", [])}
    return nurses | assistants


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest) -> TokenOut:
    users = load_users(body.ward_id)
    if not check_login(users, body.name, body.pin):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이름 또는 PIN이 올바르지 않습니다.")
    account = users[body.name]
    token = create_access_token(body.ward_id, body.name, is_admin=bool(account.get("is_admin")))
    return TokenOut(token=token, name=body.name, is_admin=bool(account.get("is_admin")))


@router.post("/register", response_model=TokenOut)
def register(body: RegisterRequest) -> TokenOut:
    name = body.name.strip()
    if name not in _roster_names(body.ward_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "명단에 없는 이름입니다.")
    if not valid_pin_format(body.pin):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PIN은 4~6자리 숫자여야 합니다.")

    users = load_users(body.ward_id)
    if name in users:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 등록된 이름입니다.")

    users = create_account(users, name, body.pin, is_admin=False)
    save_users(body.ward_id, users)
    token = create_access_token(body.ward_id, name, is_admin=False)
    return TokenOut(token=token, name=name, is_admin=False)
