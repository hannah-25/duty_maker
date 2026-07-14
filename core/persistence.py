"""앱 입력/결과를 저장·복원하는 모듈 (로컬 JSON 또는 Firestore).

애플리케이션 상태를 로컬 JSON 또는 Firestore에 저장하고 복원한다.

백엔드 선택: FIREBASE_CREDENTIALS_JSON 환경변수에 서비스 계정 키 JSON 문자열이
있으면 Firestore, 없으면 로컬 파일(data/wards/{ward_id}/app_state.json 등).

병원+병동 조합(ward)마다 데이터가 완전히 분리된다. ward_id는 병원명+병동명으로
결정되는 해시이며, wards 레지스트리에 표시용 이름을 저장한다.
Firestore에서는 듀티 신청을 1건=1문서로 분리해 여러 사용자의 동시 제출이
서로 덮어쓰지 않게 한다 (문서 id = 신청 내용 해시).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from core.models import (
    Assistant,
    DutyRequest,
    Nurse,
    NurseLevel,
    ScheduleResult,
    ShiftRequirement,
    ShiftType,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WARDS_REGISTRY_PATH = DATA_DIR / "wards_registry.json"
STATE_VERSION = 1

# Firestore 컬렉션/문서 이름
_FS_WARDS_COLLECTION = "wards"
_FS_STATE_COLLECTION = "app_state"
_FS_STATE_DOC = "main"
_FS_REQUESTS_COLLECTION = "duty_requests"
_FS_USERS_COLLECTION = "users"

# 저장 대상이 아닌 session_state 키(위젯 상태 등)는 여기 나열된 것만 저장해 걸러낸다.
_PLAIN_KEYS = (
    "year",
    "month",
    "holiday_month_key",
    "date_override_rows",
    "requests_locked",
    "result_published",
    "constraint_settings",
)


def _nurse_to_dict(n: Nurse) -> dict:
    return {
        "name": n.name,
        "level": n.level.value if n.level is not None else None,
        "allowed_shifts": sorted(s.value for s in (n.allowed_shifts or set())),
        "max_n_hard": n.max_n_hard,
        "n_soft_consecutive_limit": n.n_soft_consecutive_limit,
        "al_target": n.al_target,
        "weekday_only": n.weekday_only,
        "is_helper": n.is_helper,
        "helper_shifts": {d.isoformat(): s.value for d, s in (n.helper_shifts or {}).items()},
        "helper_workdays": n.helper_workdays,
    }


def _nurse_from_dict(d: dict) -> Nurse:
    return Nurse(
        name=d["name"],
        level=NurseLevel(d["level"]) if d.get("level") else None,
        allowed_shifts={ShiftType(s) for s in d.get("allowed_shifts", [])} or None,
        max_n_hard=int(d.get("max_n_hard", 8)),
        n_soft_consecutive_limit=d.get("n_soft_consecutive_limit"),
        al_target=d.get("al_target"),
        weekday_only=bool(d.get("weekday_only", False)),
        is_helper=bool(d.get("is_helper", False)),
        helper_shifts=d.get("helper_shifts", {}),
        helper_workdays=d.get("helper_workdays"),
    )


def _request_to_dict(r: DutyRequest) -> dict:
    return {
        "nurse_name": r.nurse_name,
        "day": r.day.isoformat(),
        "requested_shift": r.requested_shift.value,
        "kind": getattr(r, "kind", "prefer"),
        "decision": getattr(r, "decision", "force"),
        "priority": getattr(r, "priority", 1),
        "memo": getattr(r, "memo", ""),
    }


def _request_from_dict(d: dict) -> DutyRequest:
    return DutyRequest(
        nurse_name=d["nurse_name"],
        day=date.fromisoformat(d["day"]),
        requested_shift=ShiftType(d["requested_shift"]),
        kind=d.get("kind", "prefer"),
        decision=d.get("decision", "force"),
        priority=int(d.get("priority", 1)),
        memo=d.get("memo", ""),
    )


def _template_to_list(template) -> list[list[int]]:
    return [[req.minimum, req.maximum, req.target] for req in template]


def _template_from_list(data) -> tuple[ShiftRequirement, ShiftRequirement, ShiftRequirement]:
    return tuple(ShiftRequirement(minimum=row[0], maximum=row[1], target=row[2]) for row in data)


def _result_to_dict(r: ScheduleResult) -> dict:
    return {
        "feasible": r.feasible,
        "assignments": [
            [name, day.isoformat(), shift.value] for (name, day), shift in r.assignments.items()
        ],
        "infeasible_categories": list(r.infeasible_categories),
        "soft_violations": dict(r.soft_violations),
        "dropped_duty_requests": [_request_to_dict(req) for req in r.dropped_duty_requests],
        "honored_duty_requests": [_request_to_dict(req) for req in r.honored_duty_requests],
        "objective_value": r.objective_value,
    }


def _result_from_dict(d: dict) -> ScheduleResult:
    return ScheduleResult(
        feasible=bool(d.get("feasible")),
        assignments={
            (name, date.fromisoformat(day)): ShiftType(shift)
            for name, day, shift in d.get("assignments", [])
        },
        infeasible_categories=list(d.get("infeasible_categories", [])),
        soft_violations=dict(d.get("soft_violations", {})),
        dropped_duty_requests=[_request_from_dict(r) for r in d.get("dropped_duty_requests", [])],
        honored_duty_requests=[_request_from_dict(r) for r in d.get("honored_duty_requests", [])],
        objective_value=d.get("objective_value"),
    )


def serialize_state(ss) -> dict:
    payload = {"version": STATE_VERSION}
    for key in _PLAIN_KEYS:
        if key in ss:
            payload[key] = ss[key]
    payload["nurses"] = [_nurse_to_dict(n) for n in ss.get("nurses", [])]
    payload["assistants"] = [
        {"name": a.name, "role": a.role} for a in ss.get("assistants", [])
    ]
    payload["duty_requests"] = [_request_to_dict(r) for r in ss.get("duty_requests", [])]
    payload["selected_holidays"] = sorted(ss.get("selected_holidays", set()))
    if ss.get("weekday_template"):
        payload["weekday_template"] = _template_to_list(ss["weekday_template"])
    if ss.get("weekend_template"):
        payload["weekend_template"] = _template_to_list(ss["weekend_template"])
    result = ss.get("schedule_result")
    payload["schedule_result"] = _result_to_dict(result) if result is not None else None
    return payload


def apply_state(ss, payload: dict) -> None:
    for key in _PLAIN_KEYS:
        if key in payload:
            ss[key] = payload[key]
    ss["nurses"] = [_nurse_from_dict(d) for d in payload.get("nurses", [])]
    ss["assistants"] = [
        Assistant(name=d["name"], role=d.get("role", "간호조무사"))
        for d in payload.get("assistants", [])
    ]
    ss["duty_requests"] = [_request_from_dict(d) for d in payload.get("duty_requests", [])]
    ss["selected_holidays"] = set(payload.get("selected_holidays", []))
    if payload.get("weekday_template"):
        ss["weekday_template"] = _template_from_list(payload["weekday_template"])
    if payload.get("weekend_template"):
        ss["weekend_template"] = _template_from_list(payload["weekend_template"])
    if payload.get("schedule_result"):
        ss["schedule_result"] = _result_from_dict(payload["schedule_result"])


# ---------------------------------------------------------------- backend --
def _firestore():
    """설정이 있으면 Firestore 클라이언트, 없으면 None."""
    import os

    conf = None
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if raw:
        try:
            conf = json.loads(raw)
        except Exception:
            conf = None
    if not conf:
        return None
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(dict(conf)))
    return firestore.client()


def is_remote_backend() -> bool:
    return _firestore() is not None


def _ward_dir(ward_id: str) -> Path:
    return DATA_DIR / "wards" / ward_id


def _request_doc_id(rd: dict) -> str:
    key = f"{rd['nurse_name']}|{rd['day']}|{rd.get('kind', 'prefer')}|{rd['requested_shift']}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def _split_requests(payload: dict) -> tuple[dict, dict[str, dict]]:
    """payload에서 신청을 분리해 (신청 제외 payload, {문서id: 신청}) 반환."""
    rest = {k: v for k, v in payload.items() if k != "duty_requests"}
    requests = {_request_doc_id(rd): rd for rd in payload.get("duty_requests", [])}
    return rest, requests


# ------------------------------------------------------------------ wards --
def make_ward_id(hospital_name: str, ward_name: str) -> str:
    key = f"{hospital_name.strip()}|{ward_name.strip()}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def list_wards() -> dict[str, dict]:
    """{ward_id: {hospital_name, ward_name}} 전체 목록."""
    db = _firestore()
    if db is not None:
        return {snap.id: snap.to_dict() for snap in db.collection(_FS_WARDS_COLLECTION).stream()}
    if not WARDS_REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(WARDS_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def create_ward(hospital_name: str, ward_name: str) -> str | None:
    """새 병동을 등록하고 ward_id를 반환한다. 이미 존재하면 None."""
    hospital_name = hospital_name.strip()
    ward_name = ward_name.strip()
    ward_id = make_ward_id(hospital_name, ward_name)
    wards = list_wards()
    if ward_id in wards:
        return None
    info = {"hospital_name": hospital_name, "ward_name": ward_name}
    db = _firestore()
    if db is not None:
        db.collection(_FS_WARDS_COLLECTION).document(ward_id).set(info)
    else:
        wards[ward_id] = info
        WARDS_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        WARDS_REGISTRY_PATH.write_text(json.dumps(wards, ensure_ascii=False, indent=1), encoding="utf-8")
    return ward_id


# ------------------------------------------------------------------ state --
def load_state(ward_id: str) -> dict | None:
    db = _firestore()
    if db is not None:
        ward_ref = db.collection(_FS_WARDS_COLLECTION).document(ward_id)
        doc = ward_ref.collection(_FS_STATE_COLLECTION).document(_FS_STATE_DOC).get()
        payload = doc.to_dict() if doc.exists else None
        if payload is None:
            return None
        payload["duty_requests"] = [
            snap.to_dict() for snap in ward_ref.collection(_FS_REQUESTS_COLLECTION).stream()
        ]
        return payload
    state_path = _ward_dir(ward_id) / "app_state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(ss, ward_id: str, requests_only: bool = False) -> None:
    """변경이 있을 때만 기록한다 (rerun마다 호출돼도 부담 없도록).

    requests_only: 일반 사용자 세션용 — 듀티 신청만 기록해서, 그 사이 관리자가
    바꾼 명단/설정을 오래된 값으로 덮어쓰지 않게 한다.
    """
    try:
        payload = serialize_state(ss)
        text = json.dumps(payload, ensure_ascii=False, indent=1)
    except Exception:
        return
    if ss.get("_last_saved_state") == text:
        return

    db = _firestore()
    if db is not None:
        ward_ref = db.collection(_FS_WARDS_COLLECTION).document(ward_id)
        rest, requests = _split_requests(payload)
        last_text = ss.get("_last_saved_state")
        if last_text:
            _, last_requests = _split_requests(json.loads(last_text))
        else:
            # 세션 첫 저장: 서버에 남아 있는 신청 문서와 대조해 정리
            last_requests = {
                snap.id: None for snap in ward_ref.collection(_FS_REQUESTS_COLLECTION).stream()
            }
        batch = db.batch()
        if not requests_only:
            batch.set(ward_ref.collection(_FS_STATE_COLLECTION).document(_FS_STATE_DOC), rest)
        for doc_id, rd in requests.items():
            batch.set(ward_ref.collection(_FS_REQUESTS_COLLECTION).document(doc_id), rd)
        for doc_id in last_requests:
            if doc_id not in requests:
                batch.delete(ward_ref.collection(_FS_REQUESTS_COLLECTION).document(doc_id))
        batch.commit()
    else:
        state_path = _ward_dir(ward_id) / "app_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        if requests_only:
            existing = load_state(ward_id) or {}
            existing["duty_requests"] = payload.get("duty_requests", [])
            text_to_write = json.dumps(existing, ensure_ascii=False, indent=1)
        else:
            text_to_write = text
        state_path.write_text(text_to_write, encoding="utf-8")
    ss["_last_saved_state"] = text


def reload_duty_requests(ss, ward_id: str) -> bool:
    """다른 세션이 제출한 신청을 포함해 최신 신청 목록을 다시 불러온다 (Firestore 전용)."""
    db = _firestore()
    if db is None:
        return False
    ward_ref = db.collection(_FS_WARDS_COLLECTION).document(ward_id)
    ss["duty_requests"] = [
        _request_from_dict(snap.to_dict())
        for snap in ward_ref.collection(_FS_REQUESTS_COLLECTION).stream()
    ]
    ss.pop("_last_saved_state", None)
    return True


def clear_state(ward_id: str) -> None:
    db = _firestore()
    if db is not None:
        ward_ref = db.collection(_FS_WARDS_COLLECTION).document(ward_id)
        ward_ref.collection(_FS_STATE_COLLECTION).document(_FS_STATE_DOC).delete()
        for snap in ward_ref.collection(_FS_REQUESTS_COLLECTION).stream():
            snap.reference.delete()
        return
    state_path = _ward_dir(ward_id) / "app_state.json"
    if state_path.exists():
        state_path.unlink()


# ------------------------------------------------------------------ users --
def load_users(ward_id: str) -> dict[str, dict]:
    """계정 목록 {이름: {pin_salt, pin_hash, is_admin}}. 상태 초기화와 무관하게 유지된다."""
    db = _firestore()
    if db is not None:
        ward_ref = db.collection(_FS_WARDS_COLLECTION).document(ward_id)
        return {
            snap.id: snap.to_dict() for snap in ward_ref.collection(_FS_USERS_COLLECTION).stream()
        }
    users_path = _ward_dir(ward_id) / "users.json"
    if not users_path.exists():
        return {}
    try:
        return json.loads(users_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(ward_id: str, users: dict[str, dict]) -> None:
    db = _firestore()
    if db is not None:
        ward_ref = db.collection(_FS_WARDS_COLLECTION).document(ward_id)
        existing = {snap.id for snap in ward_ref.collection(_FS_USERS_COLLECTION).stream()}
        batch = db.batch()
        for name, account in users.items():
            batch.set(ward_ref.collection(_FS_USERS_COLLECTION).document(name), account)
        for name in existing - set(users):
            batch.delete(ward_ref.collection(_FS_USERS_COLLECTION).document(name))
        batch.commit()
        return
    users_path = _ward_dir(ward_id) / "users.json"
    users_path.parent.mkdir(parents=True, exist_ok=True)
    users_path.write_text(json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8")
