from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import Nurse
from ui.state import LABEL_TO_LEVEL, LEVEL_LABELS, level_label, parse_shift, shift_label


def render_nurse_editor() -> list[Nurse]:
    st.subheader("간호사 명단")

    nurses = st.session_state.nurses
    rows = [
        {
            "이름": nurse.name,
            "연차 구분": level_label(nurse),
            "N 제외": nurse.n_excluded,
            "전담": shift_label(nurse.dedicated_shift),
            "N 상한": nurse.max_n_hard if nurse.max_n_hard < 999 else 999,
            "N 선호연속": nurse.n_soft_consecutive_limit,
            "평일만": nurse.weekday_only,
        }
        for nurse in nurses
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
            "전담": st.column_config.SelectboxColumn(
                options=["없음", "D", "E"],
                required=True,
            ),
            "N 선호연속": st.column_config.SelectboxColumn(options=[2, 3], required=True),
        },
    )

    updated: list[Nurse] = []
    for _, row in edited.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        level = LABEL_TO_LEVEL.get(row.get("연차 구분"), next(iter(LEVEL_LABELS)))
        max_n = int(row.get("N 상한", 999) or 999)
        updated.append(
            Nurse(
                name=name,
                level=level,
                n_excluded=bool(row.get("N 제외", False)),
                dedicated_shift=parse_shift(str(row.get("전담", "없음"))),
                max_n_hard=max_n,
                n_soft_consecutive_limit=int(row.get("N 선호연속", 3) or 3),
                weekday_only=bool(row.get("평일만", False)),
            )
        )

    st.session_state.nurses = updated
    return updated
