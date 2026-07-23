from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import WardSettings
from api.state_store import (
    default_charge_minimums,
    load_ward_state,
    resolve_ward_settings,
    save_ward_state,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=WardSettings)
def get_settings(user: CurrentUser = Depends(get_current_user)) -> WardSettings:
    return WardSettings(**resolve_ward_settings(load_ward_state(user.ward_id)))


@router.put("", response_model=WardSettings)
def put_settings(
    body: WardSettings,
    user: CurrentUser = Depends(require_admin),
) -> WardSettings:
    ss = load_ward_state(user.ward_id)
    # 기본값(목표÷2)과 같은 값은 저장하지 않아 목표가 바뀌면 자동으로 따라간다.
    defaults = default_charge_minimums(ss)
    prior_use_s_shift = bool(resolve_ward_settings(ss).get("use_s_shift", True))
    submitted = body.model_dump()
    overrides = {key: value for key, value in submitted.items() if value != defaults.get(key)}
    ss["constraint_settings"] = overrides
    if prior_use_s_shift != body.use_s_shift:
        ss["schedule_revision"] = int(ss.get("schedule_revision", 0)) + 1
        ss["schedule_previews"] = {}
    save_ward_state(user.ward_id, ss)
    return WardSettings(**resolve_ward_settings(ss))
