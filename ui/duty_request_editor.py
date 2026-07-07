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
DECISION_LABELS = {
    "강제반영": "force",
    "미반영": "ignore",
}
DECISION_TO_LABEL = {decision: label for label, decision in DECISION_LABELS.items()}


def _date_label(day: date) -> str:
    return day.isoformat()


def _request_frame(requests: list[DutyRequest], include_delete: bool = False) -> pd.DataFrame:
    rows = [
        {
            "선택": False,
            "이름": req.nurse_name,
            "날짜": _date_label(req.day),
            "유형&신청": f"{KIND_TO_LABEL.get(getattr(req, 'kind', 'prefer'), '희망')} {SHIFT_TO_LABEL.get(req.requested_shift, req.requested_shift.value)}",
            "반영 여부": DECISION_TO_LABEL.get(getattr(req, "decision", "force"), "강제반영"),
        }
        for req in requests
    ]
    columns = ["선택", "이름", "날짜", "유형&신청", "반영 여부"] if include_delete else ["이름", "날짜", "유형&신청", "반영 여부"]
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


def render_duty_request_editor(
    year: int,
    month: int,
    restrict_to: str | None = None,
    locked: bool = False,
) -> list[DutyRequest]:
    """듀티 신청 편집기.

    restrict_to: 지정하면 그 사람 본인 신청만 등록/삭제 가능 (일반 사용자 모드).
    locked: 신청 마감 — 등록/삭제 불가, 목록만 표시.
    """
    st.subheader("듀티 신청")
    if "nurses" not in st.session_state:
        st.session_state.nurses = build_real_nurses()
    if "duty_requests" not in st.session_state:
        st.session_state.duty_requests = []

    days = month_dates(year, month)
    date_options = [_date_label(day) for day in days]
    valid_dates = {day.isoformat(): day for day in days}
    nurses = st.session_state.get("nurses", [])
    assistants = st.session_state.get("assistants", [])
    # 보조 인력도 간호사와 동일하게 희망/제외 신청 가능 (표시 용도)
    nurse_names = [nurse.name for nurse in nurses] + [a.name for a in assistants]

    if not nurse_names:
        st.info("간호사 명단을 먼저 입력하세요.")
        return []

    if locked:
        st.warning("신청이 마감되었습니다. 등록·삭제는 관리자에게 문의하세요.")

    if not locked:
        if restrict_to is None:
            col1, col2, col3, col4, col5 = st.columns([1.2, 1.2, 0.8, 0.8, 0.8])
            with col1:
                nurse_name = st.selectbox("이름", nurse_names, key="duty_request_name")
        else:
            nurse_name = restrict_to
            col2, col3, col4, col5 = st.columns([1.4, 0.9, 0.9, 0.9])
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
                        decision="force",
                    ),
                ]
            )
            st.rerun()

    requests: list[DutyRequest] = st.session_state.get("duty_requests", [])
    visible = (
        requests
        if restrict_to is None
        else [req for req in requests if req.nurse_name == restrict_to]
    )
    st.caption(f"현재 신청 {len(visible)}건")

    if visible and restrict_to is None:
        # 관리자: 반영 여부 조정 + 삭제
        editable = not locked
        edited = st.data_editor(
            _request_frame(visible, include_delete=editable),
            key="duty_request_list_v1",
            use_container_width=True,
            hide_index=True,
            disabled=["이름", "날짜", "유형&신청"] + ([] if editable else ["선택", "반영 여부"]),
            column_config={
                "선택": st.column_config.CheckboxColumn(required=True),
                "반영 여부": st.column_config.SelectboxColumn(
                    options=list(DECISION_LABELS.keys()),
                    required=True,
                ),
            },
        )
        if editable:
            for req, (_, row) in zip(visible, edited.iterrows()):
                req.decision = DECISION_LABELS.get(str(row.get("반영 여부", "강제반영")), "force")
            st.session_state.duty_requests = requests
            if st.button("선택 삭제", use_container_width=True):
                selected = {
                    id(req)
                    for req, (_, row) in zip(visible, edited.iterrows())
                    if bool(row.get("선택", False))
                }
                st.session_state.duty_requests = [req for req in requests if id(req) not in selected]
                st.rerun()
    elif visible:
        # 일반 사용자: 본인 신청 목록 + 삭제 (반영 여부는 관리자 영역이라 숨김)
        for idx, req in enumerate(visible):
            col_info, col_del = st.columns([4, 1])
            kind = KIND_TO_LABEL.get(getattr(req, "kind", "prefer"), "희망")
            shift = SHIFT_TO_LABEL.get(req.requested_shift, req.requested_shift.value)
            col_info.write(f"{req.day.isoformat()} — {kind} {shift}")
            if not locked and col_del.button("삭제", key=f"own_request_delete_{idx}"):
                st.session_state.duty_requests = [r for r in requests if r is not req]
                st.rerun()
    return st.session_state.get("duty_requests", [])
