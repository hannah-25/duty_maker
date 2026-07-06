from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.holidays_kr import get_month_holiday_items
from core.models import DayRequirement, ShiftRequirement, month_dates
from ui.state import shift_requirement_from_row


def _template_frame(template: tuple[ShiftRequirement, ShiftRequirement, ShiftRequirement]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"근무": "D", "하한": template[0].minimum, "목표": template[0].target},
            {"근무": "E", "하한": template[1].minimum, "목표": template[1].target},
            {"근무": "N", "하한": template[2].minimum, "목표": template[2].target},
        ]
    )


def _edit_template(label: str, key: str, template):
    st.caption(label)
    edited = st.data_editor(
        _template_frame(template),
        key=key,
        hide_index=True,
        use_container_width=True,
        disabled=["근무"],
    )
    return tuple(shift_requirement_from_row(row) for _, row in edited.iterrows())


def _holiday_editor(year: int, month: int) -> set[date]:
    items = get_month_holiday_items(year, month)
    month_key = f"{year}-{month:02d}"
    if st.session_state.get("holiday_month_key") != month_key:
        st.session_state.holiday_month_key = month_key
        st.session_state.selected_holidays = {d.isoformat() for d, _ in items}
        st.session_state.date_override_rows = []
        st.session_state.date_overrides = {}

    selected = set(st.session_state.get("selected_holidays", set()))
    rows = [
        {"반영": d.isoformat() in selected, "날짜": d.isoformat(), "제목": title}
        for d, title in items
    ]
    st.caption("공휴일")
    edited = st.data_editor(
        pd.DataFrame(rows, columns=["반영", "날짜", "제목"]),
        key=f"holiday_editor_{month_key}",
        hide_index=True,
        use_container_width=True,
        disabled=["날짜", "제목"],
        column_config={"반영": st.column_config.CheckboxColumn(required=True)},
    )
    selected_dates = {date.fromisoformat(str(row["날짜"])) for _, row in edited.iterrows() if bool(row["반영"])}
    st.session_state.selected_holidays = {d.isoformat() for d in selected_dates}
    return selected_dates


def _override_frame(rows: list[dict] | None, year: int, month: int) -> pd.DataFrame:
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(
        [],
        columns=["날짜", "D하한", "D목표", "E하한", "E목표", "N하한", "N목표"],
    )


def _date_overrides_editor(year: int, month: int) -> dict[date, DayRequirement]:
    st.caption("특정일 인원 기준")
    date_options = [d.isoformat() for d in month_dates(year, month)]
    edited = st.data_editor(
        _override_frame(st.session_state.get("date_override_rows"), year, month),
        key=f"date_override_editor_{year}_{month}",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        column_config={
            "날짜": st.column_config.SelectboxColumn(options=date_options, required=True),
            "D하한": st.column_config.NumberColumn(min_value=0, step=1),
            "D목표": st.column_config.NumberColumn(min_value=0, step=1),
            "E하한": st.column_config.NumberColumn(min_value=0, step=1),
            "E목표": st.column_config.NumberColumn(min_value=0, step=1),
            "N하한": st.column_config.NumberColumn(min_value=0, step=1),
            "N목표": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )

    overrides: dict[date, DayRequirement] = {}
    rows_for_state: list[dict] = []
    for _, row in edited.iterrows():
        day_raw = str(row.get("날짜", "")).strip()
        if not day_raw:
            continue
        try:
            day = date.fromisoformat(day_raw)
            d_min, d_target = int(row["D하한"]), int(row["D목표"])
            e_min, e_target = int(row["E하한"]), int(row["E목표"])
            n_min, n_target = int(row["N하한"]), int(row["N목표"])
        except Exception:
            continue
        overrides[day] = DayRequirement(
            day=day,
            D=ShiftRequirement(d_min, d_target, d_target),
            E=ShiftRequirement(e_min, e_target, e_target),
            N=ShiftRequirement(n_min, n_target, n_target),
        )
        rows_for_state.append(
            {
                "날짜": day.isoformat(),
                "D하한": d_min,
                "D목표": d_target,
                "E하한": e_min,
                "E목표": e_target,
                "N하한": n_min,
                "N목표": n_target,
            }
        )
    st.session_state.date_override_rows = rows_for_state
    return overrides


def render_requirement_editor():
    st.subheader("인원 기준")
    col_year, col_month, col_reset = st.columns([1, 1, 1])
    with col_year:
        year = int(st.number_input("연도", min_value=2026, max_value=2035, value=int(st.session_state.get("year", 2026)), step=1))
    with col_month:
        month = int(st.number_input("월", min_value=1, max_value=12, value=int(st.session_state.get("month", 7)), step=1))
    with col_reset:
        st.write("")
        st.write("")
        if st.button("기본값 복원", use_container_width=True):
            from ui.state import reset_defaults

            reset_defaults()
            st.rerun()

    st.session_state.year = year
    st.session_state.month = month

    selected_holidays = _holiday_editor(year, month)

    col1, col2 = st.columns(2)
    with col1:
        weekday = _edit_template("평일", "weekday_template_editor", st.session_state.weekday_template)
    with col2:
        weekend = _edit_template("주말", "weekend_template_editor", st.session_state.weekend_template)

    overrides = _date_overrides_editor(year, month)

    st.session_state.weekday_template = weekday
    st.session_state.weekend_template = weekend
    st.session_state.date_overrides = overrides
    return year, month, weekday, weekend, selected_holidays, overrides
