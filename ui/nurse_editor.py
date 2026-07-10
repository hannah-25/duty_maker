from __future__ import annotations

from itertools import combinations

import pandas as pd
import streamlit as st

from core.models import Assistant, Nurse, ShiftType
from ui.state import (
    LABEL_TO_LEVEL,
    LEVEL_LABELS,
    allowed_shifts_label,
    level_label,
    parse_allowed_shifts,
    parse_optional_int,
)

DUTY_OPTIONS = [
    ",".join(combo)
    for r in range(1, 4)
    for combo in combinations([ShiftType.D.value, ShiftType.E.value, ShiftType.N.value], r)
]
N_HARD_OPTIONS = ["", *[str(i) for i in range(9)]]


def _request_summary_by_nurse() -> dict[str, str]:
    result: dict[str, list[str]] = {}
    for req in st.session_state.get("duty_requests", []):
        kind = "제외" if getattr(req, "kind", "prefer") == "avoid" else "희망"
        text = f"{req.day.month}/{req.day.day} {req.requested_shift.value} {kind}"
        if getattr(req, "decision", "force") == "ignore":
            text = f"~~{text} (미반영)~~"
        result.setdefault(req.nurse_name, []).append(text)
    return {name: ", ".join(items) for name, items in result.items()}


def _render_request_summary() -> None:
    requests = st.session_state.get("duty_requests", [])
    if not requests:
        return
    st.caption("신청 요약")
    rows = ["| 이름 | 신청 |", "|---|---|"]
    for req in requests:
        kind = "제외" if getattr(req, "kind", "prefer") == "avoid" else "희망"
        text = f"{req.day.month}/{req.day.day} {req.requested_shift.value} {kind}"
        if getattr(req, "decision", "force") == "ignore":
            text = f"~~{text} (미반영)~~"
        rows.append(f"| {req.nurse_name} | {text} |")
    st.markdown("\n".join(rows))


def render_nurse_editor() -> list[Nurse]:
    st.subheader("간호사 명단")

    summaries = _request_summary_by_nurse()
    rows = [
        {
            "이름": nurse.name,
            "연차 구분": level_label(nurse),
            "가능 듀티": allowed_shifts_label(nurse),
            "N 상한": str(nurse.max_n_hard),
            "N 선호연속": "" if nurse.n_soft_consecutive_limit is None else str(nurse.n_soft_consecutive_limit),
            "연차 목표": "" if nurse.al_target is None else str(nurse.al_target),
            "평일만": nurse.weekday_only,
            "신청 요약": summaries.get(nurse.name, ""),
        }
        for nurse in st.session_state.nurses
    ]

    edited = st.data_editor(
        pd.DataFrame(
            rows,
            columns=[
                "이름",
                "연차 구분",
                "가능 듀티",
                "N 상한",
                "N 선호연속",
                "연차 목표",
                "평일만",
                "신청 요약",
            ],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        disabled=["신청 요약"],
        column_config={
            "연차 구분": st.column_config.SelectboxColumn(
                options=list(LABEL_TO_LEVEL.keys()),
                required=True,
            ),
            "가능 듀티": st.column_config.SelectboxColumn(
                options=DUTY_OPTIONS,
                required=True,
            ),
            "N 상한": st.column_config.SelectboxColumn(
                help="가능 듀티에 N이 없으면 무시되고 0으로 처리됩니다",
                options=N_HARD_OPTIONS,
                required=False,
            ),
            "N 선호연속": st.column_config.SelectboxColumn(
                options=["", "2", "3"],
                required=False,
            ),
            "연차 목표": st.column_config.NumberColumn(
                min_value=0,
                max_value=31,
                step=1,
                required=False,
            ),
        },
    )

    updated: list[Nurse] = []
    for _, row in edited.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        level = LABEL_TO_LEVEL.get(row.get("연차 구분"), next(iter(LEVEL_LABELS)))
        max_n_hard = parse_optional_int(row.get("N 상한"))
        updated.append(
            Nurse(
                name=name,
                level=level,
                allowed_shifts=parse_allowed_shifts(row.get("가능 듀티", "D,E,N")),
                max_n_hard=8 if max_n_hard is None else max_n_hard,
                n_soft_consecutive_limit=parse_optional_int(row.get("N 선호연속")),
                al_target=parse_optional_int(row.get("연차 목표")),
                weekday_only=bool(row.get("평일만", False)),
            )
        )

    st.session_state.nurses = updated
    _render_assistant_editor()
    _render_request_summary()
    return updated


def _render_assistant_editor() -> None:
    st.subheader("보조 인력")
    st.caption("근무표 생성 대상은 아니며, 결과 표와 HWP 하단 행에 표시됩니다. 듀티 신청도 가능합니다.")
    rows = [
        {"이름": assistant.name, "구분": assistant.role}
        for assistant in st.session_state.get("assistants", [])
    ]
    edited = st.data_editor(
        pd.DataFrame(rows, columns=["이름", "구분"]),
        key="assistant_editor_v1",
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "구분": st.column_config.TextColumn(help="예: 간호조무사", required=True),
        },
    )
    updated: list[Assistant] = []
    for _, row in edited.iterrows():
        name = str(row.get("이름") or "").strip()
        if not name or name.lower() == "nan":
            continue
        role = str(row.get("구분") or "").strip() or "간호조무사"
        updated.append(Assistant(name=name, role=role))
    st.session_state.assistants = updated
