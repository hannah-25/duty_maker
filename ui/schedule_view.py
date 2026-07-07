from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.hwpx_export import TEMPLATE_PATH, export_schedule_hwpx
from core.models import ShiftType, month_dates


WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
HOLIDAY_STYLE = "background-color: #E9ECEF;"  # 주말·공휴일 열: 연한 회색
SHIFT_BG_STYLES = {  # 듀티별 파스텔 배경 (휴일 회색보다 우선)
    "D": "background-color: #FFF3C4;",
    "E": "background-color: #D6E8FF;",
    "N": "background-color: #E5D9F7;",
    "S": "background-color: #DFF5E1;",
}
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


def _request_highlight_days(result) -> set[tuple[str, date]]:
    """반영된 신청 중 파란색으로 표시할 (이름, 날짜) — 오프 희망과 제외 신청."""
    cells: set[tuple[str, date]] = set()
    for req in result.honored_duty_requests:
        is_off_prefer = getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (ShiftType.O, ShiftType.AL)
        is_avoid = getattr(req, "kind", "prefer") == "avoid"
        if is_off_prefer or is_avoid:
            cells.add((req.nurse_name, req.day))
    return cells


def _highlight_request_cells(result, day_to_column: dict[date, str]) -> set[tuple[str, str]]:
    return {
        (name, day_to_column[day])
        for name, day in _request_highlight_days(result)
        if day in day_to_column
    }


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
        shift_bg = SHIFT_BG_STYLES.get(str(df.loc[row_name, column_name]))
        if shift_bg:
            styles.append(shift_bg)
        elif column_name in holiday_columns:
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


def _assistant_request_marks(assistants) -> dict[tuple[str, date], ShiftType]:
    """보조 인력의 활성 '희망' 신청 (이름, 날짜) -> 신청 듀티. 제외 신청은 표에 표시하지 않는다."""
    names = {assistant.name for assistant in assistants}
    return {
        (req.nurse_name, req.day): req.requested_shift
        for req in st.session_state.get("duty_requests", [])
        if req.nurse_name in names
        and getattr(req, "decision", "force") != "ignore"
        and getattr(req, "kind", "prefer") == "prefer"
    }


def _render_constraint_checklist(report, result, nurse_names: set[str]) -> None:
    rows: list[dict[str, object]] = list(getattr(report, "checklist", []) or []) if report is not None else []

    forced_requests = [
        req
        for req in st.session_state.get("duty_requests", [])
        if getattr(req, "decision", "force") != "ignore" and req.nurse_name in nurse_names
    ]
    if forced_requests:
        honored = len(result.honored_duty_requests)
        dropped = len(result.dropped_duty_requests)
        rows.append(
            {
                "항목": "듀티 신청",
                "대상": "전체",
                "기준(입력)": f"강제반영 {len(forced_requests)}건",
                "실제": f"{honored}건 반영 / {dropped}건 미반영",
                "반영": dropped == 0,
            }
        )

    if not rows:
        return

    unmet = sum(1 for row in rows if not row["반영"])
    st.subheader("입력 조건 반영 현황")
    if unmet:
        st.warning(f"미반영 항목 {unmet}건 — 아래 표에서 ❌ 항목을 확인하세요.")
    else:
        st.caption("입력한 모든 제약 조건이 반영되었습니다.")
    display = pd.DataFrame(rows)
    display["반영"] = display["반영"].map(lambda ok: "✅" if ok else "❌")
    st.dataframe(display, use_container_width=True, hide_index=True)


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
    if any((nurse.name, day) not in result.assignments for nurse in nurses for day in days):
        st.info("명단이나 연월이 생성 시점과 달라졌습니다. 근무표를 다시 생성하세요.")
        _request_decision_editor(result)
        return

    assistants = st.session_state.get("assistants", [])
    assistant_marks = _assistant_request_marks(assistants)
    df = schedule_dataframe(nurses, year, month, result.assignments)
    if report is not None and "개인별" in report.stats:
        per_nurse = report.stats["개인별"]
        for label in ("근무", "N", "O", "연차", "연차목표", "오프편차"):
            df[label] = [per_nurse[nurse.name].get(label, "-") for nurse in nurses]
    if assistants:
        assistant_rows = []
        for assistant in assistants:
            row = {column: "" for column in df.columns}
            for day in days:
                mark = assistant_marks.get((assistant.name, day))
                if mark is not None:
                    row[day_to_column[day]] = "O" if mark in (ShiftType.O, ShiftType.AL) else mark.value
            assistant_rows.append(row)
        df = pd.concat(
            [df, pd.DataFrame(assistant_rows, index=[a.name for a in assistants])]
        )

    st.subheader("생성 결과")
    request_cells = _highlight_request_cells(result, day_to_column)
    request_cells |= {
        (name, day_to_column[day])
        for (name, day) in assistant_marks
        if day in day_to_column
    }
    holiday_columns = {
        day_to_column[day]
        for day in days
        if day.weekday() >= 5 or day in holidays
    }
    st.dataframe(
        _style_schedule(df, day_columns, holiday_columns, request_cells),
        use_container_width=True,
    )

    if TEMPLATE_PATH.exists():
        weekend_count = sum(1 for d in days if d.weekday() >= 5)
        try:
            hwpx_bytes = export_schedule_hwpx(
                nurses,
                year,
                month,
                result.assignments,
                holidays,
                weekend_count + len(holidays),
                _request_highlight_days(result),
                assistants=assistants,
                assistant_marks=assistant_marks,
            )
        except Exception as exc:
            st.caption(f"HWP 양식 내보내기 실패: {exc}")
        else:
            st.download_button(
                "HWP(hwpx) 다운로드",
                data=hwpx_bytes,
                file_name=f"{year}년 {month}월 근무표.hwpx",
                mime="application/octet-stream",
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
    # 보조 인력 희망 신청은 표에 그대로 표시되므로 반영으로 집계
    honored_count = len(result.honored_duty_requests) + len(assistant_marks)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("공휴일", len(holidays))
    col2.metric("목적값", f"{result.objective_value:.0f}" if result.objective_value is not None else "-")
    col3.metric("전체 신청", len(st.session_state.get("duty_requests", [])))
    col4.metric("반영 신청", honored_count)
    col5.metric("미반영 신청", unreflected_count, f"오프 {len(dropped_off_requests)}")

    if report is not None:
        if report.ok:
            st.success("검증 통과")
        else:
            st.error("검증 실패")
            st.write(report.violations)

    _render_constraint_checklist(report, result, {nurse.name for nurse in nurses})

    _request_decision_editor(result)

    if result.honored_duty_requests:
        with st.expander("반영된 듀티 신청"):
            st.write(_request_rows(result.honored_duty_requests))

    if result.dropped_duty_requests:
        with st.expander("반영하지 못한 듀티 신청"):
            st.write(_request_rows(result.dropped_duty_requests))
