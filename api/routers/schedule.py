from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import (
    AssistantRowOut,
    ChecklistItemOut,
    NurseStatsOut,
    PublishIn,
    ScheduleAssignmentOut,
    ScheduleOut,
    ScheduleRequestOut,
)
from api.state_store import load_ward_state, resolve_ward_settings, save_ward_state
from core.models import (
    DayRequirement,
    DutyRequest,
    ShiftRequirement,
    ShiftType,
    build_month_requirements,
    month_dates,
)
from core.solver import generate_schedule
from core.validator import validate_schedule

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


def _selected_holidays(ss: dict, year: int, month: int) -> set[date]:
    result = set()
    for raw in ss.get("selected_holidays", set()):
        try:
            day = date.fromisoformat(str(raw))
        except ValueError:
            continue
        if day.year == year and day.month == month:
            result.add(day)
    return result


def _date_overrides(ss: dict) -> dict[date, DayRequirement]:
    overrides: dict[date, DayRequirement] = {}
    for row in ss.get("date_override_rows", []):
        raw = row.get("date") or row.get("날짜")
        if not raw:
            continue
        try:
            day = date.fromisoformat(str(raw))
            d_count = int(row["D"])
            e_count = int(row["E"])
            n_count = int(row["N"])
        except (KeyError, TypeError, ValueError):
            continue
        overrides[day] = DayRequirement(
            day=day,
            D=ShiftRequirement(d_count, d_count, d_count),
            E=ShiftRequirement(e_count, e_count, e_count),
            N=ShiftRequirement(n_count, n_count, n_count),
        )
    return overrides


def _requirements(ss: dict, year: int, month: int) -> dict[date, DayRequirement]:
    if "weekday_template" not in ss or "weekend_template" not in ss:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "인원 기준이 설정되지 않았습니다.")
    return build_month_requirements(
        year,
        month,
        ss["weekday_template"],
        ss["weekend_template"],
        _date_overrides(ss),
    )


def _off_target(ss: dict, year: int, month: int) -> dict[str, int]:
    holidays = _selected_holidays(ss, year, month)
    weekend_count = sum(1 for day in month_dates(year, month) if day.weekday() >= 5)
    value = weekend_count + len(holidays)
    return {nurse.name: value for nurse in ss.get("nurses", [])}


def _charge_cells(ss: dict, result) -> list[str]:
    """날짜·근무별 차지 담당자 셀을 "이름|날짜"로 반환한다.

    그날 그 근무 배정자 중 차지 가능자(can_charge)를 명단 순서(상위)로 골라:
      D → 상위 2명, E·N → 상위 1명 (단 그 근무가 4명이고 차지가능자 2명 이상이면 상위 2명).
    차지 가능자가 부족하면 있는 만큼만 표시한다.
    """
    nurses = ss.get("nurses", [])
    order = {nurse.name: i for i, nurse in enumerate(nurses)}
    can_charge = {nurse.name for nurse in nurses if nurse.can_charge}
    days = month_dates(int(ss.get("year", 2026)), int(ss.get("month", 7)))

    cells: list[str] = []
    for day in days:
        for shift in (ShiftType.D, ShiftType.E, ShiftType.N):
            assigned = [
                name
                for name in (n.name for n in nurses)
                if result.assignments.get((name, day)) == shift
            ]
            chargeable = sorted((n for n in assigned if n in can_charge), key=lambda n: order[n])
            if shift is ShiftType.D:
                pick = 2
            else:
                pick = 2 if (len(assigned) == 4 and len(chargeable) >= 2) else 1
            for name in chargeable[:pick]:
                cells.append(f"{name}|{day.isoformat()}")
    return cells


def _request_out(req: DutyRequest) -> ScheduleRequestOut:
    return ScheduleRequestOut(
        nurse_name=req.nurse_name,
        date=req.day.isoformat(),
        requested_shift=req.requested_shift.value,
        kind=getattr(req, "kind", "prefer"),
    )


def _build_report(ss: dict):
    result = ss.get("schedule_result")
    if result is None or not result.feasible:
        return None
    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    return validate_schedule(
        ss.get("nurses", []),
        year,
        month,
        result.assignments,
        _requirements(ss, year, month),
        _off_target(ss, year, month),
        settings=resolve_ward_settings(ss),
    )


def _is_active(req: DutyRequest) -> bool:
    return getattr(req, "decision", "force") != "ignore"


def _is_off_prefer(req: DutyRequest) -> bool:
    return getattr(req, "kind", "prefer") == "prefer" and req.requested_shift in (ShiftType.O, ShiftType.AL)


def _stats_out(report) -> dict[str, NurseStatsOut]:
    per_nurse = report.stats.get("개인별", {}) if report is not None else {}
    return {
        name: NurseStatsOut(
            worked=row["근무"],
            n_count=row["N"],
            off_count=row["O"],
            annual_leave=row["연차"],
            annual_leave_target=str(row["연차목표"]),
            off_delta=row["오프편차"],
        )
        for name, row in per_nurse.items()
    }


