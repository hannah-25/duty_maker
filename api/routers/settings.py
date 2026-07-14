from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import WardSettings
from api.state_store import load_ward_state, save_ward_state
from core.constraints import merge_ward_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_out(ss: dict) -> WardSettings:
    return WardSettings(**merge_ward_settings(ss.get("constraint_settings")))


@router.get("", response_model=WardSettings)
def get_settings(user: CurrentUser = Depends(get_current_user)) -> WardSettings:
    return _settings_out(load_ward_state(user.ward_id))


@router.put("", response_model=WardSettings)
def put_settings(
    body: WardSettings,
    user: CurrentUser = Depends(require_admin),
) -> WardSettings:
    ss = load_ward_state(user.ward_id)
    ss["constraint_settings"] = body.model_dump()
    save_ward_state(user.ward_id, ss)
    return _settings_out(ss)
