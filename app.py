from __future__ import annotations

import streamlit as st

from core.models import build_month_requirements, month_dates
from core.solver import generate_schedule
from core.validator import validate_schedule
from ui.duty_request_editor import render_duty_request_editor
from ui.nurse_editor import render_nurse_editor
from ui.requirement_editor import render_requirement_editor
from ui.schedule_view import render_schedule_view
from ui.state import init_state


st.set_page_config(page_title="Duty Maker", layout="wide")
init_state()

st.title("Duty Maker")

tabs = st.tabs(["명단", "인원 기준", "듀티 신청", "결과"])

with tabs[0]:
    nurses = render_nurse_editor()

with tabs[1]:
    year, month, weekday_template, weekend_template, holidays, date_overrides = render_requirement_editor()

with tabs[2]:
    duty_requests = render_duty_request_editor(int(st.session_state.year), int(st.session_state.month))

year = int(st.session_state.year)
month = int(st.session_state.month)
holidays = set(holidays)
weekend_count = sum(1 for day in month_dates(year, month) if day.weekday() >= 5)
off_target_value = weekend_count + len(holidays)
nurses_for_generation = st.session_state.get("nurses", [])
off_target = {nurse.name: off_target_value for nurse in nurses_for_generation}
requirements = build_month_requirements(
    year,
    month,
    st.session_state.weekday_template,
    st.session_state.weekend_template,
    st.session_state.get("date_overrides", {}),
)

generate_col, info_col = st.columns([1, 3])
with generate_col:
    generate = st.button("근무표 생성", type="primary", use_container_width=True)
with info_col:
    st.caption(f"목표 오프일수: {off_target_value}일 (주말 {weekend_count}일 + 반영 공휴일 {len(holidays)}일)")

if generate:
    with st.spinner("근무표 생성 중"):
        result = generate_schedule(
            st.session_state.nurses,
            year,
            month,
            requirements,
            off_target,
            duty_requests=st.session_state.get("duty_requests", []),
            time_limit_seconds=60.0,
        )
        st.session_state.schedule_result = result
        if result.feasible:
            st.session_state.validation_report = validate_schedule(
                st.session_state.nurses,
                year,
                month,
                result.assignments,
                requirements,
                off_target,
            )
        else:
            st.session_state.validation_report = None

with tabs[3]:
    render_schedule_view(year, month, holidays)
