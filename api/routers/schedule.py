from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import CurrentUser, get_current_user, require_admin
from api.schemas import (
    AssistantRowOut,
    ChecklistItemOut,
    ManualAssignmentIn,
    NurseStatsOut,
    PrevMonthIn,
    PrevMonthOut,
    PublishIn,
    RegenerateApplyIn,
    RegeneratePreviewIn,
    ScheduleAssignmentOut,
    ScheduleOut,
    ScheduleRequestOut,
)
from api.state_store import (
    load_ward_state,
    prev_month_history,
    resolve_ward_settings,
    save_ward_state,
    staffing_signature,
)
from core.models import (
    DayRequirement,
    DutyRequest,
    ShiftRequirement,
    ShiftType,
    build_month_requirements,
    lookback_dates,
    month_dates,
    month_key,
)
from core.solver import _split_duty_requests, generate_schedule
from core.validator import validate_schedule

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

TRINITY_A_WARD_ID = "bb5d9d97767667e6"


def _solver_settings(ss: dict, user: CurrentUser) -> dict:
    settings = resolve_ward_settings(ss)
    if user.ward_id == TRINITY_A_WARD_ID:
        settings["trinity_a_pair_overlap"] = True
    return settings


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


def _infeasibility_messages(ss: dict, categories: list[str]) -> list[str]:
    """Turn solver diagnostics into operational guidance for administrators."""
    year, month = int(ss.get("year", 2026)), int(ss.get("month", 7))
    days = month_dates(year, month)
    requirements = _requirements(ss, year, month)
    target_by_nurse = _off_target(ss, year, month)
    minimum_slots = sum(row.D.minimum + row.E.minimum + row.N.minimum for row in requirements.values())
    available_slots = 0
    for nurse in ss.get("nurses", []):
        if nurse.is_helper:
            continue
        target = target_by_nurse.get(nurse.name, 0)
        if nurse.is_night_dedicated:
            available_slots += nurse.max_n_hard
            continue
        max_workdays = len(days) - target - (nurse.al_target or 0)
        if nurse.weekday_only:
            max_workdays = min(max_workdays, sum(day.weekday() < 5 for day in days))
        available_slots += max(0, max_workdays)

    messages: list[str] = []
    if available_slots < minimum_slots:
        shortage = minimum_slots - available_slots
        messages.extend([
            f"필요 최소 근무 칸은 {minimum_slots}칸인데, 현재 OFF·연차·전담 조건으로 가능한 근무 칸은 {available_slots}칸입니다. {shortage}칸이 부족합니다.",
            "해결 방법: 일별 최소 인원을 합계 1칸 이상 낮추거나, 추가 인력을 투입하거나, 야간 전담자의 월 야간 횟수/전담 조건을 조정하세요.",
        ])

    labels = {
        "off_cap": "OFF 목표 수를 모든 근무자에게 정확히 적용할 수 없습니다.",
        "al_target": "설정된 연차 목표와 다른 하드 제약이 충돌합니다.",
        "fixed_assignments": "수동으로 고정한 듀티 또는 부분 재생성의 고정 영역이 다른 규칙과 충돌합니다.",
        "e_then_d": "같은 사람의 E 다음 날 D/S 배정이 충돌합니다.",
        "n_then_2off": "야간 근무 뒤 2일 휴식 규칙이 충돌합니다.",
        "staffing_range": "일별 최소/최대 인력 조건이 충돌합니다.",
        "charge_placement": "필요한 차지 간호사를 각 근무에 배치할 수 없습니다.",
        "charge_minimum": "근무별 차지 간호사 최소 인원 조건을 충족할 수 없습니다.",
        "allowed_shifts": "개인별 가능한 근무 종류 제한 때문에 배정할 수 없습니다.",
    }
    for category in categories:
        if category in labels:
            messages.append(labels[category])
        elif category.startswith("solver_status_"):
            messages.append("세부 충돌 원인을 계산하지 못했습니다. 위 인력 수와 수동 고정 듀티를 먼저 확인하세요.")
    return messages or ["현재 인력·요청·하드 제약의 조합으로는 근무표를 만들 수 없습니다."]


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


