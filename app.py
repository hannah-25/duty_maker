from __future__ import annotations

import streamlit as st

from core.holidays_kr import get_month_holidays
from core.models import build_month_requirements, month_dates
from core.solver import generate_schedule
from core.validator import validate_schedule
from ui.nurse_editor import render_nurse_editor
from ui.requirement_editor import render_requirement_editor
from ui.schedule_view import render_schedule_view
from ui.state import init_state, reset_defaults


st.set_page_config(page_title="Duty Maker", layout="wide")
init_state()

st.title("Duty Maker")

with st.sidebar:
    year = st.number_input("연도", min_value=2026, max_value=2035, value=2026, step=1)
    month = st.number_input("월", min_value=1, max_value=12, value=7, step=1)
    holidays = get_month_holidays(int(year), int(month))
    holiday_count = st.number_input(
        "공휴일 수",
        min_value=0,
        max_value=31,
        value=len(holidays),
        step=1,
    )
    time_limit = st.slider("탐색 시간(초)", min_value=10, max_value=120, value=60, step=10)
    if st.button("기본값 복원", use_container_width=True):
        reset_defaults()
        st.rerun()

tabs = st.tabs(["명단", "인원 기준", "결과"])

with tabs[0]:
    nurses = render_nurse_editor()

with tabs[1]:
    weekday_template, weekend_template = render_requirement_editor()

weekend_count = sum(1 for day in month_dates(int(year), int(month)) if day.weekday() >= 5)
off_target_value = weekend_count + int(holiday_count)
off_target = {nurse.name: off_target_value for nurse in st.session_state.nurses}
requirements = build_month_requirements(
    int(year),
    int(month),
    st.session_state.weekday_template,
    st.session_state.weekend_template,
)

generate_col, info_col = st.columns([1, 3])
with generate_col:
    generate = st.button("근무표 생성", type="primary", use_container_width=True)
with info_col:
    st.caption(
        f"목표 오프일수: {off_target_value}일 "
        f"(주말 {weekend_count}일 + 공휴일 입력 {int(holiday_count)}일, 자동 감지 {len(holidays)}일)"
    )

if generate:
    with st.spinner("근무표 생성 중"):
        result = generate_schedule(
            st.session_state.nurses,
            int(year),
            int(month),
            requirements,
            off_target,
            time_limit_seconds=float(time_limit),
        )
        st.session_state.schedule_result = result
        if result.feasible:
            st.session_state.validation_report = validate_schedule(
                st.session_state.nurses,
                int(year),
                int(month),
                result.assignments,
                requirements,
                off_target,
            )
        else:
            st.session_state.validation_report = None

with tabs[2]:
    render_schedule_view(int(year), int(month), holidays)
