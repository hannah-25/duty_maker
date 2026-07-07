from __future__ import annotations

import streamlit as st

_CUSTOM_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

html, body, [data-testid="stAppViewContainer"] * {
    font-family: 'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
}

.block-container {
    padding-top: 2.2rem;
    max-width: 1400px;
}

h1 {
    letter-spacing: -0.02em;
    font-weight: 800;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 0.25rem;
}

.stTabs [data-baseweb="tab"] {
    font-weight: 600;
    border-radius: 10px 10px 0 0;
    padding: 0.4rem 1rem;
}

.stButton > button, .stDownloadButton > button {
    border-radius: 10px;
    font-weight: 600;
}

[data-testid="stMetric"] {
    background: #F5F7FA;
    border-radius: 12px;
    padding: 0.6rem 0.9rem;
}

[data-testid="stSidebar"] {
    background: #F8FAFC;
}
</style>
"""


def apply_custom_style() -> None:
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
