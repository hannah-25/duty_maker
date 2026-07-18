from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import (
    DateOverrideIn,
    DateOverrideOut,
    HolidayOut,
    RequirementsIn,
    RequirementsOut,
    ShiftRequirementIn,
    ShiftRequirementOut,
    StaffingTemplateIn,
    StaffingTemplateOut,
)
from api.state_store import (
    load_ward_state,
    normalize_month_state,
    save_ward_state,
    staffing_signature,
)
from core.holidays_kr import get_month_holiday_items
from core.models import ShiftRequirement, lookback_dates, month_dates, month_key

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


def _req_from_schema(item: ShiftRequirementIn) -> ShiftRequirement:
    return ShiftRequirement(item.minimum, item.maximum, item.target)


def _template_from_schema(
    template: StaffingTemplateIn,
) -> tuple[ShiftRequirement, ShiftRequirement, ShiftRequirement]:
    return (
        _req_from_schema(template.D),
        _req_from_schema(template.E),
        _req_from_schema(template.N),
    )


def _req_out(req: ShiftRequirement) -> ShiftRequirementOut:
    return ShiftRequirementOut(minimum=req.minimum, maximum=req.maximum, target=req.target)


def _template_out(
    template: tuple[ShiftRequirement, ShiftRequirement, ShiftRequirement],
) -> StaffingTemplateOut:
    return StaffingTemplateOut(D=_req_out(template[0]), E=_req_out(template[1]), N=_req_out(template[2]))


def _current_month_key(year: int, month: int) -> str:
    return month_key(year, month)


def _is_one_month_after(old_key: str, new_key: str) -> bool:
    try:
        old_year, old_month = (int(part) for part in old_key.split("-"))
        new_year, new_month = (int(part) for part in new_key.split("-"))
    except ValueError:
        return False
    return new_year * 12 + (new_month - 1) == old_year * 12 + (old_month - 1) + 1


def _maybe_autofill_prev_month(ss: dict, old_key: str, new_key: str, year: int, month: int) -> None:
    """월을 정확히 +1 진행하면, 직전 달 근무표의 마지막 5일을 직전 달 입력으로 채운다.

    이미 그 월에 대한 직전 달 입력이 확정돼 있으면 유지한다(왕복 이동 시 보존).
    """
    if old_key == new_key:
        return
    inputs = ss.setdefault("prev_month_inputs", {})
    if new_key in inputs:
        return
    if not _is_one_month_after(old_key, new_key):
        return
    prev_result = (ss.get("schedules_by_month") or {}).get(old_key)
    if prev_result is None:
        return
    lookback = {day.isoformat() for day in lookback_dates(year, month, 5)}
    values: dict[str, dict[str, str]] = {}
    for (name, day), shift in prev_result.assignments.items():
        iso = day.isoformat()
        if iso in lookback:
            values.setdefault(name, {})[iso] = shift.value
    inputs[new_key] = values


def _valid_date(raw: str, year: int, month: int) -> date:
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"잘못된 날짜입니다: {raw}")
    if parsed.year != year or parsed.month != month:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"해당 월의 날짜가 아닙니다: {raw}")
    return parsed


def _override_rows_from_body(items: list[DateOverrideIn], year: int, month: int) -> list[dict]:
    valid_dates = {day.isoformat() for day in month_dates(year, month)}
    rows: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if item.date not in valid_dates:
            _valid_date(item.date, year, month)
        if item.date in seen:
            continue
        seen.add(item.date)
        rows.append({"date": item.date, "D": item.D, "E": item.E, "N": item.N})
    return rows


def _override_rows(ss: dict) -> list[DateOverrideOut]:
    rows = ss.get("date_override_rows", [])
    result: list[DateOverrideOut] = []
    for row in rows:
        raw_date = row.get("date") or row.get("날짜")
        if not raw_date:
            continue
        try:
            result.append(
                DateOverrideOut(
                    date=str(raw_date),
                    D=int(row.get("D", 0)),
                    E=int(row.get("E", 0)),
                    N=int(row.get("N", 0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return result


def _requirements_out(ss: dict) -> RequirementsOut:
    normalize_month_state(ss)
    year = int(ss["year"])
    month = int(ss["month"])
    selected = {str(item) for item in ss.get("selected_holidays", set())}
    holidays = [
        HolidayOut(date=day.isoformat(), title=title, selected=day.isoformat() in selected)
        for day, title in get_month_holiday_items(year, month)
    ]
    return RequirementsOut(
        year=year,
        month=month,
        weekday_template=_template_out(ss["weekday_template"]),
        weekend_template=_template_out(ss["weekend_template"]),
        holidays=holidays,
        selected_holidays=sorted(selected),
        date_overrides=_override_rows(ss),
    )


@router.get("", response_model=RequirementsOut)
def get_requirements(user: CurrentUser = Depends(get_current_user)) -> RequirementsOut:
    return _requirements_out(load_ward_state(user.ward_id))


@router.put("", response_model=RequirementsOut)
def put_requirements(
    body: RequirementsIn,
    user: CurrentUser = Depends(require_admin),
) -> RequirementsOut:
    ss = load_ward_state(user.ward_id)
    previous_month_key = _current_month_key(int(ss.get("year", 2026)), int(ss.get("month", 7)))
    next_month_key = _current_month_key(body.year, body.month)
    ss["year"] = body.year
    ss["month"] = body.month
    ss["holiday_month_key"] = next_month_key

    try:
        ss["weekday_template"] = _template_from_schema(body.weekday_template)
        ss["weekend_template"] = _template_from_schema(body.weekend_template)
        valid_month_dates = {day.isoformat() for day in month_dates(body.year, body.month)}
        if previous_month_key != next_month_key and not body.selected_holidays:
            selected_holidays = {day.isoformat() for day, _ in get_month_holiday_items(body.year, body.month)}
        else:
            selected_holidays = set()
            for raw in body.selected_holidays:
                _valid_date(raw, body.year, body.month)
                selected_holidays.add(raw)
        ss["selected_holidays"] = selected_holidays
        ss["date_override_rows"] = _override_rows_from_body(body.date_overrides, body.year, body.month)
        ss["date_overrides"] = {}
        for row in ss["date_override_rows"]:
            if row["date"] not in valid_month_dates:
                raise ValueError(row["date"])
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    # 인원 기준이 바뀌어도 이미 생성된 근무표는 지우지 않는다. 근무표는 관리자가
    # 근무표 생성을 다시 눌렀을 때만 교체된다. 서명은 기준 변경 감지(미리보기
    # 무효화·클라이언트 새로고침 유도)에만 쓴다.
    new_key = next_month_key
    signatures = ss.setdefault("schedule_signatures", {})
    new_signature = staffing_signature(ss, body.year, body.month)
    prior_signature = signatures.get(new_key)
    signatures[new_key] = new_signature
    staffing_changed = prior_signature is not None and prior_signature != new_signature

    archive = ss.setdefault("schedules_by_month", {})

    # 직전 달 입력 자동 채우기 (월 +1 진행 시).
    _maybe_autofill_prev_month(ss, previous_month_key, new_key, body.year, body.month)

    # 활성 슬롯을 대상 월의 보관본으로 맞춘다.
    ss["schedule_result"] = archive.get(new_key)
    ss["result_published"] = ss.get("published_by_month", {}).get(new_key, False)

    if previous_month_key != new_key or staffing_changed:
        ss["schedule_revision"] = int(ss.get("schedule_revision", 0)) + 1
        ss["schedule_previews"] = {}

    save_ward_state(user.ward_id, ss)
    return _requirements_out(ss)
