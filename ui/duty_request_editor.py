from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.models import DutyRequest, ShiftType, month_dates
from core.sample_data import build_real_nurses


REQUEST_SHIFT_LABELS = {
    "오프": ShiftType.O,
    "D": ShiftType.D,
    "E": ShiftType.E,
    "N": ShiftType.N,
}
SHIFT_TO_LABEL = {shift: label for label, shift in REQUEST_SHIFT_LABELS.items()}
REQUEST_KIND_LABELS = {
    "희망": "prefer",
    "제외": "avoid",
}
KIND_TO_LABEL = {kind: label for label, kind in REQUEST_KIND_LABELS.items()}


def _date_label(day: date) -> str:
    return day.isoformat()


def _request_frame(requests: list[DutyRequest], include_delete: bool = False) -> pd.DataFrame:
    rows = [
        {
            "삭제": False,
            "이름": req.nurse_name,
            "날짜": _date_label(req.day),
            "유형": KIND_TO_LABEL.get(getattr(req, "kind", "prefer"), "희망"),
            "신청": SHIFT_TO_LABEL.get(req.requested_shift, req.requested_shift.value),
        }
        for req in requests
    ]
    columns = ["삭제", "이름", "날짜", "유형", "신청"] if include_delete else ["이름", "날짜", "유형", "신청"]
    return pd.DataFrame(rows, columns=columns)


def _dedupe_requests(requests: list[DutyRequest]) -> list[DutyRequest]:
    seen: set[tuple[str, date, str, ShiftType]] = set()
    result: list[DutyRequest] = []
    for req in requests:
        key = (req.nurse_name, req.day, getattr(req, "kind", "prefer"), req.requested_shift)
        if key in seen:
            continue
        seen.add(key)
        result.append(req)
    return result


def render_duty_request_editor(year: int, month: int) -> list[DutyRequest]:
    st.subheader("듀티 신청")
    if "nurses" not in st.session_state:
        st.session_state.nurses = build_real_nurses()
    if "duty_requests" not in st.session_state:
        st.session_state.duty_requests = []

    days = month_dates(year, month)
    date_options = [_date_label(day) for day in days]
    valid_dates = {day.isoformat(): day for day in days}
    nurses = st.session_state.get("nurses", [])
    nurse_names = [nurse.name for nurse in nurses]

    if not nurse_names:
        st.info("간호사 명단을 먼저 입력하세요.")
        return []

    col1, col2, col3, col4, col5 = st.columns([1.2, 1.2, 0.8, 0.8, 0.8])
    with col1:
        nurse_name = st.selectbox("이름", nurse_names, key="duty_request_name")
    with col2:
        selected_date = st.selectbox("날짜", date_options, key="duty_request_date")
    with col3:
        kind_label = st.selectbox("유형", list(REQUEST_KIND_LABELS.keys()), key="duty_request_kind")
    with col4:
        shift_label = st.selectbox("신청", list(REQUEST_SHIFT_LABELS.keys()), key="duty_request_shift")
    with col5:
        st.write("")
        st.write("")
        add_clicked = st.button("추가", type="primary", use_container_width=True)

    if add_clicked:
        st.session_state.duty_requests = _dedupe_requests(
            [
                *st.session_state.get("duty_requests", []),
                DutyRequest(
                    nurse_name=nurse_name,
                    day=valid_dates[selected_date],
                    requested_shift=REQUEST_SHIFT_LABELS[shift_label],
                    kind=REQUEST_KIND_LABELS[kind_label],
                ),
            ]
        )
        st.rerun()

    requests: list[DutyRequest] = st.session_state.get("duty_requests", [])
    st.caption(f"현재 신청 {len(requests)}건")

    if requests:
        edited = st.data_editor(
            _request_frame(requests, include_delete=True),
            key="duty_request_list_v1",
            use_container_width=True,
            hide_index=True,
            disabled=["이름", "날짜", "유형", "신청"],
            column_config={
                "삭제": st.column_config.CheckboxColumn(required=True),
            },
        )
        if st.button("선택 삭제", use_container_width=True):
            keep = [
                req
                for req, (_, row) in zip(requests, edited.iterrows())
                if not bool(row.get("삭제", False))
            ]
            st.session_state.duty_requests = keep
            st.rerun()
    return st.session_state.get("duty_requests", [])
