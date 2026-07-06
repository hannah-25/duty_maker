from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.models import ShiftType, month_dates


WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
HOLIDAY_STYLE = "background-color: rgba(255,132,58,0.8);"
REQUEST_HONORED_STYLE = "color: #1D4ED8; font-weight: 800;"
IGNORED_REQUEST_STYLE = "color: #94A3B8; text-decoration: line-through;"
DECISION_LABELS = {
    "강제반영": "force",
    "미반영": "ignore",
}
DECISION_TO_LABEL = {decision: label for label, decision in DECISION_LABELS.items()}


def _day_columns(year: int, month: int) -> tuple[list[date], list[str], dict[date, str]]:
    days = month_dates(year, month)
    columns = [f"{d.month}/{d.day}({WEEKDAY_KR[d.weekday()]})" for d in days]
    return days, columns, dict(zip(days, columns))


def schedule_dataframe(nurses, year: int, month: int, assignments) -> pd.DataFrame:
    days, columns, _ = _day_columns(year, month)
    return pd.DataFrame(
        [[assignments[(nurse.name, day)].value for day in days] for nurse in nurses],
        index=[nurse.name for nurse in nurses],
        columns=columns,
    )


def _request_label(req) -> str:
    kind = "제외" if getattr(req, "kind", "prefer") == "avoid" else "희망"
    shift = "오프" if req.requested_shift in (ShiftType.O, ShiftType.AL) else req.requested_shift.value
    return f"{kind} {shift}"


def _highlight_request_cells(result, day_to_column: dict[date, str]) -> set[tuple[str, str]]:
    cells: set[tuple[str, str]] = set()
    for req in result.honored_duty_requests:
        is_off_prefer = getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (ShiftType.O, ShiftType.AL)
        is_avoid = getattr(req, "kind", "prefer") == "avoid"
        if not (is_off_prefer or is_avoid):
            continue
        column = day_to_column.get(req.day)
        if column is not None:
            cells.add((req.nurse_name, column))
    return cells


def _style_schedule(
    df: pd.DataFrame,
    day_columns: list[str],
    holiday_columns: set[str],
    request_cells: set[tuple[str, str]],
):
    def style_cell(row_name: str, column_name: str) -> str:
        if column_name not in day_columns:
            return ""
        styles: list[str] = []
        if column_name in holiday_columns:
            styles.append(HOLIDAY_STYLE)
        if (row_name, column_name) in request_cells:
            styles.append(REQUEST_HONORED_STYLE)
        return " ".join(styles)

    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for row_name in df.index:
        for column_name in df.columns:
            styles.loc[row_name, column_name] = style_cell(row_name, column_name)
    return df.style.apply(lambda _: styles, axis=None)


def _request_rows(requests) -> list[dict[str, str]]:
    return [
        {
            "이름": req.nurse_name,
            "날짜": req.day.isoformat(),
            "유형&신청": _request_label(req),
        }
        for req in requests
    ]


def _request_decision_editor(result) -> None:
    requests = list(st.session_state.get("duty_requests", []))
    if not requests:
        return

    honored_keys = {
        (req.nurse_name, req.day, getattr(req, "kind", "prefer"), req.requested_shift)
        for req in result.honored_duty_requests
    }
    dropped_keys = {
        (req.nurse_name, req.day, getattr(req, "kind", "prefer"), req.requested_shift)
        for req in result.dropped_duty_requests
    }
    rows = []
    for req in requests:
        key = (req.nurse_name, req.day, getattr(req, "kind", "prefer"), req.requested_shift)
        is_ignored = getattr(req, "decision", "force") == "ignore"
        rows.append(
            {
                "이름": req.nurse_name,
                "날짜": req.day.isoformat(),
                "유형&신청": _request_label(req),
                "반영 여부": DECISION_TO_LABEL.get(getattr(req, "decision", "force"), "강제반영"),
                "_미반영": is_ignored,
            }
        )

    st.subheader("듀티 신청 반영 조정")
    display_df = pd.DataFrame(rows)
    style_flags = display_df.pop("_미반영")
    edited = st.data_editor(
        display_df.style.apply(
            lambda _: pd.DataFrame(
                [
                    [IGNORED_REQUEST_STYLE if ignored else "" for _ in display_df.columns]
                    for ignored in style_flags
                ],
                index=display_df.index,
                columns=display_df.columns,
            ),
            axis=None,
        ),
        key="result_request_decision_editor_v1",
        use_container_width=True,
        hide_index=True,
        disabled=["이름", "날짜", "유형&신청"],
        column_config={
            "반영 여부": st.column_config.SelectboxColumn(
                options=list(DECISION_LABELS.keys()),
                required=True,
            ),
        },
    )
    for req, (_, row) in zip(requests, edited.iterrows()):
        req.decision = DECISION_LABELS.get(str(row.get("반영 여부", "강제반영")), "force")
    st.session_state.duty_requests = requests


def render_schedule_view(year: int, month: int, holidays: set[date]) -> None:
    result = st.session_state.schedule_result
    report = st.session_state.validation_report
    if result is None:
        st.info("근무표를 생성하면 결과가 여기에 표시됩니다.")
        return

    if not result.feasible:
        st.error("실행 가능한 근무표를 찾지 못했습니다.")
        st.write(result.infeasible_categories)
        _request_decision_editor(result)
        return

    nurses = st.session_state.nurses
    days, day_columns, day_to_column = _day_columns(year, month)
    df = schedule_dataframe(nurses, year, month, result.assignments)
    if report is not None and "개인별" in report.stats:
        per_nurse = report.stats["개인별"]
        for label in ("근무", "N", "O", "연차", "오프편차"):
            df[label] = [per_nurse[nurse.name][label] for nurse in nurses]

    st.subheader("생성 결과")
    request_cells = _highlight_request_cells(result, day_to_column)
    holiday_columns = {
        day_to_column[day]
        for day in days
        if day.weekday() >= 5 or day in holidays
    }
    st.dataframe(
        _style_schedule(df, day_columns, holiday_columns, request_cells),
        use_container_width=True,
    )

    ignored_requests = [
        req for req in st.session_state.get("duty_requests", []) if getattr(req, "decision", "force") == "ignore"
    ]
    unreflected_count = len(result.dropped_duty_requests) + len(ignored_requests)
    dropped_off_requests = [
        req
        for req in [*result.dropped_duty_requests, *ignored_requests]
        if getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (ShiftType.O, ShiftType.AL)
    ]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("공휴일", len(holidays))
    col2.metric("목적값", f"{result.objective_value:.0f}" if result.objective_value is not None else "-")
    col3.metric("전체 신청", len(st.session_state.get("duty_requests", [])))
    col4.metric("반영 신청", len(result.honored_duty_requests))
    col5.metric("미반영 신청", unreflected_count, f"오프 {len(dropped_off_requests)}")

    if report is not None:
        if report.ok:
            st.success("검증 통과")
        else:
            st.error("검증 실패")
            st.write(report.violations)

    _request_decision_editor(result)

    if result.honored_duty_requests:
        with st.expander("반영된 듀티 신청"):
            st.write(_request_rows(result.honored_duty_requests))

    if result.dropped_duty_requests:
        with st.expander("반영하지 못한 듀티 신청"):
            st.write(_request_rows(result.dropped_duty_requests))
