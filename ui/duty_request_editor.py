from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.models import DutyRequest, ShiftType, month_dates


REQUEST_SHIFT_LABELS = {
    "오프": ShiftType.O,
    "D": ShiftType.D,
    "E": ShiftType.E,
    "N": ShiftType.N,
}
SHIFT_TO_LABEL = {shift: label for label, shift in REQUEST_SHIFT_LABELS.items()}


def _date_label(day: date) -> str:
    return day.isoformat()


def _request_frame(requests: list[DutyRequest]) -> pd.DataFrame:
    rows = [
        {
            "이름": req.nurse_name,
            "날짜": _date_label(req.day),
            "신청": SHIFT_TO_LABEL.get(req.requested_shift, req.requested_shift.value),
            "우선순위": req.priority,
            "메모": req.memo,
        }
        for req in requests
    ]
    return pd.DataFrame(rows, columns=["이름", "날짜", "신청", "우선순위", "메모"])


def render_duty_request_editor(year: int, month: int) -> list[DutyRequest]:
    st.subheader("듀티 신청")
    if "duty_requests" not in st.session_state:
        st.session_state.duty_requests = []

    days = month_dates(year, month)
    date_options = [_date_label(day) for day in days]
    nurse_names = [nurse.name for nurse in st.session_state.nurses]
    edited = st.data_editor(
        _request_frame(st.session_state.duty_requests),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "이름": st.column_config.SelectboxColumn(options=nurse_names, required=True),
            "날짜": st.column_config.SelectboxColumn(options=date_options, required=True),
            "신청": st.column_config.SelectboxColumn(
                options=list(REQUEST_SHIFT_LABELS.keys()),
                required=True,
            ),
            "우선순위": st.column_config.NumberColumn(
                min_value=1,
                max_value=5,
                step=1,
                required=True,
            ),
            "메모": st.column_config.TextColumn(required=False),
        },
    )

    requests: list[DutyRequest] = []
    valid_dates = {day.isoformat(): day for day in days}
    for _, row in edited.iterrows():
        nurse_name = str(row.get("이름", "")).strip()
        day = valid_dates.get(str(row.get("날짜", "")).strip())
        requested_shift = REQUEST_SHIFT_LABELS.get(str(row.get("신청", "")).strip())
        if not nurse_name or day is None or requested_shift is None:
            continue
        requests.append(
            DutyRequest(
                nurse_name=nurse_name,
                day=day,
                requested_shift=requested_shift,
                priority=int(row.get("우선순위", 1) or 1),
                memo=str(row.get("메모", "") or ""),
            )
        )

    st.session_state.duty_requests = requests
    return requests
