from __future__ import annotations

import streamlit as st

from core.auth import (
    PIN_MAX_LEN,
    PIN_MIN_LEN,
    check_login,
    create_account,
    valid_pin_format,
)
from core.persistence import load_users, save_users

ADMIN_DISPLAY_NAME = "관리자"
_DEFAULT_ADMIN_PASSWORD = "admin1234"


def _admin_password() -> tuple[str, bool]:
    """(관리자 비밀번호, secrets에 설정돼 있는지). 미설정이면 로컬 기본값을 쓴다."""
    try:
        configured = st.secrets.get("admin_password")
    except Exception:
        configured = None
    if configured:
        return str(configured), True
    return _DEFAULT_ADMIN_PASSWORD, False


def _roster_names() -> set[str]:
    names = {n.name for n in st.session_state.get("nurses", [])}
    names |= {a.name for a in st.session_state.get("assistants", [])}
    return names


def _users() -> dict[str, dict]:
    if "auth_users" not in st.session_state:
        st.session_state.auth_users = load_users()
    return st.session_state.auth_users


def _set_users(users: dict[str, dict]) -> None:
    st.session_state.auth_users = users
    save_users(users)


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def logout_button() -> None:
    user = current_user()
    if user is None:
        return
    with st.sidebar:
        role = "관리자" if user.get("is_admin") else "사용자"
        st.markdown(f"**{user['name']}** ({role})")
        if st.button("로그아웃", use_container_width=True):
            st.session_state.auth_user = None
            st.rerun()


def _login_tab() -> None:
    with st.form("login_form"):
        name = st.text_input("이름")
        pin = st.text_input(f"PIN ({PIN_MIN_LEN}~{PIN_MAX_LEN}자리 숫자)", type="password")
        submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
    if not submitted:
        return
    name = name.strip()
    users = _users()
    if not name or not check_login(users, name, pin.strip()):
        st.error("이름 또는 PIN이 올바르지 않습니다. 처음이면 'PIN 등록' 탭에서 등록하세요.")
        return
    st.session_state.auth_user = {
        "name": name,
        "is_admin": bool(users[name].get("is_admin")),
    }
    st.rerun()


def _register_tab() -> None:
    st.caption("명단에 등록된 이름만 가입할 수 있습니다. 이름이 없으면 관리자(수간호사)에게 문의하세요.")
    with st.form("register_form"):
        name = st.text_input("이름 (명단과 동일하게)")
        pin = st.text_input(f"PIN ({PIN_MIN_LEN}~{PIN_MAX_LEN}자리 숫자)", type="password")
        pin2 = st.text_input("PIN 확인", type="password")
        submitted = st.form_submit_button("PIN 등록", type="primary", use_container_width=True)
    if not submitted:
        return
    name = name.strip()
    users = _users()
    if name not in _roster_names():
        st.error("명단에 없는 이름입니다.")
    elif name in users:
        st.error("이미 등록된 이름입니다. PIN을 잊었으면 관리자에게 초기화를 요청하세요.")
    elif not valid_pin_format(pin.strip()):
        st.error(f"PIN은 {PIN_MIN_LEN}~{PIN_MAX_LEN}자리 숫자여야 합니다.")
    elif pin.strip() != pin2.strip():
        st.error("PIN 확인이 일치하지 않습니다.")
    else:
        _set_users(create_account(users, name, pin.strip()))
        st.session_state.auth_user = {"name": name, "is_admin": False}
        st.rerun()


def _admin_tab() -> None:
    password, configured = _admin_password()
    if not configured:
        st.caption("⚠️ 관리자 비밀번호가 설정되지 않아 기본값을 사용 중입니다. 배포 시 Secrets에 admin_password를 꼭 설정하세요.")
    with st.form("admin_login_form"):
        entered = st.text_input("관리자 비밀번호", type="password")
        submitted = st.form_submit_button("관리자 로그인", type="primary", use_container_width=True)
    if not submitted:
        return
    if entered != password:
        st.error("관리자 비밀번호가 올바르지 않습니다.")
        return
    st.session_state.auth_user = {"name": ADMIN_DISPLAY_NAME, "is_admin": True}
    st.rerun()


def require_login() -> dict:
    """로그인 상태면 사용자 정보를 반환하고, 아니면 로그인 화면을 그리고 멈춘다."""
    user = current_user()
    if user is not None:
        logout_button()
        return user

    st.title("Duty Maker")
    st.caption("이름과 PIN으로 로그인하세요. 데이터는 서버에만 저장되며 브라우저에는 남지 않습니다.")
    tab_login, tab_register, tab_admin = st.tabs(["로그인", "PIN 등록(처음)", "관리자"])
    with tab_login:
        _login_tab()
    with tab_register:
        _register_tab()
    with tab_admin:
        _admin_tab()
    st.stop()
    raise RuntimeError("unreachable")


def render_account_admin() -> None:
    """관리자용 계정 관리: 관리자 권한 부여/해제, PIN 초기화(계정 삭제)."""
    st.subheader("계정 관리")
    users = _users()
    if not users:
        st.info("등록된 계정이 없습니다. 각자 로그인 화면의 'PIN 등록' 탭에서 등록합니다.")
        return
    changed = False
    for name in sorted(users):
        col_name, col_admin, col_reset = st.columns([2, 1, 1])
        col_name.write(name)
        is_admin = col_admin.checkbox(
            "관리자", value=bool(users[name].get("is_admin")), key=f"admin_flag_{name}"
        )
        if is_admin != bool(users[name].get("is_admin")):
            users[name]["is_admin"] = is_admin
            changed = True
        if col_reset.button("PIN 초기화", key=f"pin_reset_{name}"):
            users = {k: v for k, v in users.items() if k != name}
            _set_users(users)
            st.success(f"{name} 계정을 삭제했습니다. 다음 로그인 때 PIN을 다시 등록하면 됩니다.")
            st.rerun()
    if changed:
        _set_users(users)
