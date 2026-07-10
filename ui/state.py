from __future__ import annotations

import math
from dataclasses import replace

import streamlit as st

from core.models import Nurse, NurseLevel, ShiftRequirement, ShiftType
from core.persistence import apply_state, clear_state, load_state
from core.sample_data import ward_templates


LEVEL_LABELS = {
    NurseLevel.SENIOR_CHARGE: "차지만",
    NurseLevel.MIDDLE: "차지&액팅",
    NurseLevel.JUNIOR: "액팅만",
    NurseLevel.NEW_JUNIOR: "신규",
}
LABEL_TO_LEVEL = {label: level for level, label in LEVEL_LABELS.items()}


def init_state(ward_id: str) -> None:
    # 병동이 바뀌면(최초 로그인 포함) 그 병동의 저장 데이터를 다시 불러온다
    if st.session_state.get("_state_loaded_ward") != ward_id:
        st.session_state._state_loaded_ward = ward_id
        for key in (
            "nurses",
            "assistants",
            "weekday_template",
            "weekend_template",
            "schedule_result",
            "validation_report",
            "duty_requests",
            "year",
            "month",
            "selected_holidays",
            "date_override_rows",
            "date_overrides",
            "_last_saved_state",
        ):
            st.session_state.pop(key, None)
        payload = load_state(ward_id)
        if payload:
            apply_state(st.session_state, payload)
    if "nurses" not in st.session_state:
        st.session_state.nurses = []
    if "assistants" not in st.session_state:
        st.session_state.assistants = []
    if "weekday_template" not in st.session_state or "weekend_template" not in st.session_state:
        weekday, weekend = ward_templates()
        st.session_state.weekday_template = weekday
        st.session_state.weekend_template = weekend
    if "schedule_result" not in st.session_state:
        st.session_state.schedule_result = None
    if "validation_report" not in st.session_state:
        st.session_state.validation_report = None
    if "duty_requests" not in st.session_state:
        st.session_state.duty_requests = []
    if "year" not in st.session_state:
        st.session_state.year = 2026
    if "month" not in st.session_state:
        st.session_state.month = 7
    if "selected_holidays" not in st.session_state:
        st.session_state.selected_holidays = set()
    if "date_override_rows" not in st.session_state:
        st.session_state.date_override_rows = []
    if "date_overrides" not in st.session_state:
        st.session_state.date_overrides = {}


def reset_defaults(ward_id: str) -> None:
    clear_state(ward_id)
    st.session_state.pop("_last_saved_state", None)
    weekday, weekend = ward_templates()
    st.session_state.nurses = []
    st.session_state.assistants = []
    st.session_state.weekday_template = weekday
    st.session_state.weekend_template = weekend
    st.session_state.schedule_result = None
    st.session_state.validation_report = None
    st.session_state.duty_requests = []
    st.session_state.year = 2026
    st.session_state.month = 7
    st.session_state.selected_holidays = set()
    st.session_state.holiday_month_key = None
    st.session_state.date_override_rows = []
    st.session_state.date_overrides = {}


def clone_nurse(nurse: Nurse, **changes) -> Nurse:
    return replace(nurse, **changes)


def shift_requirement_from_row(row) -> ShiftRequirement:
    target = int(row["목표"])
    return ShiftRequirement(
        minimum=int(row["하한"]),
        maximum=int(row.get("상한", target)),
        target=target,
    )


def level_label(nurse: Nurse) -> str:
    return LEVEL_LABELS.get(nurse.level, "액팅만")


def allowed_shifts_label(nurse: Nurse) -> str:
    allowed = nurse.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
    return ",".join(s.value for s in (ShiftType.D, ShiftType.E, ShiftType.N) if s in allowed)


def parse_allowed_shifts(value: object) -> set[ShiftType]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return {ShiftType.D, ShiftType.E, ShiftType.N}
    raw = str(value).replace(" ", "").upper()
    if not raw:
        return {ShiftType.D, ShiftType.E, ShiftType.N}
    result: set[ShiftType] = set()
    tokens = list(raw) if "," not in raw and "/" not in raw else raw.replace("/", ",").split(",")
    for token in tokens:
        if not token:
            continue
        result.add(ShiftType(token))
    return result


def parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    raw = str(value).strip()
    if not raw or raw.lower() in ("nan", "none"):
        return None
    return int(float(raw))
