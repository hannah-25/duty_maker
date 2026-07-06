from datetime import date, timedelta

import pytest
from ortools.sat.python import cp_model

from core.constraints import ScheduleModel
from core.holidays_kr import get_month_holidays
from core.models import (
    DutyRequest,
    Nurse,
    NurseLevel,
    ShiftRequirement,
    ShiftType,
    build_month_requirements,
    compute_month_off_target,
    month_dates,
)
from core.sample_data import build_real_nurses, ward_templates
from core.solver import generate_schedule
from core.validator import validate_schedule

YEAR, MONTH = 2026, 7


def _isolated_workday_penalty_for(sequence):
    nurse = Nurse(name="a", can_charge=True)
    days = [date(2026, 1, i) for i in range(1, len(sequence) + 1)]
    lookback = [date(2025, 12, 31)]
    sm = ScheduleModel(
        [nurse],
        days,
        lookback,
        {("a", lookback[0]): ShiftType.O},
        {},
        {"a": 0},
    )
    for day, shift in zip(days, sequence):
        sm.model.Add(sm.val("a", day, shift) == 1)
    sm._soft_avoid_isolated_workday()
    sm.model.Minimize(sum(sm.objective_terms()))

    solver = cp_model.CpSolver()
    status = solver.Solve(sm.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return sum(
        solver.Value(var)
        for category, _weight, var in sm.penalties
        if category == "isolated_workday"
    )


def test_soft_penalizes_rest_work_rest_pattern():
    assert _isolated_workday_penalty_for([ShiftType.O, ShiftType.D, ShiftType.O]) == 1


def test_soft_does_not_penalize_multi_day_work_block():
    assert _isolated_workday_penalty_for([ShiftType.O, ShiftType.D, ShiftType.D]) == 0


def test_nurse_levels_set_role_capabilities():
    senior = Nurse(name="senior", level=NurseLevel.SENIOR_CHARGE)
    middle = Nurse(name="middle", level=NurseLevel.MIDDLE)
    junior = Nurse(name="junior", level=NurseLevel.JUNIOR)
    new_junior = Nurse(name="new", level=NurseLevel.NEW_JUNIOR)

    assert senior.can_charge and not senior.can_act
    assert middle.can_charge and middle.can_act
    assert not junior.can_charge and junior.can_act
    assert not new_junior.can_charge and new_junior.can_act and new_junior.is_new_junior


def test_soft_penalizes_new_junior_overlap():
    nurses = [
        Nurse(name="new1", level=NurseLevel.NEW_JUNIOR),
        Nurse(name="new2", level=NurseLevel.NEW_JUNIOR),
    ]
    days = [date(2026, 1, 1)]
    sm = ScheduleModel(nurses, days, [], {}, {}, {"new1": 0, "new2": 0})
    for nurse in nurses:
        sm.model.Add(sm.val(nurse.name, days[0], ShiftType.D) == 1)
    sm._soft_avoid_new_junior_overlap()
    sm.model.Minimize(sum(sm.objective_terms()))

    solver = cp_model.CpSolver()
    status = solver.Solve(sm.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(
        solver.Value(var)
        for category, _weight, var in sm.penalties
        if category == "new_junior_overlap"
    ) == 1


@pytest.fixture(scope="module")
def solved():
    nurses = build_real_nurses()
    weekday_template, weekend_template = ward_templates()
    requirements = build_month_requirements(YEAR, MONTH, weekday_template, weekend_template)
    holidays = get_month_holidays(YEAR, MONTH)
    target = compute_month_off_target(YEAR, MONTH, holidays)
    off_target = {n.name: target for n in nurses}
    result = generate_schedule(nurses, YEAR, MONTH, requirements, off_target, time_limit_seconds=60)
    assert result.feasible, f"실제 명단이 실행불가로 나옴: {result.infeasible_categories}"
    return nurses, requirements, off_target, result


def test_validator_passes_all_hard_rules(solved):
    """전수 검증기 통과 = 모든 하드 규칙(일별 인원, 개인 규칙, 오프 상한 등) 준수."""
    nurses, requirements, off_target, result = solved
    report = validate_schedule(nurses, YEAR, MONTH, result.assignments, requirements, off_target)
    assert report.ok, report.summary()


def test_daily_n_exactly_3(solved):
    nurses, requirements, off_target, result = solved
    for day in month_dates(YEAR, MONTH):
        n_count = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.N)
        assert n_count == 3, f"{day}: N {n_count}명 (정확히 3명이어야 함)"


def test_daily_staffing_within_range(solved):
    nurses, requirements, off_target, result = solved
    for day in month_dates(YEAR, MONTH):
        req = requirements[day]
        d = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.D)
        e = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.E)
        s = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.S)
        assert req.D.minimum <= d + s <= req.D.maximum, f"{day}: D+S={d + s}"
        assert req.E.minimum <= e + s <= req.E.maximum, f"{day}: E+S={e + s}"
        assert s <= 1