def _assistant_rows(ss: dict) -> list[AssistantRowOut]:
    """보조 인력의 활성 '희망' 신청만 표에 찍는다. 제외 신청은 표시하지 않는다."""
    assistants = ss.get("assistants", [])
    names = {assistant.name for assistant in assistants}
    marks: dict[str, dict[str, str]] = {name: {} for name in names}
    for req in ss.get("duty_requests", []):
        if req.nurse_name not in names or not _is_active(req):
            continue
        if getattr(req, "kind", "prefer") != "prefer":
            continue
        shift = req.requested_shift
        label = "O" if shift in (ShiftType.O, ShiftType.AL) else shift.value
        marks[req.nurse_name][req.day.isoformat()] = label
    return [AssistantRowOut(name=assistant.name, marks=marks[assistant.name]) for assistant in assistants]


def _checklist_out(report, ss: dict, result) -> list[ChecklistItemOut]:
    rows = list(getattr(report, "checklist", []) or []) if report is not None else []
    items = [
        ChecklistItemOut(
            item=str(row["항목"]),
            subject=str(row["대상"]),
            expected=str(row["기준(입력)"]),
            actual=str(row["실제"]),
            ok=bool(row["반영"]),
        )
        for row in rows
    ]
    nurse_names = {nurse.name for nurse in ss.get("nurses", [])}
    forced = [
        req for req in ss.get("duty_requests", []) if _is_active(req) and req.nurse_name in nurse_names
    ]
    if forced:
        dropped = len(result.dropped_duty_requests)
        items.append(
            ChecklistItemOut(
                item="듀티 신청",
                subject="전체",
                expected=f"강제반영 {len(forced)}건",
                actual=f"{len(result.honored_duty_requests)}건 반영 / {dropped}건 미반영",
                ok=dropped == 0,
            )
        )
    return items


def _schedule_out(ss: dict, user: CurrentUser) -> ScheduleOut:
    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    result = ss.get("schedule_result")
    published = bool(ss.get("result_published", False))
    visible = user.is_admin or published
    if result is None or not visible:
        return ScheduleOut(year=year, month=month, published=published, visible=visible)

    assignments = [
        ScheduleAssignmentOut(nurse_name=name, date=day.isoformat(), shift=shift.value)
        for (name, day), shift in sorted(result.assignments.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    report = _build_report(ss)
    assistant_rows = _assistant_rows(ss)
    out = ScheduleOut(
        year=year,
        month=month,
        published=published,
        visible=visible,
        feasible=result.feasible,
        objective_value=result.objective_value,
        infeasible_categories=list(result.infeasible_categories),
        assignments=assignments,
        nurse_names=[nurse.name for nurse in ss.get("nurses", [])],
        honored_requests=[_request_out(req) for req in result.honored_duty_requests],
        dropped_requests=[_request_out(req) for req in result.dropped_duty_requests],
        validation_ok=None if report is None else report.ok,
        violations=[] if report is None else list(report.violations),
        dates=[day.isoformat() for day in month_dates(year, month)],
        holidays=sorted(day.isoformat() for day in _selected_holidays(ss, year, month)),
        stats=_stats_out(report),
        assistant_rows=assistant_rows,
        charge_cells=_charge_cells(ss, result),
        helper_names=[n.name for n in ss.get("nurses", []) if n.is_helper],
    )
    if not user.is_admin:
        return out

    all_requests = ss.get("duty_requests", [])
    ignored = [req for req in all_requests if not _is_active(req)]
    # 보조 인력 희망 신청은 표에 그대로 찍히므로 반영으로 집계한다.
    out.checklist = _checklist_out(report, ss, result)
    out.total_requests = len(all_requests)
    out.honored_count = len(result.honored_duty_requests) + sum(len(row.marks) for row in assistant_rows)
    out.unreflected_count = len(result.dropped_duty_requests) + len(ignored)
    out.dropped_off_count = sum(
        1 for req in [*result.dropped_duty_requests, *ignored] if _is_off_prefer(req)
    )
    return out


@router.get("", response_model=ScheduleOut)
def get_schedule(user: CurrentUser = Depends(get_current_user)) -> ScheduleOut:
    return _schedule_out(load_ward_state(user.ward_id), user)


@router.post("/generate", response_model=ScheduleOut)
def generate(user: CurrentUser = Depends(require_admin)) -> ScheduleOut:
    ss = load_ward_state(user.ward_id)
    nurses = ss.get("nurses", [])
    if not nurses:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "간호사 명단을 먼저 입력하세요.")

    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    requirements = _requirements(ss, year, month)
    off_target = _off_target(ss, year, month)
    nurse_names = {nurse.name for nurse in nurses}
    duty_requests = [
        req
        for req in ss.get("duty_requests", [])
        if req.nurse_name in nurse_names
    ]
    result = generate_schedule(
        nurses,
        year,
        month,
        requirements,
        off_target,
        duty_requests=duty_requests,
        time_limit_seconds=60.0,
        settings=resolve_ward_settings(ss),
    )
    ss["schedule_result"] = result
    ss["result_published"] = False
    save_ward_state(user.ward_id, ss)
    return _schedule_out(ss, user)


@router.put("/publish", response_model=ScheduleOut)
def publish(body: PublishIn, user: CurrentUser = Depends(require_admin)) -> ScheduleOut:
    ss = load_ward_state(user.ward_id)
    result = ss.get("schedule_result")
    if body.published and (result is None or not result.feasible):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "공개할 수 있는 근무표가 없습니다.")
    ss["result_published"] = body.published
    save_ward_state(user.ward_id, ss)
    return _schedule_out(ss, user)
