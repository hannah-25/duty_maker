from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import AssistantOut, NurseOut, RosterIn, RosterOut
from api.state_store import load_ward_state, save_ward_state
from core.models import Assistant, Nurse, NurseLevel, ShiftType

router = APIRouter(prefix="/api/nurses", tags=["nurses"])


def _nurse_out(n: Nurse) -> NurseOut:
    return NurseOut(
        name=n.name,
        level=n.level.value if n.level else "junior",
        allowed_shifts=sorted(s.value for s in (n.allowed_shifts or set())),
        max_n_hard=n.max_n_hard,
        n_soft_consecutive_limit=n.n_soft_consecutive_limit,
        al_target=n.al_target,
        weekday_only=n.weekday_only,
        is_helper=n.is_helper,
        helper_shifts={d.isoformat(): s.value for d, s in (n.helper_shifts or {}).items()},
        helper_workdays=n.helper_workdays,
    )


def _roster_out(ss: dict) -> RosterOut:
    return RosterOut(
        nurses=[_nurse_out(n) for n in ss["nurses"]],
        assistants=[AssistantOut(name=a.name, role=a.role) for a in ss["assistants"]],
    )


@router.get("", response_model=RosterOut)
def get_roster(user: CurrentUser = Depends(get_current_user)) -> RosterOut:
    return _roster_out(load_ward_state(user.ward_id))


@router.put("", response_model=RosterOut)
def put_roster(body: RosterIn, user: CurrentUser = Depends(require_admin)) -> RosterOut:
    ss = load_ward_state(user.ward_id)
    try:
        ss["nurses"] = [
            Nurse(
                name=n.name.strip(),
                level=None if n.is_helper else NurseLevel(n.level),
                allowed_shifts={ShiftType(s) for s in n.allowed_shifts} or None,
                max_n_hard=n.max_n_hard if n.max_n_hard is not None else 8,
                n_soft_consecutive_limit=n.n_soft_consecutive_limit,
                al_target=n.al_target,
                weekday_only=n.weekday_only,
                is_helper=n.is_helper,
                helper_shifts=dict(n.helper_shifts) if n.is_helper else {},
                helper_workdays=n.helper_workdays if n.is_helper else None,
            )
            for n in body.nurses
            if n.name.strip()
        ]
        ss["assistants"] = [
            Assistant(name=a.name.strip(), role=a.role.strip() or "간호조무사")
            for a in body.assistants
            if a.name.strip()
        ]
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    save_ward_state(user.ward_id, ss)
    return _roster_out(ss)