def _build_report(ss: dict, user: CurrentUser):
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
        settings=_solver_settings(ss, user),
    )


def _is_active(req: DutyRequest) -> bool:
    return getattr(req, "decision", "force") != "ignore"


def _requests_for_month(
    ss: dict, nurse_names: set[str], year: int, month: int
) -> list[DutyRequest]:
    return [
        req
        for req in ss.get("duty_requests", [])
        if req.nurse_name in nurse_names
        and req.day.year == year
        and req.day.month == month
    ]


def _revision(ss: dict) -> int:
    return int(ss.get("schedule_revision", 0))


def _bump_revision(ss: dict) -> None:
    ss["schedule_revision"] = _revision(ss) + 1
    ss["schedule_previews"] = {}


def _manual_assignments(ss: dict, year: int, month: int) -> dict[tuple[str, date], ShiftType]:
    assignments: dict[tuple[str, date], ShiftType] = {}
    for key, raw_shift in (ss.get("manual_overrides") or {}).items():
        try:
            nurse_name, raw_day = key.split("|", 1)
            day = date.fromisoformat(raw_day)
            shift = ShiftType(raw_shift)
        except (AttributeError, TypeError, ValueError):
            continue
        if day.year == year and day.month == month:
            assignments[(nurse_name, day)] = shift
    return assignments


