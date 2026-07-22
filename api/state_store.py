"""Load and save a ward's full application state as a plain dict."""

from __future__ import annotations

from datetime import date

from core.holidays_kr import get_month_holiday_items
from core.models import ShiftType, lookback_dates, month_key
from core.persistence import apply_state, load_state, save_state
from core.sample_data import ward_templates

_CHARGE_SHIFTS = ("D", "E", "N")


def default_charge_minimums(ss: dict) -> dict[str, int]:
    """근무별 차지 최소 기본값 = 해당 근무 목표 인원 ÷ 2 (내림). 평일/주말 각각."""
    out: dict[str, int] = {}
    for prefix, key in (("weekday", "weekday_template"), ("weekend", "weekend_template")):
        template = ss.get(key)
        for i, shift in enumerate(_CHARGE_SHIFTS):
            target = template[i].target if template else 0
            out[f"{prefix}_charge_{shift}"] = target // 2
    return out


def resolve_ward_settings(ss: dict) -> dict[str, int]:
    """병동 제약 설정을 확정한다: 저장된 값이 있으면 그것, 없으면 목표÷2 기본값."""
    stored = ss.get("constraint_settings") or {}
    resolved = default_charge_minimums(ss)
    for key in list(resolved):
        if stored.get(key) is not None:
            resolved[key] = int(stored[key])
    return resolved


def normalize_month_state(ss: dict) -> None:
    """대상 연월이 바뀌었으면 공휴일을 전부 선택하고 날짜별 예외를 비운다.

    근무표 생성·결과 표시도 이 선택을 읽으므로, 인원 기준 탭을 한 번도 열지
    않았더라도 공휴일이 반영되도록 상태를 읽을 때마다 맞춰 준다.
    """
    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    month_key = f"{year}-{month:02d}"
    if ss.get("holiday_month_key") == month_key:
        return
    ss["holiday_month_key"] = month_key
    ss["selected_holidays"] = {day.isoformat() for day, _ in get_month_holiday_items(year, month)}
    ss["date_override_rows"] = []
    ss["date_overrides"] = {}


def staffing_signature(ss: dict, year: int, month: int) -> dict:
    """해당 월의 인원 기준 서명. 이 값이 달라졌을 때만 그 달 근무표를 무효화한다."""
    prefix = month_key(year, month)

    def tmpl(template) -> list[list[int]]:
        return [[r.minimum, r.maximum, r.target] for r in template] if template else []

    holidays = sorted(
        str(h) for h in ss.get("selected_holidays", set()) if str(h).startswith(prefix)
    )
    overrides = sorted(
        (row for row in ss.get("date_override_rows", []) if str(row.get("date", "")).startswith(prefix)),
        key=lambda row: str(row.get("date", "")),
    )
    return {
        "weekday": tmpl(ss.get("weekday_template")),
        "weekend": tmpl(ss.get("weekend_template")),
        "holidays": holidays,
        "overrides": overrides,
    }


def prev_month_history(ss: dict, year: int, month: int) -> dict[tuple[str, date], ShiftType]:
    """현재 월의 직전 달 입력을 솔버 history 형태로 변환한다.

    lookback 5일에 해당하는 셀만, 값이 있는 셀만 담는다(빈칸은 오프로 간주됨).
    """
    key = month_key(year, month)
    values = (ss.get("prev_month_inputs") or {}).get(key) or {}
    lookback = {day.isoformat() for day in lookback_dates(year, month, 5)}
    history: dict[tuple[str, date], ShiftType] = {}
    helper_names = {nurse.name for nurse in ss.get("nurses", []) if nurse.is_helper}
    for name, days in values.items():
        if name in helper_names:
            continue
        for iso, raw_shift in (days or {}).items():
            if iso not in lookback:
                continue
            try:
                history[(name, date.fromisoformat(iso))] = ShiftType(raw_shift)
            except ValueError:
                continue
    return history


def prev_month_confirmed(ss: dict, year: int, month: int) -> bool:
    """현재 월에 대한 직전 달 입력이 한 번이라도 확정(저장/자동채움)되었는가."""
    return month_key(year, month) in (ss.get("prev_month_inputs") or {})


def load_ward_state(ward_id: str) -> dict:
    ss: dict = {}
    payload = load_state(ward_id)
    if payload:
        apply_state(ss, payload)
    ss.setdefault("nurses", [])
    ss.setdefault("assistants", [])
    ss.setdefault("duty_requests", [])
    ss.setdefault("selected_holidays", set())
    ss.setdefault("date_override_rows", [])
    ss.setdefault("date_overrides", {})
    ss.setdefault("schedule_revision", 0)
    ss.setdefault("schedule_previews", {})
    ss.setdefault("manual_overrides", {})
    ss.setdefault("export_settings", {})
    ss.setdefault("schedules_by_month", {})
    ss.setdefault("published_by_month", {})
    # Older Firestore state can contain an explicit null for this field.
    # setdefault() preserves an existing None, which makes schedule generation
    # fail when it records the current month's signature.
    if not isinstance(ss.get("schedule_signatures"), dict):
        ss["schedule_signatures"] = {}
    ss.setdefault("prev_month_inputs", {})
    ss.setdefault("year", 2026)
    ss.setdefault("month", 7)
    if "weekday_template" not in ss or "weekend_template" not in ss:
        weekday, weekend = ward_templates()
        ss["weekday_template"] = weekday
        ss["weekend_template"] = weekend
    normalize_month_state(ss)
    _mirror_active_month(ss)
    return ss


def _mirror_active_month(ss: dict) -> None:
    """활성 슬롯(schedule_result/result_published)을 현재 선택 월의 보관본으로 맞춘다.

    월별 보관소가 단일 진실이며, 기존 코드가 읽는 schedule_result는 그 미러다.
    레거시 상태(보관소 없이 schedule_result만 있음)는 현재 월 항목으로 이관한다.
    """
    key = month_key(int(ss.get("year", 2026)), int(ss.get("month", 7)))
    archive = ss["schedules_by_month"]
    published = ss["published_by_month"]
    if key not in archive and ss.get("schedule_result") is not None:
        archive[key] = ss["schedule_result"]
        published.setdefault(key, bool(ss.get("result_published", False)))
    ss["schedule_result"] = archive.get(key)
    ss["result_published"] = published.get(key, False)


def _sync_active_month(ss: dict) -> None:
    """저장 직전, 활성 슬롯을 현재 선택 월의 보관소로 되쓴다.

    generate/수동편집/공개 등 어떤 경로가 schedule_result를 바꿔도, 이 한 곳에서
    보관소를 최신화해 다른 달의 근무표를 잃지 않는다.
    """
    key = month_key(int(ss.get("year", 2026)), int(ss.get("month", 7)))
    archive = ss.setdefault("schedules_by_month", {})
    published = ss.setdefault("published_by_month", {})
    result = ss.get("schedule_result")
    if result is None:
        archive.pop(key, None)
        published.pop(key, None)
    else:
        archive[key] = result
        published[key] = bool(ss.get("result_published", False))


def save_ward_state(ward_id: str, ss: dict, requests_only: bool = False) -> None:
    if not requests_only:
        _sync_active_month(ss)
    save_state(ss, ward_id, requests_only=requests_only)
