from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.models import ShiftType, month_dates


WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def schedule_dataframe(nurses, year: int, month: int, assignments) -> pd.DataFrame:
    days = month_dates(year, month)
    columns = [f"{d.month}/{d.day}({WEEKDAY_KR[d.weekday()]})" for d in days]
    return pd.DataFrame(
        [[assignments[(nurse.name, day)].value for day in days] for nurse in nurses],
        index=[nurse.name for nurse in nurses],
        columns=columns,
    )


def render_schedule_view(year: int, month: int, holidays: set[date]) -> None:
    result = st.session_state.schedule_result
    report = st.session_state.validation_report
    if result is None:
        st.info("근무표를 생성하면 결과가 여기에 표시됩니다.")
        return

    if not result.feasible:
        st.error("실행 가능한 근무표를 찾지 못했습니다.")
        st.write(result.infeasible_categories)
        return

    nurses = st.session_state.nurses
    df = schedule_dataframe(nurses, year, month, result.assignments)
    if report is not None and "개인별" in report.stats:
        per_nurse = report.stats["개인별"]
        for label in ("근무", "N", "O", "연차", "오프편차"):
            df[label] = [per_nurse[nurse.name][label] for nurse in nurses]

    st.subheader("생성 결과")
    st.dataframe(df, use_container_width=True)

    dropped_off_requests = [
        req
        for req in result.dropped_duty_requests
        if getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (ShiftType.O, ShiftType.AL)
    ]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("공휴일", len(holidays))
    col2.metric("목적값", f"{result.objective_value:.0f}" if result.objective_value is not None else "-")
    col3.metric("전체 신청", len(result.honored_duty_requests) + len(result.dropped_duty_requests))
    col4.metric("반영 신청", len(result.honored_duty_requests))
    col5.metric("잘린 신청", len(result.dropped_duty_requests), f"오프 {len(dropped_off_requests)}")

    if report is not None:
        if report.ok:
            st.success("검증 통과")
        else:
            st.error("검증 실패")
            st.write(report.violations)

    with st.expander("소프트 벌점"):
        st.json(result.soft_violations)

    if result.honored_duty_requests:
        with st.expander("반영된 듀티 신청"):
            st.write(
                [
                    {
                        "이름": req.nurse_name,
                        "날짜": req.day.isoformat(),
                        "유형": "제외" if getattr(req, "kind", "prefer") == "avoid" else "희망",
                        "신청": req.requested_shift.value,
                        "우선순위": req.priority,
                        "메모": req.memo,
                    }
                    for req in result.honored_duty_requests
                ]
            )

    if result.dropped_duty_requests:
        with st.expander("반영하지 못한 듀티 신청"):
            st.write(
                [
                    {
                        "이름": req.nurse_name,
                        "날짜": req.day.isoformat(),
                        "유형": "제외" if getattr(req, "kind", "prefer") == "avoid" else "희망",
                        "신청": req.requested_shift.value,
                        "우선순위": req.priority,
                        "메모": req.memo,
                    }
                    for req in result.dropped_duty_requests
                ]
            )
