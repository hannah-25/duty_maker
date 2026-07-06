from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import ShiftRequirement
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


def render_requirement_editor():
    st.subheader("인원 기준")
    col1, col2 = st.columns(2)
    with col1:
        weekday = _edit_template("평일", "weekday_template_editor", st.session_state.weekday_template)
    with col2:
        weekend = _edit_template("주말", "weekend_template_editor", st.session_state.weekend_template)

    st.session_state.weekday_template = weekday
    st.session_state.weekend_template = weekend
    return weekday, weekend
