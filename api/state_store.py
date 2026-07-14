"""Load and save a ward's full application state as a plain dict."""

from __future__ import annotations

from core.holidays_kr import get_month_holiday_items
from core.persistence import apply_state, load_state, save_state
from core.sample_data import ward_templates


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
    ss.setdefault("year", 2026)
    ss.setdefault("month", 7)
    if "weekday_template" not in ss or "weekend_template" not in ss:
        weekday, weekend = ward_templates()
        ss["weekday_template"] = weekday
        ss["weekend_template"] = weekend
    normalize_month_state(ss)
    return ss


def save_ward_state(ward_id: str, ss: dict, requests_only: bool = False) -> None:
    save_state(ss, ward_id, requests_only=requests_only)
