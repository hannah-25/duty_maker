"""앱 입력/결과를 JSON 파일로 저장·복원하는 모듈.

Streamlit session_state는 브라우저 세션 메모리라 새로고침하면 사라지므로,
매 rerun 마지막에 저장하고 새 세션 시작 시 복원한다 (data/app_state.json).
"""

from __future__ import annotations

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

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "app_state.json"
STATE_VERSION = 1

# 저장 대상이 아닌 session_state 키(위젯 상태 등)는 여기 나열된 것만 저장해 걸러낸다.
_PLAIN_KEYS = ("year", "month", "holiday_month_key", "date_override_rows")


def _nurse_to_dict(n: Nurse) -> dict:
    return {
        "name": n.name,
        "level": n.level.value if n.level is not None else None,
        "allowed_shifts": sorted(s.value for s in (n.allowed_shifts or set())),
        "max_n_hard": n.max_n_hard,
        "n_soft_consecutive_limit": n.n_soft_consecutive_limit,
        "al_target": n.al_target,
        "weekday_only": n.weekday_only,
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


def load_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(ss) -> None:
    """변경이 있을 때만 파일에 기록한다 (rerun마다 호출돼도 부담 없도록)."""
    try:
        text = json.dumps(serialize_state(ss), ensure_ascii=False, indent=1)
    except Exception:
        return
    if ss.get("_last_saved_state") == text:
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(text, encoding="utf-8")
    ss["_last_saved_state"] = text


def clear_state() -> None:
    if STATE_PATH.exists():
        STATE_PATH.unlink()
