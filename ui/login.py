from __future__ import annotations

import streamlit as st

from core.auth import (
    PIN_MAX_LEN,
    PIN_MIN_LEN,
    check_login,
    create_account,
    valid_pin_format,
)
from core.persistence import create_ward, list_wards, load_users, save_users
from ui.state import init_state

_DEFAULT_WARD_CODE = "admin1234"


def _ward_registration_code() -> tuple[str, bool]:
    """(병동 등록 코드, secrets에 설정돼 있는지). 미설정이면 로컬 기본값을 쓴다.

    새 병원/병동을 만들 때만 필요하다 — 공개된 URL에서 아무나 병동을 계속
    만들어내는 것을 막는 최소한의 문턱이며, 병동별 일상 로그인에는 쓰이지 않는다.
    """
    try:
        configured = st.secrets.get("admin_password")
    except Exception:
        configured = None
    if configured:
        return str(configured), True
    return _DEFAULT_WARD_CODE, False


def _ward_label(info: dict) -> str:
    return f"{info.get('hospital_name', '')} - {info.get('ward_name', '')}"


def _roster_names() -> set[str]:
    names = {n.name for n in st.session_state.get("nurses", [])}
    names |= {a.name for a in st.session_state.get("assistants", [])}
    return names


def _users() -> dict[str, dict]:
    ward_id = st.session_state.get("ward_id")
    if st.session_state.get("_auth_users_ward") != ward_id:
        st.session_state.auth_users = load_users(ward_id)
        st.session_state._auth_users_ward = ward_id
    return st.session_state.auth_users


def _set_users(users: dict[str, dict]) -> None:
    st.session_state.auth_users = users
    save_users(st.session_state.ward_id, users)


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def logout_button() -> None:
    user = current_user()
    if user is None:
        return
    with st.sidebar:
        role = "관리자" if user.get("is_admin") else "사용자"
        st.markdown(f"**{user['name']}** ({role})")
        ward_info = st.session_state.get("ward_info") or {}
        if ward_info:
            st.caption(_ward_label(ward_info))
        if st.button("로그아웃", use_container_width=True):
            st.session_state.auth_user = None
            st.rerun()
        if st.button("다른 병동으로 전환", use_container_width=True):
            for key in ("auth_user", "ward_id", "ward_info", "auth_users", "_auth_users_ward"):
                st.session_state.pop(key, None)
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


def _ward_register_form() -> None:
    code, configured = _ward_registration_code()
    if not configured:
        st.caption(
            "⚠️ 병동 등록 코드가 설정되지 않아 기본값을 사용 중입니다. "
            "배포 시 Secrets에 admin_password를 꼭 설정하세요."
        )
    with st.form("ward_register_form"):
        hospital_name = st.text_input("병원 이름")
        ward_name = st.text_input("병동 이름")
        admin_name = st.text_input("관리자 이름")
        admin_pin = st.text_input(f"관리자 PIN ({PIN_MIN_LEN}~{PIN_MAX_LEN}자리 숫자)", type="password")
        admin_pin2 = st.text_input("PIN 확인", type="password")
        entered_code = st.text_input("병동 등록 코드", type="password")
        submitted = st.form_submit_button("병동 등록", type="primary", use_container_width=True)
    if not submitted:
        return
    hospital_name = hospital_name.strip()
    ward_name = ward_name.strip()
    admin_name = admin_name.strip()
    if entered_code != code:
        st.error("병동 등록 코드가 올바르지 않습니다.")
    elif not hospital_name or not ward_name or not admin_name:
        st.error("병원 이름, 병동 이름, 관리자 이름을 모두 입력하세요.")
    elif not valid_pin_format(admin_pin.strip()):
        st.error(f"PIN은 {PIN_MIN_LEN}~{PIN_MAX_LEN}자리 숫자여야 합니다.")
    elif admin_pin.strip() != admin_pin2.strip():
        st.error("PIN 확인이 일치하지 않습니다.")
    else:
        ward_id = create_ward(hospital_name, ward_name)
        if ward_id is None:
            st.error("이미 등록된 병원/병동입니다. 목록에서 선택해 로그인하세요.")
        else:
            save_users(ward_id, create_account({}, admin_name, admin_pin.strip(), is_admin=True))
            st.session_state.ward_id = ward_id
            st.session_state.ward_info = {"hospital_name": hospital_name, "ward_name": ward_name}
            st.session_state.auth_user = {"name": admin_name, "is_admin": True}
            st.rerun()


def _select_ward_screen() -> None:
    st.title("Duty Maker")
    st.caption("병원/병동을 선택하거나 새로 등록하세요.")
    wards = list_wards()
    _none = "선택하세요"

    if wards:
        chosen = st.selectbox(
            "병원 / 병동",
            options=[_none, *wards.keys()],
            format_func=lambda wid: _none if wid == _none else _ward_label(wards[wid]),
        )
        if chosen != _none and st.button("이 병동으로 계속", type="primary", use_container_width=True):
            st.session_state.ward_id = chosen
            st.session_state.ward_info = wards[chosen]
            st.rerun()

    with st.expander("+ 새 병원/병동 등록", expanded=not wards):
        _ward_register_form()


def require_login() -> tuple[dict, str]:
    """로그인 상태면 (사용자 정보, ward_id)를 반환하고, 아니면 화면을 그리고 멈춘다."""
    ward_id = st.session_state.get("ward_id")
    if ward_id is None:
        _select_ward_screen()
        st.stop()
        raise RuntimeError("unreachable")

    init_state(ward_id)

    user = current_user()
    if user is not None:
        logout_button()
        return user, ward_id

    st.title("Duty Maker")
    st.caption(_ward_label(st.session_state.get("ward_info") or {}))
    st.caption("이름과 PIN으로 로그인하세요. 데이터는 서버에만 저장되며 브라우저에는 남지 않습니다.")
    tab_login, tab_register = st.tabs(["로그인", "PIN 등록(처음)"])
    with tab_login:
        _login_tab()
    with tab_register:
        _register_tab()
    st.stop()
    raise RuntimeError("unreachable")


def render_account_admin() -> None:
    """관리자용 계정 관리: 관리자 권한 부여/해제, PIN 초기화(계정 삭제), 명단-계정 연동 확인."""
    st.subheader("계정 관리")
    users = _users()
    roster = _roster_names()

    unregistered = sorted(roster - set(users))
    if unregistered:
        st.info("계정 미등록 (명단에는 있음): " + ", ".join(unregistered))

    orphaned = sorted(set(users) - roster)
    if orphaned:
        st.warning("명단에 없는 계정입니다 (퇴사 등). 필요 없으면 PIN 초기화로 정리하세요: " + ", ".join(orphaned))

    if not users:
        st.info("등록된 계정이 없습니다. 각자 로그인 화면의 'PIN 등록' 탭에서 등록합니다.")
        return
    my_name = (current_user() or {}).get("name")
    changed = False
    for name in sorted(users):
        col_name, col_admin, col_reset = st.columns([2, 1, 1])
        col_name.write(f"{name} ⚠️" if name in orphaned else name)
        if name == my_name:
            col_admin.caption("본인 계정")
            col_reset.caption("-")
            continue
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