def _validate_selected_cells(ss: dict, cells, year: int, month: int) -> set[tuple[str, date]]:
    nurses = {nurse.name for nurse in ss.get("nurses", []) if not nurse.is_helper}
    selected: set[tuple[str, date]] = set()
    for cell in cells:
        try:
            day = date.fromisoformat(cell.date)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "날짜 형식이 올바르지 않습니다.") from exc
        if cell.nurse_name not in nurses or day.year != year or day.month != month:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "근무표에 없는 셀이 포함되어 있습니다.")
        selected.add((cell.nurse_name, day))
    if not selected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "재생성할 셀을 선택하세요.")
    return selected


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
    year = int(ss.get("year", 2026))
    month = int(ss.get("month", 7))
    nurse_names = {nurse.name for nurse in ss.get("nurses", [])}
    forced = [
        req
        for req in _requests_for_month(ss, nurse_names, year, month)
        if _is_active(req)
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
        return ScheduleOut(
            year=year, month=month, published=published, visible=visible, revision=_revision(ss)
        )

    assignments = [
        ScheduleAssignmentOut(nurse_name=name, date=day.isoformat(), shift=shift.value)
        for (name, day), shift in sorted(result.assignments.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    report = _build_report(ss, user)
    assistant_rows = _assistant_rows(ss)
    out = ScheduleOut(
        year=year,
        month=month,
        published=published,
        visible=visible,
        revision=_revision(ss),
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
        manual_override_cells=sorted((ss.get("manual_overrides") or {}).keys()),
    )
    if not user.is_admin:
        return out

    all_requests = _requests_for_month(ss, set(out.nurse_names), year, month)
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
    # Missing prior-month history is treated as OFF by prev_month_history().
    requirements = _requirements(ss, year, month)
    off_target = _off_target(ss, year, month)
    nurse_names = {nurse.name for nurse in nurses}
    duty_requests = _requests_for_month(ss, nurse_names, year, month)
    result = generate_schedule(
        nurses,
        year,
        month,
        requirements,
        off_target,
        history=prev_month_history(ss, year, month),
        duty_requests=duty_requests,
        time_limit_seconds=60.0,
        settings=_solver_settings(ss, user),
        fixed_assignments=_manual_assignments(ss, year, month),
    )
    if not result.feasible:
        result.infeasible_categories = _infeasibility_messages(ss, result.infeasible_categories)
    ss["schedule_result"] = result
    ss["result_published"] = False
    ss.setdefault("schedule_signatures", {})[month_key(year, month)] = staffing_signature(
        ss, year, month
    )
    _bump_revision(ss)
    save_ward_state(user.ward_id, ss)
    return _schedule_out(ss, user)


@router.patch("/assignment", response_model=ScheduleOut)
def update_assignment(
    body: ManualAssignmentIn, user: CurrentUser = Depends(require_admin)
) -> ScheduleOut:
    ss = load_ward_state(user.ward_id)
    result = ss.get("schedule_result")
    if result is None or not result.feasible:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "먼저 실행 가능한 근무표를 생성하세요.")
    if body.expected_revision != _revision(ss):
        raise HTTPException(status.HTTP_409_CONFLICT, "근무표가 변경되었습니다. 새로고침 후 다시 시도하세요.")
    year, month = int(ss["year"]), int(ss["month"])
    selected = _validate_selected_cells(ss, [body], year, month)
    key = next(iter(selected))
    override_key = f"{body.nurse_name}|{body.date}"
    overrides = ss.setdefault("manual_overrides", {})
    if body.shift is None:
        overrides.pop(override_key, None)
    else:
        try:
            shift = ShiftType(body.shift)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "지원하지 않는 근무 코드입니다.") from exc
        # 수동 편집은 한 칸씩(증분) 이뤄지므로, 인원 하한·상한은 여기서 하드로
        # 막지 않는다(그러면 다중 칸 재배치의 중간 상태가 전부 거부된다).
        # 위반은 검증 리포트의 '일별 인원 기준' 경고로 관리자에게 표시된다.
        candidate_assignments = dict(result.assignments)
        candidate_assignments[key] = shift
        result.assignments = candidate_assignments
        overrides[override_key] = shift.value
    active_requests = [
        request for request in _requests_for_month(
            ss, {nurse.name for nurse in ss.get("nurses", [])}, year, month
        ) if _is_active(request)
    ]
    result.honored_duty_requests, result.dropped_duty_requests = _split_duty_requests(
        result.assignments, active_requests
    )
    ss["result_published"] = False
    _bump_revision(ss)
    save_ward_state(user.ward_id, ss)
    return _schedule_out(ss, user)


@router.post("/regenerate-preview")
def regenerate_preview(
    body: RegeneratePreviewIn, user: CurrentUser = Depends(require_admin)
):
    ss = load_ward_state(user.ward_id)
    original = ss.get("schedule_result")
    if original is None or not original.feasible:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "먼저 실행 가능한 근무표를 생성하세요.")
    if body.expected_revision != _revision(ss):
        raise HTTPException(status.HTTP_409_CONFLICT, "근무표가 변경되었습니다. 새로고침 후 다시 시도하세요.")
    year, month = int(ss["year"]), int(ss["month"])
    selected = _validate_selected_cells(ss, body.cells, year, month)
    manual = _manual_assignments(ss, year, month)
    movable = selected - set(manual)
    if not movable:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "선택한 셀이 모두 수동 수정으로 고정되어 있습니다.")

    fixed = {
        key: shift for key, shift in original.assignments.items()
        if key not in selected
    }
    fixed.update(manual)
    candidate = generate_schedule(
        ss.get("nurses", []), year, month, _requirements(ss, year, month), _off_target(ss, year, month),
        history=prev_month_history(ss, year, month),
        duty_requests=_requests_for_month(ss, {n.name for n in ss.get("nurses", [])}, year, month),
        time_limit_seconds=60.0, settings=_solver_settings(ss, user), fixed_assignments=fixed,
    )
    if not candidate.feasible:
        guidance = _infeasibility_messages(ss, candidate.infeasible_categories)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "선택 영역만으로는 조건을 만족하는 근무표를 만들 수 없습니다. "
            + " ".join(guidance),
        )
    changed = [
        ScheduleAssignmentOut(nurse_name=name, date=day.isoformat(), shift=shift.value)
        for (name, day), shift in sorted(candidate.assignments.items())
        if (name, day) in selected and original.assignments.get((name, day)) != shift
    ]
    preview_id = uuid4().hex
    ss.setdefault("schedule_previews", {})[preview_id] = {
        "base_revision": _revision(ss), "selected_keys": [f"{name}|{day.isoformat()}" for name, day in selected],
        "result": candidate,
    }
    save_ward_state(user.ward_id, ss)
    preview_state = dict(ss)
    preview_state["schedule_result"] = candidate
    return {
        "preview_id": preview_id, "revision": _revision(ss), "changed_count": len(changed),
        "changed_cells": [row.model_dump() for row in changed],
        "schedule": _schedule_out(preview_state, user).model_dump(),
    }