def test_off_count_never_exceeds_target(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        o_count = sum(1 for d in days if result.assignments[(nurse.name, d)] == ShiftType.O)
        assert o_count <= off_target[nurse.name], (
            f"{nurse.name}: O {o_count} > 목표 {off_target[nurse.name]}"
        )


def test_july_off_target_is_9(solved):
    # 2026년 7월 = 주말 8일 + 제헌절 1일 (병동 기준 공휴일)
    nurses, requirements, off_target, result = solved
    assert all(t == 9 for t in off_target.values())


def test_n_monthly_count_in_range_6_to_8(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        if nurse.n_excluded or nurse.dedicated_shift is not None:
            continue
        n_count = sum(1 for d in days if result.assignments[(nurse.name, d)] == ShiftType.N)
        assert 6 <= n_count <= 8, f"{nurse.name}: 월 N {n_count}개 (6~8 허용)"


def test_weekday_only_nurse_rests_all_weekends(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in (n for n in nurses if n.weekday_only):
        for day in days:
            if day.weekday() >= 5:
                assert result.assignments[(nurse.name, day)] in (ShiftType.O, ShiftType.AL), (
                    f"{nurse.name} {day}: 평일만 근무자인데 주말 근무"
                )


def test_n_then_2off_after_block_end(solved):
    # 나이트 블록(연속 N)이 끝난 뒤 2일은 반드시 오프(O/연차).
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    day_set = set(days)
    for nurse in nurses:
        for day in days:
            if result.assignments[(nurse.name, day)] != ShiftType.N:
                continue
            nd1 = day + timedelta(days=1)
            if nd1 not in day_set:
                continue  # 월말 경계 - 다음달 생성 시 lookback으로 검증됨
            if result.assignments[(nurse.name, nd1)] == ShiftType.N:
                continue  # 블록 계속
            for offset in (1, 2):
                nd = day + timedelta(days=offset)
                if nd in day_set:
                    assert result.assignments[(nurse.name, nd)] in (ShiftType.O, ShiftType.AL)


def test_e_then_d_forbidden(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    day_set = set(days)
    for nurse in nurses:
        for day in days:
            if result.assignments[(nurse.name, day)] == ShiftType.E:
                nd = day + timedelta(days=1)
                if nd in day_set:
                    assert result.assignments[(nurse.name, nd)] not in (ShiftType.D, ShiftType.S)


def test_max_5_consecutive_workdays(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        consecutive = 0
        for day in days:
            if result.assignments[(nurse.name, day)] in (ShiftType.O, ShiftType.AL):
                consecutive = 0
            else:
                consecutive += 1
                assert consecutive <= 5, f"{nurse.name}가 6일 이상 연속 근무"


def test_max_3_consecutive_nights(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        consecutive = 0
        for day in days:
            if result.assignments[(nurse.name, day)] == ShiftType.N:
                consecutive += 1
                assert consecutive <= 3, f"{nurse.name}가 나이트 4일 이상 연속"
            else:
                consecutive = 0


def test_dedicated_and_charge_rules(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in (n for n in nurses if n.dedicated_shift is not None):
        for day in days:
            shift = result.assignments[(nurse.name, day)]
            assert shift in (nurse.dedicated_shift, ShiftType.O, ShiftType.AL)
    for day in days:
        for shift in (ShiftType.D, ShiftType.E, ShiftType.N):
            assigned = [n for n in nurses if result.assignments[(n.name, day)] == shift]
            if assigned:
                assert any(n.can_charge for n in assigned), f"{day} {shift.value} 차지가능자 없음"


def test_s_only_junior_or_new_junior_staff(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        if nurse.level not in (NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR):
            for day in days:
                assert result.assignments[(nurse.name, day)] != ShiftType.S


def test_daily_d_has_at_least_two_charge_capable_staff(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for day in days:
        charge_d = sum(
            1
            for nurse in nurses
            if nurse.can_charge
            and result.assignments[(nurse.name, day)] == ShiftType.D
        )
        assert charge_d >= 2, f"{day}: D charge-capable staff {charge_d} < 2"


def test_senior_same_shift_cap(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    seniors = [n for n in nurses if n.level == NurseLevel.SENIOR_CHARGE]
    for day in days:
        for shift in (ShiftType.D, ShiftType.E):
            senior_count = sum(
                1 for nurse in seniors if result.assignments[(nurse.name, day)] == shift
            )
            assert senior_count <= 2, f"{day} {shift.value}: senior staff {senior_count} > 2"
        senior_n = sum(
            1 for nurse in seniors if result.assignments[(nurse.name, day)] == ShiftType.N
        )
        assert senior_n == 1, f"{day} N: senior staff {senior_n} != 1"


def test_conflicting_duty_requests_report_dropped_request():
    nurses = [Nurse(name=f"n{i}", can_charge=True) for i in range(6)]
    template = (
        ShiftRequirement(minimum=2, maximum=2),
        ShiftRequirement(minimum=0, maximum=0),
        ShiftRequirement(minimum=0, maximum=0),
    )
    requirements = build_month_requirements(YEAR, MONTH, template, template)
    off_target = {n.name: 0 for n in nurses}
    day = date(YEAR, MONTH, 1)
    duty_requests = [
        DutyRequest("n0", day, ShiftType.D),
        DutyRequest("n0", day, ShiftType.O),
    ]

    result = generate_schedule(
        nurses,
        YEAR,
        MONTH,
        requirements,
        off_target,
        duty_requests=duty_requests,
        n_monthly_range=(0, 31),
        time_limit_seconds=10,
    )

    assert result.feasible
    assert len(result.honored_duty_requests) == 1
    assert len(result.dropped_duty_requests) == 1


# ---------------------------------------------------------------- infeasible --
def test_infeasible_when_min_staffing_impossible():
    nurses = [Nurse(name="a", can_charge=True), Nurse(name="b", can_charge=True)]
    template = (
        ShiftRequirement(minimum=5, maximum=5),
        ShiftRequirement(minimum=1, maximum=1),
        ShiftRequirement(minimum=1),
    )
    requirements = build_month_requirements(YEAR, MONTH, template, template)
    off_target = {n.name: 0 for n in nurses}
    result = generate_schedule(
        nurses, YEAR, MONTH, requirements, off_target, n_monthly_range=(0, 31)
    )
    assert not result.feasible
    assert "staffing_range" in result.infeasible_categories


def test_infeasible_when_all_nurses_night_excluded():
    nurses = [Nurse(name=f"n{i}", can_charge=True, n_excluded=True) for i in range(3)]
    template = (
        ShiftRequirement(minimum=1, maximum=1),
        ShiftRequirement(minimum=1, maximum=1),
        ShiftRequirement(minimum=1),
    )
    requirements = build_month_requirements(YEAR, MONTH, template, template)
    off_target = {n.name: 0 for n in nurses}
    result = generate_schedule(
        nurses, YEAR, MONTH, requirements, off_target, n_monthly_range=(0, 31)
    )
    assert not result.feasible
    assert "n_excluded" in result.infeasible_categories
    assert "staffing_range" in result.infeasible_categories
