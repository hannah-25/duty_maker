from datetime import date, timedelta

import pytest
from ortools.sat.python import cp_model

from core.constraints import ScheduleModel
from core.holidays_kr import get_month_holidays
from core.models import (
    DutyRequest,
    DayRequirement,
    Nurse,
    NurseLevel,
    ShiftRequirement,
    ShiftType,
    build_month_requirements,
    compute_month_off_target,
    month_dates,
)
from core.sample_data import build_real_nurses, ward_templates
from core.solver import _split_duty_requests, generate_schedule
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


def test_off_target_is_hard_minimum_even_with_annual_leave_target():
    """Annual leave must not substitute for the monthly OFF target."""
    nurses = [
        Nurse(name="A", can_charge=True, al_target=1),
        Nurse(name="B", can_charge=True),
    ]
    days = [date(2026, 1, day) for day in range(1, 5)]
    requirements = {
        day: DayRequirement(day, ShiftRequirement(1), ShiftRequirement(0), ShiftRequirement(0))
        for day in days
    }
    sm = ScheduleModel(nurses, days, [], {}, requirements, {"A": 1, "B": 1})
    sm.add_tier1_hard_constraints()

    # A fulfills its annual-leave target but has no OFF.  B supplies the
    # remaining daily coverage, so this was feasible while OFF was only a cap.
    forced = {
        "A": [ShiftType.AL, ShiftType.D, ShiftType.D, ShiftType.D],
        "B": [ShiftType.D, ShiftType.AL, ShiftType.AL, ShiftType.O],
    }
    for nurse in nurses:
        for day, shift in zip(days, forced[nurse.name]):
            sm.model.Add(sm.val(nurse.name, day, shift) == 1)

    assert cp_model.CpSolver().Solve(sm.model) == cp_model.INFEASIBLE


