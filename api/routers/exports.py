from __future__ import annotations

import io
from datetime import date
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.deps import CurrentUser, get_current_user
from api.routers.schedule import _off_target, _selected_holidays
from api.state_store import load_ward_state
from core.hwpx_export import export_schedule_hwpx
from core.models import ShiftType, month_dates

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _ensure_visible_schedule(user: CurrentUser) -> dict:
    ss = load_ward_state(user.ward_id)
    result = ss.get("schedule_result")
    if result is None or not result.feasible:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "내보낼 수 있는 근무표가 없습니다.")
    if not user.is_admin and not ss.get("result_published", False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "공개된 근무표가 없습니다.")
    return ss


def _request_highlight_days(result) -> set[tuple[str, date]]:
    cells: set[tuple[str, date]] = set()
    for req in result.honored_duty_requests:
        is_off_prefer = getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (
            ShiftType.O,
            ShiftType.AL,
        )
        is_avoid = getattr(req, "kind", "prefer") == "avoid"
        if is_off_prefer or is_avoid:
            cells.add((req.nurse_name, req.day))
    return cells


def _assistant_marks(ss: dict) -> dict[tuple[str, date], ShiftType]:
    names = {assistant.name for assistant in ss.get("assistants", [])}
    return {
        (req.nurse_name, req.day): req.requested_shift
        for req in ss.get("duty_requests", [])
        if req.nurse_name in names
        and getattr(req, "decision", "force") != "ignore"
        and getattr(req, "kind", "prefer") == "prefer"
    }


def _download_response(data: bytes, filename: str, media_type: str) -> Response:
    quoted = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}
    return Response(content=data, media_type=media_type, headers=headers)


@router.get("/hwpx")
def export_hwpx(user: CurrentUser = Depends(get_current_user)) -> Response:
    ss = _ensure_visible_schedule(user)
    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    holidays = _selected_holidays(ss, year, month)
    off_target_values = _off_target(ss, year, month)
    off_target_value = next(iter(off_target_values.values()), 0)
    result = ss["schedule_result"]
    data = export_schedule_hwpx(
        ss.get("nurses", []),
        year,
        month,
        result.assignments,
        holidays,
        off_target_value,
        _request_highlight_days(result),
        assistants=ss.get("assistants", []),
        assistant_marks=_assistant_marks(ss),
    )
    return _download_response(data, f"{year}-{month:02d}_duty_schedule.hwpx", "application/octet-stream")


@router.get("/xlsx")
def export_xlsx(user: CurrentUser = Depends(get_current_user)) -> Response:
    ss = _ensure_visible_schedule(user)
    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    result = ss["schedule_result"]
    days = month_dates(year, month)
    rows = [
        [result.assignments[(nurse.name, day)].value for day in days]
        for nurse in ss.get("nurses", [])
    ]
    df = pd.DataFrame(
        rows,
        index=[nurse.name for nurse in ss.get("nurses", [])],
        columns=[f"{day.month}/{day.day}" for day in days],
    )
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="근무표")
    return _download_response(
        out.getvalue(),
        f"{year}-{month:02d}_duty_schedule.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