@router.post("/regenerate-apply", response_model=ScheduleOut)
def apply_regeneration(
    body: RegenerateApplyIn, user: CurrentUser = Depends(require_admin)
) -> ScheduleOut:
    ss = load_ward_state(user.ward_id)
    preview = (ss.get("schedule_previews") or {}).get(body.preview_id)
    if preview is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "미리보기를 찾을 수 없습니다.")
    if int(preview.get("base_revision", -1)) != _revision(ss):
        raise HTTPException(status.HTTP_409_CONFLICT, "근무표가 변경되어 미리보기를 적용할 수 없습니다.")
    ss["schedule_result"] = preview["result"]
    ss["result_published"] = False
    _bump_revision(ss)
    save_ward_state(user.ward_id, ss)
    return _schedule_out(ss, user)


@router.delete("/regenerate-preview/{preview_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_regeneration(preview_id: str, user: CurrentUser = Depends(require_admin)):
    ss = load_ward_state(user.ward_id)
    previews = ss.setdefault("schedule_previews", {})
    if preview_id in previews:
        del previews[preview_id]
        save_ward_state(user.ward_id, ss)


@router.put("/publish", response_model=ScheduleOut)
def publish(body: PublishIn, user: CurrentUser = Depends(require_admin)) -> ScheduleOut:
    ss = load_ward_state(user.ward_id)
    result = ss.get("schedule_result")
    if body.published and (result is None or not result.feasible):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "공개할 수 있는 근무표가 없습니다.")
    ss["result_published"] = body.published
    save_ward_state(user.ward_id, ss)
    return _schedule_out(ss, user)


def _prev_month_out(ss: dict, year: int, month: int) -> PrevMonthOut:
    key = month_key(year, month)
    dates = [day.isoformat() for day in lookback_dates(year, month, 5)]
    date_set = set(dates)
    stored = (ss.get("prev_month_inputs") or {}).get(key, {})
    nurse_names = [nurse.name for nurse in ss.get("nurses", []) if not nurse.is_helper]
    values = {
        name: {iso: shift for iso, shift in (stored.get(name) or {}).items() if iso in date_set}
        for name in nurse_names
    }
    return PrevMonthOut(
        year=year,
        month=month,
        dates=dates,
        nurse_names=nurse_names,
        values=values,
        confirmed=key in (ss.get("prev_month_inputs") or {}),
    )


@router.get("/prev-month", response_model=PrevMonthOut)
def get_prev_month(user: CurrentUser = Depends(require_admin)) -> PrevMonthOut:
    ss = load_ward_state(user.ward_id)
    return _prev_month_out(ss, int(ss.get("year", 2026)), int(ss.get("month", 7)))


@router.put("/prev-month", response_model=PrevMonthOut)
def put_prev_month(
    body: PrevMonthIn, user: CurrentUser = Depends(require_admin)
) -> PrevMonthOut:
    ss = load_ward_state(user.ward_id)
    year, month = int(ss.get("year", 2026)), int(ss.get("month", 7))
    valid_dates = {day.isoformat() for day in lookback_dates(year, month, 5)}
    nurse_names = {nurse.name for nurse in ss.get("nurses", []) if not nurse.is_helper}
    cleaned: dict[str, dict[str, str]] = {}
    for name, days in (body.values or {}).items():
        if name not in nurse_names:
            continue
        row: dict[str, str] = {}
        for iso, raw_shift in (days or {}).items():
            if iso not in valid_dates:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "직전 달 날짜 범위를 벗어난 셀이 있습니다.")
            if raw_shift in (None, "", "O"):
                continue  # 오프는 기본값이라 저장하지 않는다(빈칸 = 오프).
            try:
                shift = ShiftType(raw_shift)
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "지원하지 않는 근무 코드입니다.") from exc
            row[iso] = shift.value
        if row:
            cleaned[name] = row
    # 키를 기록하면(빈 dict라도) '확정'으로 간주된다 — 전원 오프인 첫 달도 통과.
    ss.setdefault("prev_month_inputs", {})[month_key(year, month)] = cleaned
    save_ward_state(user.ward_id, ss)
    return _prev_month_out(ss, year, month)
