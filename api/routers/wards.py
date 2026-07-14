from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, status

from api.schemas import WardCreate, WardOut, WardRegisterOut
from api.security import create_access_token
from core.auth import create_account, valid_pin_format
from core.persistence import create_ward, list_wards, save_users

router = APIRouter(prefix="/api/wards", tags=["wards"])

_DEFAULT_REGISTRATION_CODE = "admin1234"


def _registration_code() -> str:
    return os.environ.get("WARD_REGISTRATION_CODE", _DEFAULT_REGISTRATION_CODE)


@router.get("", response_model=list[WardOut])
def get_wards() -> list[WardOut]:
    wards = list_wards()
    return [
        WardOut(ward_id=ward_id, hospital_name=info["hospital_name"], ward_name=info["ward_name"])
        for ward_id, info in wards.items()
    ]


@router.post("", response_model=WardRegisterOut)
def register_ward(body: WardCreate) -> WardRegisterOut:
    if body.registration_code != _registration_code():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "병동 등록 코드가 올바르지 않습니다.")
    if not valid_pin_format(body.admin_pin):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PIN은 4~6자리 숫자여야 합니다.")

    ward_id = create_ward(body.hospital_name, body.ward_name)
    if ward_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 등록된 병원/병동입니다.")

    admin_name = body.admin_name.strip()
    save_users(ward_id, create_account({}, admin_name, body.admin_pin, is_admin=True))
    token = create_access_token(ward_id, admin_name, is_admin=True)
    return WardRegisterOut(ward_id=ward_id, token=token, name=admin_name, is_admin=True)