def test_evening_off_day_pattern_is_allowed():
    """E → O → D is no longer a hard constraint."""
    nurse = Nurse(name="A", can_charge=True)
    days = [date(2026, 1, day) for day in range(5, 8)]
    requirements = {
        day: DayRequirement(
            day,
            ShiftRequirement(minimum=0, maximum=1),
            ShiftRequirement(minimum=0, maximum=1),
            ShiftRequirement(minimum=0, maximum=0),
        )
        for day in days
    }
    sm = ScheduleModel(
        [nurse],
        days,
        [],
        {},
        requirements,
        {nurse.name: 1},
        settings={
            "weekday_charge_D": 0,
            "weekday_charge_E": 0,
            "weekday_charge_N": 0,
            "weekend_charge_D": 0,
            "weekend_charge_E": 0,
            "weekend_charge_N": 0,
        },
    )
    sm.add_tier1_hard_constraints()
    for day, shift in zip(days, (ShiftType.E, ShiftType.O, ShiftType.D)):
        sm.model.Add(sm.val(nurse.name, day, shift) == 1)

    assert cp_model.CpSolver().Solve(sm.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_exact_off_allows_staffing_target_shortfall_within_hard_range():
    nurses = [Nurse(name=name, can_charge=True) for name in ("A", "B", "C")]
    days = [date(2026, 1, day) for day in range(5, 8)]
    requirements = {
        day: DayRequirement(
            day,
            ShiftRequirement(minimum=1, maximum=2, target=2),
            ShiftRequirement(minimum=1, maximum=1, target=1),
            ShiftRequirement(minimum=0, maximum=0, target=0),
        )
        for day in days
    }
    sm = ScheduleModel(
        nurses,
        days,
        [],
        {},
        requirements,
        {nurse.name: 1 for nurse in nurses},
        settings={
            "weekday_charge_D": 1,
            "weekday_charge_E": 1,
            "weekday_charge_N": 0,
            "weekend_charge_D": 1,
            "weekend_charge_E": 1,
            "weekend_charge_N": 0,
        },
    )
    sm.add_tier1_hard_constraints()
    sm.add_tier2_soft_constraints()
    sm.model.Minimize(sum(sm.objective_terms()))
    solver = cp_model.CpSolver()

    assert solver.Solve(sm.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for nurse in nurses:
        assert sum(solver.Value(sm.val(nurse.name, day, ShiftType.O)) for day in days) == 1
    assert any(
        sum(
            solver.Value(sm.val(nurse.name, day, ShiftType.D))
            for nurse in nurses
        ) < requirements[day].D.target
        for day in days
    )


def test_s_disabled_is_a_hard_constraint():
    nurse = Nurse(name="junior", level=NurseLevel.JUNIOR)
    day = date(2026, 1, 5)
    requirements = {
        day: DayRequirement(day, ShiftRequirement(1), ShiftRequirement(0), ShiftRequirement(0))
    }
    sm = ScheduleModel(
        [nurse],
        [day],
        [],
        {},
        requirements,
        {nurse.name: 0},
        settings={
            "use_s_shift": False,
            "weekday_charge_D": 0,
            "weekday_charge_E": 0,
            "weekday_charge_N": 0,
            "weekend_charge_D": 0,
            "weekend_charge_E": 0,
            "weekend_charge_N": 0,
        },
    )
    sm.add_tier1_hard_constraints()
    sm.model.Add(sm.val(nurse.name, day, ShiftType.S) == 1)

    assert cp_model.CpSolver().Solve(sm.model) == cp_model.INFEASIBLE


def test_s_enabled_adds_s_without_replacing_d_hard_staffing():
    """S는 별도 근무이며, D 하드 인원을 대체하면 안 된다."""
    day = date(2026, 1, 5)
    nurses = [
        Nurse(name="charge", level=NurseLevel.MIDDLE),
        Nurse(name="junior", level=NurseLevel.JUNIOR),
    ]
    requirements = {
        day: DayRequirement(day, ShiftRequirement(1), ShiftRequirement(0), ShiftRequirement(0))
    }
    sm = ScheduleModel(
        nurses,
        [day],
        [],
        {},
        requirements,
        {nurse.name: 0 for nurse in nurses},
        settings={
            "use_s_shift": True,
            "weekday_charge_D": 0,
            "weekday_charge_E": 0,
            "weekday_charge_N": 0,
            "weekend_charge_D": 0,
            "weekend_charge_E": 0,
            "weekend_charge_N": 0,
        },
    )
    sm.add_tier1_hard_constraints()
    sm.add_tier2_soft_constraints()
    sm.model.Minimize(sum(sm.objective_terms()))
    solver = cp_model.CpSolver()

    assert solver.Solve(sm.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert sum(solver.Value(sm.val(n.name, day, ShiftType.D)) for n in nurses) == 1
    assert sum(solver.Value(sm.val(n.name, day, ShiftType.S)) for n in nurses) == 1


def test_weekday_and_weekend_hard_staffing_ranges_are_independent():
    """평일·주말의 입력값은 각각의 하드 하한·상한으로 적용된다."""
    weekday, weekend = date(2026, 1, 9), date(2026, 1, 10)
    nurses = [Nurse(name=f"n{i}", level=NurseLevel.MIDDLE) for i in range(4)]
    requirements = {
        weekday: DayRequirement(weekday, ShiftRequirement(3), ShiftRequirement(1), ShiftRequirement(0)),
        weekend: DayRequirement(weekend, ShiftRequirement(2), ShiftRequirement(2), ShiftRequirement(0)),
    }
    sm = ScheduleModel(
        nurses,
        [weekday, weekend],
        [],
        {},
        requirements,
        {nurse.name: 0 for nurse in nurses},
        settings={
            "use_s_shift": False,
            "weekday_charge_D": 0,
            "weekday_charge_E": 0,
            "weekday_charge_N": 0,
            "weekend_charge_D": 0,
            "weekend_charge_E": 0,
            "weekend_charge_N": 0,
        },
    )
    sm.add_tier1_hard_constraints()
    solver = cp_model.CpSolver()

    assert solver.Solve(sm.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    for day in (weekday, weekend):
        assert sum(solver.Value(sm.val(n.name, day, ShiftType.D)) for n in nurses) == requirements[day].D.minimum
        assert sum(solver.Value(sm.val(n.name, day, ShiftType.E)) for n in nurses) == requirements[day].E.minimum


def _night_off_return_penalty_for(sequence):
    nurse = Nurse(name="a", can_charge=True)
    days = [date(2026, 1, i) for i in range(1, len(sequence) + 1)]
    sm = ScheduleModel([nurse], days, [], {}, {}, {"a": 0})
    for day, shift in zip(days, sequence):
        sm.model.Add(sm.val("a", day, shift) == 1)
    sm._soft_avoid_night_after_night_off()
    sm.model.Minimize(sum(sm.objective_terms()))

    solver = cp_model.CpSolver()
    assert solver.Solve(sm.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return sum(
        solver.Value(var)
        for category, _weight, var in sm.penalties
        if category == "night_off_return"
    )


def test_soft_penalizes_night_after_night_off():
    assert _night_off_return_penalty_for([ShiftType.N, ShiftType.O, ShiftType.O, ShiftType.N]) == 1


def test_soft_allows_day_as_first_shift_after_night_off():
    assert _night_off_return_penalty_for([ShiftType.N, ShiftType.O, ShiftType.O, ShiftType.D]) == 0


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
    # The default sample staffing needs two more shifts than 14 nurses can
    # provide with nine OFFs each.  Use a feasible configured OFF target here;
    # the exact-target behavior itself is covered by the focused hard-rule test.
    off_target = {n.name: target - 1 for n in nurses}
    result = generate_schedule(nurses, YEAR, MONTH, requirements, off_target, time_limit_seconds=30)
    assert result.feasible, f"실제 명단이 실행불가로 나옴: {result.infeasible_categories}"
    return nurses, requirements, off_target, result


def test_validator_passes_all_hard_rules(solved):
    """전수 검증기 통과 = 모든 하드 규칙(일별 인원, 개인 규칙, 오프 상한 등) 준수."""
    nurses, requirements, off_target, result = solved
    report = validate_schedule(nurses, YEAR, MONTH, result.assignments, requirements, off_target)
    assert report.ok, report.summary()


def test_daily_n_meets_minimum(solved):
    nurses, requirements, off_target, result = solved
    for day in month_dates(YEAR, MONTH):
        n_count = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.N)
        assert n_count >= requirements[day].N.minimum, f"{day}: N {n_count}명 < 하한"


def test_daily_staffing_meets_hard_minimums(solved):
    """Configured staffing minimums are hard constraints; targets are preferences."""
    nurses, requirements, _, result = solved
    assert result.feasible

    for day, req in requirements.items():
        d = sum(result.assignments[(nurse.name, day)] is ShiftType.D for nurse in nurses)
        e = sum(result.assignments[(nurse.name, day)] is ShiftType.E for nurse in nurses)
        n = sum(result.assignments[(nurse.name, day)] is ShiftType.N for nurse in nurses)
        assert d >= req.D.minimum, f"{day}: D={d}"
        assert e >= req.E.minimum, f"{day}: E={e}"
        assert n >= req.N.minimum, f"{day}: N={n}"


def test_daily_staffing_within_range(solved):
    nurses, requirements, off_target, result = solved
    for day in month_dates(YEAR, MONTH):
        req = requirements[day]
        d = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.D)
        e = sum(1 for n in nurses if result.assignments[(n.name, day)] == ShiftType.E)
        # S는 D/E/N 인원 규칙과 별개로 추가 배정된다.
        assert req.D.minimum <= d <= req.D.maximum, f"{day}: D={d}"
        assert req.E.minimum <= e <= req.E.maximum, f"{day}: E={e}"


def test_off_count_exactly_matches_target(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        o_count = sum(1 for d in days if result.assignments[(nurse.name, d)] == ShiftType.O)
        if nurse.is_night_dedicated:
            continue
        assert o_count == off_target[nurse.name], (
            f"{nurse.name}: O {o_count} != 목표 {off_target[nurse.name]}"
        )


def test_july_off_target_is_9():
    # 2026년 7월 = 주말 8일 + 제헌절 1일 (병동 기준 공휴일)
    assert compute_month_off_target(YEAR, MONTH, get_month_holidays(YEAR, MONTH)) == 9


def test_n_monthly_count_within_individual_cap(solved):
    # 월 N 개수는 개인 N상한(max_n_hard) 이하 (하한은 없음).
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        if ShiftType.N not in (nurse.allowed_shifts or set()) or nurse.max_n_hard <= 0:
            continue
        n_count = sum(1 for d in days if result.assignments[(nurse.name, d)] == ShiftType.N)
        assert n_count <= nurse.max_n_hard, f"{nurse.name}: 월 N {n_count}개 > 상한 {nurse.max_n_hard}"


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


def test_allowed_shifts_and_charge_rules(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for nurse in nurses:
        allowed = nurse.allowed_shifts or {ShiftType.D, ShiftType.E, ShiftType.N}
        for day in days:
            shift = result.assignments[(nurse.name, day)]
            if shift in (ShiftType.D, ShiftType.E, ShiftType.N):
                assert shift in allowed
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


def test_weekday_d_has_at_least_two_charge_capable_staff(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for day in days:
        if day.weekday() >= 5:
            continue  # 주말은 차지 1명이면 충분 (charge_placement가 보장)
        charge_d = sum(
            1
            for nurse in nurses
            if nurse.can_charge
            and result.assignments[(nurse.name, day)] == ShiftType.D
        )
        assert charge_d >= 2, f"{day}: 평일 D charge-capable staff {charge_d} < 2"


def test_weekend_d_has_at_least_one_charge_capable_staff(solved):
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    for day in days:
        if day.weekday() < 5:
            continue
        has_d = any(result.assignments[(n.name, day)] == ShiftType.D for n in nurses)
        charge_d = sum(
            1
            for nurse in nurses
            if nurse.can_charge and result.assignments[(nurse.name, day)] == ShiftType.D
        )
        if has_d:
            assert charge_d >= 1, f"{day}: 주말 D 차지 0명"


def test_senior_same_shift_cap(solved):
    # 데이 최대 2명 (하드). 이브닝은 소프트, 나이트는 제약 없음.
    nurses, requirements, off_target, result = solved
    days = month_dates(YEAR, MONTH)
    seniors = [n for n in nurses if n.level == NurseLevel.SENIOR_CHARGE]
    for day in days:
        senior_d = sum(
            1 for nurse in seniors if result.assignments[(nurse.name, day)] == ShiftType.D
        )
        assert senior_d <= 2, f"{day} D: senior staff {senior_d} > 2"


def test_ignored_duty_request_is_not_sent_to_solver():
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
        DutyRequest("n0", day, ShiftType.O, decision="ignore"),
    ]

    result = generate_schedule(
        nurses,
        YEAR,
        MONTH,
        requirements,
        off_target,
        duty_requests=duty_requests,
        time_limit_seconds=10,
    )

    assert result.feasible
    assert len(result.honored_duty_requests) == 1
    assert len(result.dropped_duty_requests) == 0
    assert result.honored_duty_requests[0].requested_shift == ShiftType.D


def test_avoid_duty_request_is_honored_when_shift_is_not_assigned():
    day = date(YEAR, MONTH, 1)
    request = DutyRequest("n0", day, ShiftType.N, kind="avoid")
    assignments = {("n0", day): ShiftType.D}

    honored, dropped = _split_duty_requests(assignments, [request])

    assert honored == [request]
    assert dropped == []


def test_avoid_duty_request_is_dropped_when_shift_is_assigned():
    day = date(YEAR, MONTH, 1)
    request = DutyRequest("n0", day, ShiftType.N, kind="avoid")
    assignments = {("n0", day): ShiftType.N}

    honored, dropped = _split_duty_requests(assignments, [request])

    assert honored == []
    assert dropped == [request]


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
    result = generate_schedule(nurses, YEAR, MONTH, requirements, off_target)
    assert not result.feasible
    assert "staffing_range" in result.infeasible_categories


def test_infeasible_when_all_nurses_night_unavailable():
    nurses = [
        Nurse(name=f"n{i}", can_charge=True, allowed_shifts={ShiftType.D, ShiftType.E}, max_n_hard=0)
        for i in range(3)
    ]
    template = (
        ShiftRequirement(minimum=1, maximum=1),
        ShiftRequirement(minimum=1, maximum=1),
        ShiftRequirement(minimum=1),
    )
    requirements = build_month_requirements(YEAR, MONTH, template, template)
    off_target = {n.name: 0 for n in nurses}
    result = generate_schedule(nurses, YEAR, MONTH, requirements, off_target)
    assert not result.feasible
    assert "allowed_shifts" in result.infeasible_categories
    assert "staffing_range" in result.infeasible_categories
