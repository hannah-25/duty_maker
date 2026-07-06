from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import Nurse
from ui.state import (
    LABEL_TO_LEVEL,
    LEVEL_LABELS,
    allowed_shifts_label,
    level_label,
    parse_allowed_shifts,
    parse_optional_int,
)


def render_nurse_editor() -> list[Nurse]:
    st.subheader("간호사 명단")

    rows = [
        {
            "이름": nurse.name,
            "연차 구분": level_label(nurse),
            "가능 듀티": allowed_shifts_label(nurse),
            "N 상한": nurse.max_n_hard,
            "N 선호연속": "" if nurse.n_soft_consecutive_limit is None else str(nurse.n_soft_consecutive_limit),
            "평일만": nurse.weekday_only,
        }
        for nurse in st.session_state.nurses
    ]

    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "연차 구분": st.column_config.SelectboxColumn(
                options=list(LABEL_TO_LEVEL.keys()),
                required=True,
            ),
            "가능 듀티": st.column_config.TextColumn(
                help="D,E,N 중 가능한 듀티를 콤마로 입력",
                required=True,
            ),
            "N 상한": st.column_config.NumberColumn(
                min_value=0,
                max_value=8,
                step=1,
                required=True,
            ),
            "N 선호연속": st.column_config.SelectboxColumn(
                options=["", "2", "3"],
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
        updated.append(
            Nurse(
                name=name,
                level=level,
                allowed_shifts=parse_allowed_shifts(row.get("가능 듀티", "D,E,N")),
                max_n_hard=int(row.get("N 상한", 8) or 0),
                n_soft_consecutive_limit=parse_optional_int(row.get("N 선호연속")),
                weekday_only=bool(row.get("평일만", False)),
            )
        )

    st.session_state.nurses = updated
    return updated
