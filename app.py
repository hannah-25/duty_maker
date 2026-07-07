from __future__ import annotations

from datetime import date

import streamlit as st

from core.models import DayRequirement, ShiftRequirement, build_month_requirements, month_dates
from core.persistence import is_remote_backend, reload_duty_requests, save_state
from core.solver import generate_schedule
from core.validator import validate_schedule
from ui.duty_request_editor import render_duty_request_editor
from ui.login import render_account_admin, require_login
from ui.nurse_editor import render_nurse_editor
from ui.requirement_editor import render_requirement_editor
from ui.schedule_view import render_schedule_view
from ui.state import init_state
from ui.style import apply_custom_style


def _selected_holidays_as_dates() -> set[date]:
    result = set()
    for raw in st.session_state.get("selected_holidays", set()):
        try:
            result.add(date.fromisoformat(str(raw)))
        except ValueError:
            continue
    return result


def _overrides_from_rows() -> dict[date, DayRequirement]:
    """저장된 특정일 인원 기준 행을 DayRequirement로 변환 (편집기 미방문 세션용)."""
    overrides: dict[date, DayRequirement] = {}
    for row in st.session_state.get("date_override_rows", []):
        try:
            day = date.fromisoformat(str(row["날짜"]))
            d_count, e_count, n_count = int(row["D"]), int(row["E"]), int(row["N"])
        except Exception:
            continue
        overrides[day] = DayRequirement(
            day=day,
            D=ShiftRequirement(d_count, d_count, d_count),
            E=ShiftRequirement(e_count, e_count, e_count),
            N=ShiftRequirement(n_count, n_count, n_count),
        )
    return overrides


def _ensure_validation_report(year: int, month: int, holidays: set[date]) -> None:
    """복원된 결과에 검증 리포트가 없으면 다시 계산한다 (요약 컬럼/체크리스트용)."""
    result = st.session_state.get("schedule_result")
    if result is None or not result.feasible or st.session_state.get("validation_report") is not None:
        return
    nurses = st.session_state.get("nurses", [])
    days = month_dates(year, month)
    if not nurses or any((n.name, d) not in result.assignments for n in nurses for d in days):
        return
    weekend_count = sum(1 for d in days if d.weekday() >= 5)
    off_target = {n.name: weekend_count + len(holidays) for n in nurses}
    requirements = build_month_requirements(
        year,
        month,
        st.session_state.weekday_template,
        st.session_state.weekend_template,
        st.session_state.get("date_overrides") or _overrides_from_rows(),
    )
    st.session_state.validation_report = validate_schedule(
        nurses, year, month, result.assignments, requirements, off_target
    )


def _render_publish_controls() -> None:
    result = st.session_state.get("schedule_result")
    if result is None or not result.feasible:
        return
    published = bool(st.session_state.get("result_published", False))
    col_status, col_btn = st.columns([3, 1])
    if published:
        col_status.success("확정됨 — 일반 사용자에게 공개 중입니다. 다시 생성하면 자동으로 비공개됩니다.")
        if col_btn.button("공개 취소", use_container_width=True):
            st.session_state.result_published = False
            st.rerun()
    else:
        col_status.info("확정 전 — 일반 사용자에게는 보이지 않습니다.")
        if col_btn.button("근무표 확정", type="primary", use_container_width=True):
            st.session_state.result_published = True
            st.rerun()


def _render_admin() -> None:
    tabs = st.tabs(["명단", "인원 기준", "듀티 신청", "결과", "계정"])

    with tabs[0]:
        render_nurse_editor()

    with tabs[1]:
        year, month, weekday_template, weekend_template, holidays, date_overrides = render_requirement_editor()

    with tabs[2]:
        col_lock, col_reload = st.columns([1, 1])
        with col_lock:
            locked = st.toggle(
                "신청 마감",
                value=bool(st.session_state.get("requests_locked", False)),
                key="requests_locked_toggle",
                help="마감하면 일반 사용자는 신청을 등록/삭제할 수 없습니다.",
            )
            st.session_state.requests_locked = locked
        with col_reload:
            if is_remote_backend() and st.button("신청 새로 불러오기", use_container_width=True):
                reload_duty_requests(st.session_state)
                st.rerun()
        render_duty_request_editor(int(st.session_state.year), int(st.session_state.month))

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

    solver_nurse_names = {nurse.name for nurse in nurses_for_generation}
    solver_duty_requests = [
        req
        for req in st.session_state.get("duty_requests", [])
        if req.nurse_name in solver_nurse_names
    ]

    if generate:
        with st.spinner("근무표 생성 중"):
            result = generate_schedule(
                st.session_state.nurses,
                year,
                month,
                requirements,
                off_target,
                duty_requests=solver_duty_requests,
                time_limit_seconds=60.0,
            )
            st.session_state.schedule_result = result
            st.session_state.result_published = False  # 재생성하면 확정 전 상태로
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

    _ensure_validation_report(year, month, holidays)

    with tabs[3]:
        _render_publish_controls()
        render_schedule_view(year, month, holidays)

    with tabs[4]:
        render_account_admin()


def _render_member(user: dict) -> None:
    year = int(st.session_state.get("year", 2026))
    month = int(st.session_state.get("month", 7))
    holidays = {d for d in _selected_holidays_as_dates() if d.year == year and d.month == month}

    tabs = st.tabs(["듀티 신청", "근무표"])
    with tabs[0]:
        render_duty_request_editor(
            year,
            month,
            restrict_to=user["name"],
            locked=bool(st.session_state.get("requests_locked", False)),
        )
    with tabs[1]:
        if st.session_state.get("result_published"):
            _ensure_validation_report(year, month, holidays)
            render_schedule_view(year, month, holidays, read_only=True)
        else:
            st.info("아직 확정된 근무표가 없습니다.")


st.set_page_config(page_title="Duty Maker", layout="wide")
apply_custom_style()
init_state()
user = require_login()

st.title("Duty Maker")

if user.get("is_admin"):
    _render_admin()
else:
    _render_member(user)

save_state(st.session_state, requests_only=not user.get("is_admin"))
