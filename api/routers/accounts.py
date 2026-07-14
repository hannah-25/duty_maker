from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, require_admin
from api.schemas import AccountOut, AccountsOut, AccountUpdate
from core.persistence import load_state, load_users, save_users

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _roster_names(ward_id: str) -> set[str]:
    payload = load_state(ward_id) or {}
    nurses = {item["name"] for item in payload.get("nurses", [])}
    assistants = {item["name"] for item in payload.get("assistants", [])}
    return nurses | assistants


def _accounts_out(ward_id: str, current_name: str) -> AccountsOut:
    users = load_users(ward_id)
    roster = _roster_names(ward_id)
    return AccountsOut(
        accounts=[
            AccountOut(
                name=name,
                is_admin=bool(account.get("is_admin")),
                in_roster=name in roster,
                is_current=name == current_name,
            )
            for name, account in sorted(users.items())
        ],
        unregistered_names=sorted(roster - set(users)),
    )


@router.get("", response_model=AccountsOut)
def get_accounts(user: CurrentUser = Depends(require_admin)) -> AccountsOut:
    return _accounts_out(user.ward_id, user.name)


@router.patch("/{name}", response_model=AccountsOut)
def update_account(
    name: str,
    body: AccountUpdate,
    user: CurrentUser = Depends(require_admin),
) -> AccountsOut:
    if name == user.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "본인 계정의 관리자 권한은 변경할 수 없습니다.")
    users = load_users(user.ward_id)
    if name not in users:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "계정을 찾을 수 없습니다.")
    users[name]["is_admin"] = body.is_admin
    save_users(user.ward_id, users)
    return _accounts_out(user.ward_id, user.name)


@router.delete("/{name}", response_model=AccountsOut)
def delete_account(
    name: str,
    user: CurrentUser = Depends(require_admin),
) -> AccountsOut:
    if name == user.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "본인 계정은 초기화할 수 없습니다.")
    users = load_users(user.ward_id)
    if name not in users:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "계정을 찾을 수 없습니다.")
    users = {key: value for key, value in users.items() if key != name}
    save_users(user.ward_id, users)
    return _accounts_out(user.ward_id, user.name)
