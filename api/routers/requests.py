from __future__ import annotations

import hashlib
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import (
    DutyRequestCreate,
    DutyRequestOut,
    DutyRequestsOut,
    DutyRequestUpdate,
    RequestLockIn,
)
from api.state_store import load_ward_state, save_ward_state
from core.models import DutyRequest, ShiftType, month_dates

router = APIRouter(prefix="/api/requests", tags=["requests"])

VALID_REQUEST_SHIFTS = {ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.O}
VALID_KINDS = {"prefer", "avoid"}
VALID_DECISIONS = {"force", "ignore"}


def _request_id(req: DutyRequest) -> str:
    key = f"{req.nurse_name}|{req.day.isoformat()}|{req.kind}|{req.requested_shift.value}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def _names(ss: dict) -> list[str]:
    return [n.name for n in ss.get("nurses", [])] + [a.name for a in ss.get("assistants", [])]


def _request_out(req: DutyRequest) -> DutyRequestOut:
    return DutyRequestOut(
        id=_request_id(req),
        nurse_name=req.nurse_name,
        date=req.day.isoformat(),
        requested_shift=req.requested_shift.value,
        kind=getattr(req, "kind", "prefer"),
        decision=getattr(req, "decision", "force"),
        memo=getattr(req, "memo", ""),
    )


def _visible_requests(ss: dict, user: CurrentUser) -> list[DutyRequest]:
    requests = list(ss.get("duty_requests", []))
    if user.is_admin:
        return requests
    return [req for req in requests if req.nurse_name == user.name]


def _out(ss: dict, user: CurrentUser) -> DutyRequestsOut:
    return DutyRequestsOut(
        year=int(ss.get("year", 2026)),
        month=int(ss.get("month", 7)),
        locked=bool(ss.get("requests_locked", False)),
        names=_names(ss) if user.is_admin else [user.name],
        requests=[_request_out(req) for req in _visible_requests(ss, user)],
        is_admin=user.is_admin,
    )


def _parse_date(raw: str, year: int, month: int) -> date:
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"잘못된 날짜입니다: {raw}")
    if parsed not in month_dates(year, month):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "근무표 대상 월의 날짜만 신청할 수 있습니다.")
    return parsed


def _dedupe(requests: list[DutyRequest]) -> list[DutyRequest]:
    seen: set[str] = set()
    result: list[DutyRequest] = []
    for req in requests:
        req_id = _request_id(req)
        if req_id in seen:
            continue
        seen.add(req_id)
        result.append(req)
    return result


@router.get("", response_model=DutyRequestsOut)
def get_requests(user: CurrentUser = Depends(get_current_user)) -> DutyRequestsOut:
    return _out(load_ward_state(user.ward_id), user)


@router.post("", response_model=DutyRequestsOut)
def add_request(
    body: DutyRequestCreate,
    user: CurrentUser = Depends(get_current_user),
) -> DutyRequestsOut:
    ss = load_ward_state(user.ward_id)
    if ss.get("requests_locked") and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "근무 신청이 마감되었습니다.")

    nurse_name = body.nurse_name.strip() if body.nurse_name and user.is_admin else user.name
    if nurse_name not in _names(ss):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "명단에 없는 이름입니다.")
    if body.kind not in VALID_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "신청 유형이 올바르지 않습니다.")
    try:
        requested_shift = ShiftType(body.requested_shift)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "근무 코드가 올바르지 않습니다.")
    if requested_shift not in VALID_REQUEST_SHIFTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "신청할 수 없는 근무 코드입니다.")

    day = _parse_date(body.date, int(ss.get("year", 2026)), int(ss.get("month", 7)))
    ss["duty_requests"] = _dedupe(
        [
            *ss.get("duty_requests", []),
            DutyRequest(
                nurse_name=nurse_name,
                day=day,
                requested_shift=requested_shift,
                kind=body.kind,
                decision="force",
                memo=body.memo,
            ),
        ]
    )
    save_ward_state(user.ward_id, ss, requests_only=not user.is_admin)
    return _out(ss, user)


@router.patch("/{request_id}", response_model=DutyRequestsOut)
def update_request(
    request_id: str,
    body: DutyRequestUpdate,
    user: CurrentUser = Depends(require_admin),
) -> DutyRequestsOut:
    if body.decision not in VALID_DECISIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "반영 여부가 올바르지 않습니다.")
    ss = load_ward_state(user.ward_id)
    for req in ss.get("duty_requests", []):
        if _request_id(req) == request_id:
            req.decision = body.decision
            save_ward_state(user.ward_id, ss)
            return _out(ss, user)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "신청을 찾을 수 없습니다.")


@router.delete("/{request_id}", response_model=DutyRequestsOut)
def delete_request(
    request_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> DutyRequestsOut:
    ss = load_ward_state(user.ward_id)
    if ss.get("requests_locked") and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "근무 신청이 마감되었습니다.")
    remaining = []
    found = False
    for req in ss.get("duty_requests", []):
        allowed = user.is_admin or req.nurse_name == user.name
        if _request_id(req) == request_id and allowed:
            found = True
            continue
        remaining.append(req)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "신청을 찾을 수 없습니다.")
    ss["duty_requests"] = remaining
    save_ward_state(user.ward_id, ss, requests_only=not user.is_admin)
    return _out(ss, user)


@router.put("/lock", response_model=DutyRequestsOut)
def set_request_lock(
    body: RequestLockIn,
    user: CurrentUser = Depends(require_admin),
) -> DutyRequestsOut:
    ss = load_ward_state(user.ward_id)
    ss["requests_locked"] = body.locked
    save_ward_state(user.ward_id, ss)
    return _out(ss, user)
