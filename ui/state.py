from __future__ import annotations

from dataclasses import replace

import streamlit as st

from core.models import Nurse, NurseLevel, ShiftRequirement, ShiftType
from core.sample_data import build_real_nurses, ward_templates


LEVEL_LABELS = {
    NurseLevel.SENIOR_CHARGE: "고연차",
    NurseLevel.MIDDLE: "중간연차",
    NurseLevel.JUNIOR: "저연차",
    NurseLevel.NEW_JUNIOR: "완전 저연차",
}
LABEL_TO_LEVEL = {label: level for level, label in LEVEL_LABELS.items()}


def init_state() -> None:
    if "nurses" not in st.session_state:
        st.session_state.nurses = build_real_nurses()
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


def reset_defaults() -> None:
    weekday, weekend = ward_templates()
    st.session_state.nurses = build_real_nurses()
    st.session_state.weekday_template = weekday
    st.session_state.weekend_template = weekend
    st.session_state.schedule_result = None
    st.session_state.validation_report = None
    st.session_state.duty_requests = []


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
    return LEVEL_LABELS.get(nurse.level, "저연차")


def allowed_shifts_label(nurse: Nurse) -> str:
    allowed = nurse.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
    return ",".join(s.value for s in (ShiftType.D, ShiftType.E, ShiftType.N) if s in allowed)


def parse_allowed_shifts(value: object) -> set[ShiftType]:
    if value is None:
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
    raw = str(value).strip()
    if not raw:
        return None
    return int(raw)
